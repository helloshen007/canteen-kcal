"""Export auditable per-image evidence without packaging credentials or weights."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from vlm.run_vlm import to_result
SENSITIVE_KEYS = {"api_key", "apikey", "access_token", "refresh_token", "password", "secret", "authorization"}


def digest(content):
    return hashlib.sha256(content).hexdigest()


def contains_credentials(value):
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower().replace("-", "_")
            if (normalized in SENSITIVE_KEYS or normalized.endswith(("_api_key", "_token", "_password", "_secret"))) and item:
                return True
            if contains_credentials(item):
                return True
    elif isinstance(value, list):
        return any(contains_credentials(item) for item in value)
    return False


def finite(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def prediction_schema(value):
    if not isinstance(value, dict) or not isinstance(value.get("dishes"), list):
        return False
    if value.get("parse_ok") is False or value.get("parse_error"):
        return False
    names = set()
    for item in value["dishes"]:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"] or item["name"] in names:
            return False
        names.add(item["name"])
        if not all(finite(item.get(key)) for key in ("weight_g", "kcal")):
            return False
    kcal = value.get("total", {}).get("kcal") if isinstance(value.get("total"), dict) else None
    return finite(kcal) and abs(kcal - sum(item["kcal"] for item in value["dishes"])) <= 0.11


def classify(value, method, context, nutrition_table):
    if not isinstance(value, dict):
        return "invalid"
    if value.get("status") == "failed":
        return "failed"
    if not prediction_schema(value):
        return "invalid"
    if value.get("status") != "success" or not value.get("context"):
        return "legacy_unverified"
    if value.get("context") != context:
        return "stale_context"
    if any(item["name"] not in context["vocabulary"] for item in value["dishes"]):
        return "invalid"
    if method == "vlm":
        experiment = value.get("experiment")
        if value.get("parse_ok") is not True or not isinstance(experiment, dict):
            return "invalid"
        if any(not isinstance(experiment.get(key), str) or not experiment[key]
               for key in ("provider", "model", "prompt", "image_id")):
            return "invalid"
        if not isinstance(value.get("raw"), str) or not value["raw"].strip():
            return "invalid"
        try:
            normalized = to_result(value["raw"], context["vocabulary"], nutrition_table)
        except (KeyError, TypeError, ValueError, OverflowError):
            return "invalid"
        if any(normalized[key] != value[key] for key in ("dishes", "total")):
            return "invalid"
    return "schema_valid"


def export(root, results_root, output, include_images=False, expected_repeats=3):
    root, results_root = Path(root).resolve(), Path(results_root).resolve()
    output = Path(output).resolve()
    gt_path = root / "data/ground_truth.csv"
    with gt_path.open(encoding="utf-8") as stream:
        gt = {row["image_id"]: row for row in csv.DictReader(stream)}
    with (root / "data/ingredient_nutrition.csv").open(encoding="utf-8") as stream:
        nutrition_table = {row["name"]: row for row in csv.DictReader(stream)}
    ids = set(gt)
    tests = sorted(iid for iid, row in gt.items() if row["split"] == "test")
    context_digest = hashlib.sha256()
    for name in ("data/ground_truth.csv", "data/ingredient_nutrition.csv"):
        context_digest.update(name.encode())
        context_digest.update((root / name).read_bytes())
    vocabulary = sorted({item.rsplit(":", 1)[0].strip() for row in gt.values()
                         for item in row["visible_dishes"].split(";") if item})
    context_digest.update(json.dumps(vocabulary, ensure_ascii=False).encode())
    current_context = {"data_sha256": context_digest.hexdigest(), "vocabulary": vocabulary}
    records, payloads, omitted = [], {}, []
    source_files = ["data/dish_ids.json", "data/ground_truth.csv", "data/ingredient_nutrition.csv",
                    "data/annotation_overrides.json", "data/annotation_review.csv", "data/source_revision.json",
                    "data/labels.py", "detector/vocab.py", "docs/annotation-audit.md"]
    for name in source_files:
        path = root / name
        if path.is_file() and path.resolve().is_relative_to(root):
            payloads[name] = path.read_bytes()
    metadata_sha256 = None
    metadata = root / "data/raw/metadata.jsonl"
    if metadata.is_file() and metadata.resolve().is_relative_to(root):
        source = metadata.read_bytes()
        metadata_sha256 = digest(source)
        selected_lines = []
        for line in source.splitlines():
            if line.strip() and json.loads(line).get("id") in ids:
                selected_lines.append(line)
        payloads["data/raw/metadata_subset.jsonl"] = b"\n".join(selected_lines) + b"\n"
    if include_images:
        for iid in sorted(ids):
            path = root / "data/images" / f"{iid}.jpg"
            if path.is_file() and path.resolve().is_relative_to(root):
                payloads[f"data/images/{path.name}"] = path.read_bytes()
    for method in ("features", "yolo_sam", "vlm"):
        directory = results_root / method
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or not path.resolve().is_relative_to(results_root):
                continue
            relative = path.relative_to(results_root)
            matched = next((iid for iid in ids if re.match(re.escape(iid) + r"(?:[._]|$)", path.name)), None)
            if matched is None or path.suffix.lower() not in {".json", ".npz", ".txt"}:
                continue
            # Only per-image files and the named raw/failure trees are allowed.
            if len(relative.parts) > 2 and relative.parts[1] not in {"raw", "failures"}:
                continue
            if method == "features" and path.suffix not in {".json", ".npz"}:
                continue
            if method != "features" and path.suffix != ".json" and not (method == "vlm" and relative.parts[1] == "raw" and path.suffix == ".txt"):
                continue
            content = path.read_bytes()
            record = {"path": relative.as_posix(), "image_id": matched, "method": method,
                      "sha256": digest(content), "bytes": len(content), "state": "feature" if method == "features" else "raw_reply"}
            if path.suffix == ".json":
                try:
                    value = json.loads(content)
                except (UnicodeError, ValueError):
                    record["state"] = "invalid_json"
                else:
                    if contains_credentials(value):
                        omitted.append({"path": relative.as_posix(), "reason": "credential_field_present"})
                        continue
                    if method == "features" and isinstance(value, dict) and value.get("context") != current_context:
                        record["state"] = "feature_stale_context"
                    if method != "features":
                        record["state"] = classify(value, method, current_context, nutrition_table)
                        record["raw_present"] = isinstance(value, dict) and isinstance(value.get("raw"), str) and bool(value["raw"].strip())
                        context = value.get("context") if isinstance(value, dict) else None
                        if isinstance(context, dict):
                            record["context"] = context
                        if method == "vlm" and record["state"] == "schema_valid":
                            experiment = value["experiment"]
                            if experiment["image_id"] != matched:
                                record["state"] = "invalid_image_id"
                            signature = {key: experiment.get(key, "0") for key in ("provider", "model", "prompt", "disable_thinking", "endpoint_sha256")}
                            record["experiment_sha256"] = digest(json.dumps(signature, sort_keys=True, ensure_ascii=False).encode())
            records.append(record)
            payloads[f"results/{relative.as_posix()}"] = content
    for name in ("calibration.json", "yolo_sam_summary.json", "yolo_sam_per_image.csv"):
        path = results_root / name
        if path.is_file() and path.resolve().is_relative_to(results_root):
            content = path.read_bytes()
            if path.suffix == ".json" and contains_credentials(json.loads(content)):
                omitted.append({"path": name, "reason": "credential_field_present"})
                continue
            payloads[f"results/{name}"] = content
    coverage = {}
    for iid in tests:
        image = {}
        for method in ("yolo_sam", "vlm"):
            relevant = [r for r in records if r["image_id"] == iid and r["method"] == method]
            valid = [r for r in relevant if r["state"] == "schema_valid" and "/failures/" not in r["path"] and "/raw/" not in r["path"]]
            repeats = [r for r in valid if re.fullmatch(re.escape(iid) + r"_r\d+\.json", Path(r["path"]).name)]
            numbered = sorted(int(re.search(r"_r(\d+)\.json$", r["path"])[1]) for r in repeats)
            repeat_sequence_valid = not numbered or numbered == list(range(len(numbered)))
            selected = repeats or [r for r in valid if Path(r["path"]).name == f"{iid}.json"]
            image[method] = {"valid_predictions": len(selected), "repeat_sequence_valid": repeat_sequence_valid, "raw_replies": sum(r.get("raw_present", False) for r in selected),
                             "files": [r["path"] for r in relevant], "states": sorted(set(r["state"] for r in relevant)),
                             "missing": not selected or not repeat_sequence_valid}
        coverage[iid] = image
    experiment_signatures = sorted({r["experiment_sha256"] for r in records
                                    if r["image_id"] in tests and r["state"] == "schema_valid" and "experiment_sha256" in r})
    manifest = {"format_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                "context": current_context, "source_metadata_sha256": metadata_sha256,
                "validation_scope": "Prediction schema, explicit success status and current data context; model accuracy is not validated. Coverage is not task acceptance.",
                "expected_test_images": tests, "expected_vlm_repeats": expected_repeats,
                "vlm_experiment_consistent": len(experiment_signatures) <= 1,
                "vlm_experiment_signatures": experiment_signatures,
                "coverage_complete": len(experiment_signatures) <= 1 and all(not item[m]["missing"] for item in coverage.values() for m in ("yolo_sam", "vlm")),
                "vlm_repetitions_complete": all(item["vlm"]["repeat_sequence_valid"] and item["vlm"]["valid_predictions"] >= expected_repeats for item in coverage.values()),
                "coverage": coverage, "records": records, "omitted": omitted,
                "files_sha256": {name: digest(content) for name, content in payloads.items()},
                "source_sha256": {name: digest(content) for name, content in payloads.items() if name.startswith("data/") and not name.startswith("data/images/")},
                "raw_reply_warning": "Raw model text is preserved as evidence. Review its content before sharing. No environment, credentials, weights, or virtualenv is exported."}
    payloads["manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, content in sorted(payloads.items()):
                archive.writestr(name, content)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", default="results")
    parser.add_argument("--output", default="results/evidence.zip")
    parser.add_argument("--include-images", action="store_true")
    parser.add_argument("--expected-repeats", type=int, default=3)
    args = parser.parse_args()
    if args.expected_repeats < 1:
        parser.error("--expected-repeats must be positive")
    manifest = export(ROOT, args.results_root, args.output, args.include_images, args.expected_repeats)
    missing = sum(item[method]["missing"] for item in manifest["coverage"].values() for method in ("yolo_sam", "vlm"))
    print(f"Exported {args.output}; {len(manifest['records'])} evidence files; {missing} missing image/method pairs; {len(manifest['omitted'])} credential-bearing records omitted.")


if __name__ == "__main__":
    main()
