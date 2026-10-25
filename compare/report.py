"""对齐当前真值的逐图评估；默认拒绝缺失结果，历史汇总表不会被覆盖。"""
import argparse
import csv
import re
import statistics as st
from pathlib import Path

from compare.evaluate import load_gt, name_f1
from compare.provenance import evaluation_context, load_prediction, write_json

METHODS = {"yolo_sam": "A YOLO-World+SAM", "vlm": "B 多模态大模型"}


def nutrition_table():
    with open("data/ingredient_nutrition.csv", encoding="utf-8") as stream:
        return {row["name"]: row for row in csv.DictReader(stream)}


def validate_vlm_result(prediction, context, table):
    """成功标签不能取代原始回复校验；必须能从 raw 重建同一份预测。"""
    from vlm.run_vlm import to_result
    if prediction.get("parse_ok") is not True or not isinstance(prediction.get("raw"), str):
        raise ValueError("VLM 缺少明确解析成功标记或原始回复")
    rebuilt = to_result(prediction["raw"], context["vocabulary"], table)
    if any(rebuilt[key] != prediction[key] for key in ("dishes", "total")):
        raise ValueError("VLM 预测与原始回复/当前营养表不一致")


def runs(method, iid, root="results", context=None, table=None):
    context = evaluation_context() if context is None else context
    directory = Path(root) / method
    indexed = []
    for path in directory.glob(f"{iid}_r*.json"):
        match = re.fullmatch(re.escape(iid) + r"_r(\d+)\.json", path.name)
        if match:
            indexed.append((int(match[1]), path))
    indexed.sort()
    if indexed and [i for i, _ in indexed] != list(range(len(indexed))):
        raise ValueError(f"{method}/{iid}: 重复次数必须从 r0 连续编号，不得缺失或重复")
    files = [path for _, path in indexed] or ([directory / f"{iid}.json"] if (directory / f"{iid}.json").exists() else [])
    predictions = [load_prediction(path, context) for path in files]
    if method == "vlm" and predictions and table is None:
        table = nutrition_table()
    signatures = set()
    for prediction in predictions:
        if prediction.get("image_id", iid) != iid:
            raise ValueError(f"{method}/{iid}: 图片编号与预测文件名不一致")
        if method == "vlm":
            validate_vlm_result(prediction, context, table)
            experiment = prediction.get("experiment")
            if not isinstance(experiment, dict) or any(not isinstance(experiment.get(key), str) or not experiment[key]
                                                      for key in ("provider", "model", "prompt", "image_id")):
                raise ValueError(f"vlm/{iid}: 缺少可核实的模型、提示词或图片编号")
            if experiment["image_id"] != iid:
                raise ValueError(f"vlm/{iid}: 实验图片编号与文件名不一致")
            if not isinstance(experiment.get("disable_thinking", "0"), str):
                raise ValueError(f"vlm/{iid}: 思考模式配置无效")
            signatures.add(tuple(experiment.get(key, "0") for key in ("provider", "model", "prompt", "disable_thinking", "endpoint_sha256")))
    if len(signatures) > 1:
        raise ValueError(f"vlm/{iid}: 同一图片混入不同模型/提示词的重复结果")
    return predictions


def row_metrics(results, g, baseline):
    per_run = []
    for result in results:
        names = {d["name"] for d in result["dishes"]}
        tp = len(names & g["names"])
        per_run.append((tp / len(names) if names else 0.0, tp / len(g["names"]) if g["names"] else 0.0,
                        name_f1(names, g["names"]), abs(sum(d["weight_g"] for d in result["dishes"]) - g["mass"]),
                        abs(result["total"]["kcal"] - g["kcal"])))
    return [st.mean(column) for column in zip(*per_run)] + [abs(baseline - g["kcal"])]


