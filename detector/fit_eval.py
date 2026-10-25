"""用全部当前版本特征拟合面积→克数，再输出逐图预测与测试集评估。"""
import argparse
import csv
import hashlib
import json
import math
import shutil
import statistics as st
from collections import defaultdict
from pathlib import Path
import uuid

import numpy as np
from compare.evaluate import load_gt, name_f1
from compare.provenance import evaluation_context, load_prediction, write_json
from detector.extract import read_features

FEAT, OUT = Path("results/features"), Path("results/yolo_sam")


def class_pixels(stem, thr, feature_dir=None, context=None):
    """同类掩膜取并集；特征上下文不一致时拒绝使用。"""
    context = evaluation_context() if context is None else context
    feature_dir = FEAT if feature_dir is None else Path(feature_dir)
    image = Path("data/images") / f"{stem}.jpg"
    digest = hashlib.sha256(image.read_bytes()).hexdigest() if image.exists() else None
    meta, masks = read_features(stem, feature_dir, context, digest)
    out = {}
    for d, mask in zip(meta["dets"], masks):
        if d["conf"] < thr:
            continue
        union, confidence = out.get(d["name"], (np.zeros_like(mask), 0.0))
        out[d["name"]] = (union | mask, max(confidence, d["conf"]))
    return {name: (int(union.sum()), confidence) for name, (union, confidence) in out.items()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("threshold", nargs="?", type=float, default=0.15)
    parser.add_argument("--results-root", default="results")
    args = parser.parse_args(argv)
    threshold = args.threshold
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        parser.error("置信度阈值必须在 0–1 之间")
    root = Path(args.results_root)
    feature_dir, output = root / "features", root / "yolo_sam"
    context = evaluation_context()
    gt = load_gt()
    with open("data/ingredient_nutrition.csv", encoding="utf-8") as stream:
        table = {r["name"]: r for r in csv.DictReader(stream)}
    pixels, invalid = {}, []
    for iid in gt:
        try:
            pixels[iid] = class_pixels(iid, threshold, feature_dir, context)
        except Exception as exc:
            invalid.append(f"{iid}: {type(exc).__name__}")
    if invalid:
        raise SystemExit(f"缺失/过期/损坏特征 {len(invalid)}/{len(gt)}，未进行拟合。先按当前词表重新提取；首项 {invalid[0]}")
    ratios = defaultdict(list)
    for iid, g in gt.items():
        if g["split"] != "calib":
            continue
        for name, (n, _) in pixels[iid].items():
            if name in g["grams"] and n > 0:
                ratios[name].append(g["grams"][name] / n)
    all_ratios = [ratio for values in ratios.values() for ratio in values]
    if not all_ratios:
        raise SystemExit("标定集没有正确检测配对，无法拟合；不得使用测试集配对拟合")
    global_coefficient = st.median(all_ratios)
    coefficients = {name: st.median(values) for name, values in ratios.items() if len(values) >= 3}
    print(f"阈值={threshold} | 标定配对 {len(all_ratios)} 个 | 全局系数 {global_coefficient:.5f} g/px | 类别专属系数 {len(coefficients)} 个")
    output.mkdir(parents=True, exist_ok=True)
    calibration = {"context": context, "threshold": threshold, "global_g_per_pixel": global_coefficient,
                   "class_g_per_pixel": coefficients, "calibration_pairs": len(all_ratios),
                   "calibration_ids": [iid for iid, g in gt.items() if g["split"] == "calib"]}
    # 先验证所有食材均可换算，再写结果，防止缺营养表时生成零热量预测。
    missing_nutrition = {name for values in pixels.values() for name in values if name not in table}
    if missing_nutrition:
        raise SystemExit(f"营养表缺少检测类别: {sorted(missing_nutrition)}")
    write_json(root / "calibration.json", calibration)
    rows = []
    baseline = st.mean(g["kcal"] for g in gt.values() if g["split"] == "calib")
    archive = root / "archive/yolo_sam" / uuid.uuid4().hex
    for iid, g in gt.items():
        dishes = []
        for name, (n, confidence) in pixels[iid].items():
            weight = coefficients.get(name, global_coefficient) * n
            nutrition = table[name]
            nut = lambda key: round(weight / 100 * float(nutrition[key]), 1)
            dishes.append({"name": name, "weight_g": round(weight), "kcal": nut("kcal"),
                           "protein_g": nut("protein"), "fat_g": nut("fat"), "carb_g": nut("carb"), "conf": confidence})
        totals = {key: round(sum(d[key] for d in dishes), 1) for key in ("kcal", "protein_g", "fat_g", "carb_g")}
        result = {"status": "success", "context": context, "dishes": dishes, "total": totals,
                  "advice": [], "split": g["split"], "image_id": iid, "threshold": threshold}
        target = output / f"{iid}.json"
        if target.exists():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
            except (ValueError, UnicodeError):
                existing = None
            if existing != result:
                archive.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(archive / target.name))
        write_json(target, result)
        load_prediction(target, context)
        if g["split"] != "test":
            continue
        names = {d["name"] for d in dishes}
        true_positive = len(names & g["names"])
        rows.append({"image_id": iid, "difficulty": g["difficulty"], "precision": true_positive / len(names) if names else 0.0,
                     "recall": true_positive / len(g["names"]) if g["names"] else 0.0,
                     "f1": name_f1(names, g["names"]), "predicted_kcal": totals["kcal"], "true_kcal": g["kcal"],
                     "kcal_abs_error": abs(totals["kcal"] - g["kcal"]),
                     "weight_abs_error": abs(sum(d["weight_g"] for d in dishes) - g["mass"]),
                     "baseline_abs_error": abs(baseline - g["kcal"])})
    if not rows:
        raise SystemExit("没有测试集图像，未完成评估")
    with (root / "yolo_sam_per_image.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {"context": context, "baseline_kcal": baseline, "threshold": threshold, "subsets": {}}
    print("\n==== 测试集（只算已核实的可见食材） ====")
    for label, difficulty in (("全部", None), ("single", "single"), ("few", "few"), ("many", "many")):
        selected = [r for r in rows if difficulty is None or r["difficulty"] == difficulty]
        if not selected:
            continue
        means = {key: round(st.mean(r[key] for r in selected), 4) for key in
                 ("precision", "recall", "f1", "kcal_abs_error", "weight_abs_error", "baseline_abs_error")}
        means["n"] = len(selected)
        summary["subsets"][label] = means
        print(f"{label}: n={len(selected)} P={means['precision']:.4f} R={means['recall']:.4f} F1={means['f1']:.4f} "
              f"重量MAE={means['weight_abs_error']:.2f}g 热量MAE={means['kcal_abs_error']:.2f}kcal "
              f"基线MAE={means['baseline_abs_error']:.2f}kcal")
    write_json(root / "yolo_sam_summary.json", summary)


if __name__ == "__main__":
    main()