def metrics(method, gt, base, diff=None, root="results", context=None):
    rows = []
    table = nutrition_table() if method == "vlm" else None
    for iid, g in gt.items():
        if g["split"] != "test" or (diff and g["difficulty"] != diff):
            continue
        predictions = runs(method, iid, root, context, table)
        if predictions:
            rows.append(row_metrics(predictions, g, base))
    if not rows:
        return None
    return len(rows), [round(st.mean(column), 2) for column in zip(*rows)]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", default="results")
    parser.add_argument("--output", help="默认 <results-root>/report.md")
    parser.add_argument("--allow-partial", action="store_true", help="明确生成覆盖不完整的局部复验报告，不宣称两方案都成功")
    args = parser.parse_args(argv)
    root, context, gt = Path(args.results_root), evaluation_context(), load_gt()
    table = nutrition_table()
    baseline = st.mean(g["kcal"] for g in gt.values() if g["split"] == "calib")
    test_ids = [iid for iid, g in gt.items() if g["split"] == "test"]
    collected, issues, per_image = {}, [], []
    fields = ["method", "image_id", "difficulty", "status", "repeats", "precision", "recall", "f1", "weight_mae_g", "kcal_mae", "baseline_mae", "true_kcal", "true_mass_g"]
    for method in METHODS:
        collected[method] = {}
        for iid in test_ids:
            g = gt[iid]
            try:
                results = runs(method, iid, root, context, table)
                if not results:
                    status = "failed" if any((root / method / "failures").rglob(f"{iid}*.json")) else "missing"
                else:
                    status = "success"
            except (OSError, ValueError) as exc:
                results, status = [], "invalid"
            record = {"method": method, "image_id": iid, "difficulty": g["difficulty"], "status": status,
                      "repeats": len(results), "true_kcal": g["kcal"], "true_mass_g": g["mass"]}
            if status == "success":
                collected[method][iid] = results
                values = row_metrics(results, g, baseline)
                record.update(dict(zip(fields[5:11], values)))
            else:
                issues.append({"method": method, "image_id": iid, "status": status})
            per_image.append(record)
    if issues and not args.allow_partial:
        counts = {status: sum(i["status"] == status for i in issues) for status in ("missing", "failed", "invalid")}
        raise SystemExit(f"结果不完整 {counts}，未生成报告。修复后重跑；单独复验可显式加 --allow-partial。")
    signatures = {tuple(result["experiment"].get(key, "0") for key in ("provider", "model", "prompt", "disable_thinking", "endpoint_sha256"))
                  for results in collected["vlm"].values() for result in results}
    if len(signatures) > 1:
        raise SystemExit("VLM 测试图混入多套模型/提示词/思考配置，不能汇总为同一实验。")
    lines = ["# 当前标注版本复验" + ("（覆盖不完整）" if issues else ""),
             "", f"- 真值/营养表/词表指纹: `{context['data_sha256']}`。",
             f"- 基线: 标定集平均可见热量 {baseline:.2f} kcal。", "",
             "| 方案 | 子集 | 图数 | 菜名P | 菜名R | 菜名F1 | 重量MAE(g) | 热量MAE(kcal) | 基线MAE(kcal) |",
             "|---|---|---|---|---|---|---|---|---|"]
    summary = {"context": context, "baseline_kcal": baseline, "expected_test_images": len(test_ids), "coverage": {}, "issues": issues, "metrics": {}}
    for method, label in METHODS.items():
        coverage = len(collected[method])
        summary["coverage"][method] = {"success": coverage, "expected": len(test_ids)}
        summary["metrics"][method] = {}
        for difficulty, label_subset in ((None, "全部"), ("single", "单一食材"), ("few", "2-3种"), ("many", "4种以上")):
            selected = [row_metrics(predictions, gt[iid], baseline) for iid, predictions in collected[method].items()
                        if difficulty is None or gt[iid]["difficulty"] == difficulty]
            if not selected:
                continue
            values = [round(st.mean(column), 4 if index < 3 else 2) for index, column in enumerate(zip(*selected))]
            summary["metrics"][method][label_subset] = {"n": len(selected), **dict(zip(fields[5:11], values))}
            lines.append(f"| {label} | {label_subset} | {len(selected)} | " + " | ".join(str(v) for v in values) + " |")
        lines += []
    lines += ["", "## 覆盖与失败"]
    for method, label in METHODS.items():
        lines.append(f"- {label}: 有效 {len(collected[method])}/{len(test_ids)} 张。失败/缺失/过期结果不计为零热量，也不计入已评估图数。")
    repeated = [st.pstdev(result["total"]["kcal"] for result in results)
                for results in collected["vlm"].values() if len(results) > 1]
    deviation = round(st.mean(repeated), 2) if repeated else None
    summary["vlm_stability_kcal"] = deviation
    lines.append(f"- 大模型稳定性（仅当前测试集成功重复预测）: {deviation} kcal。" if deviation is not None else "- 大模型稳定性: 未计算；缺少同图成功重复预测。")
    if issues:
        lines += ["", "不完整结果详见同目录逐图 CSV 和 JSON；本报告不是两个方案均已完成的声明。"]
    target = Path(args.output) if args.output else root / "report.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with target.with_suffix(".per-image.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(per_image)
    write_json(target.with_suffix(".json"), {**summary, "per_image": per_image})
    print("\n".join(lines))


if __name__ == "__main__":
    main()
