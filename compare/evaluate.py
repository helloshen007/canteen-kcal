"""读取可见食材真值并评估成功且属于当前标注版本的逐图结果。"""
import argparse
import csv
import statistics as st
from pathlib import Path

from compare.provenance import evaluation_context, load_prediction


def load_gt(path="data/ground_truth.csv"):
    gt = {}
    with open(path, encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            grams = {}
            for item in row["visible_dishes"].split(";"):
                if item:
                    name, weight = item.rsplit(":", 1)
                    grams[name] = grams.get(name, 0.0) + float(weight)
            gt[row["image_id"]] = {"difficulty": row["difficulty"], "kcal": float(row["visible_kcal"]),
                                    "names": set(grams), "grams": grams, "split": row["split"],
                                    "mass": float(row["visible_mass_g"])}
    return gt


def name_f1(pred, true):
    tp = len(pred & true)
    if not pred or not true or tp == 0:
        return 0.0
    precision, recall = tp / len(pred), tp / len(true)
    return 2 * precision * recall / (precision + recall)


def evaluate(method, gt, root="results", context=None):
    context = evaluation_context() if context is None else context
    if method == "vlm":
        from compare.report import runs, nutrition_table
        table = nutrition_table()
    rows = []
    for iid, g in gt.items():
        if g["split"] != "test":
            continue
        if method == "vlm":
            results = runs(method, iid, root, context, table)
        else:
            path = Path(root) / method / f"{iid}.json"
            results = [load_prediction(path, context)] if path.exists() else []
        if not results:
            continue
        f1 = st.mean(name_f1({x["name"] for x in result["dishes"]}, g["names"]) for result in results)
        error = st.mean(abs(result["total"]["kcal"] - g["kcal"]) for result in results)
        rows.append({"id": iid, "diff": g["difficulty"], "f1": f1,
                     "abs_err": error, "pct_err": error / g["kcal"] * 100 if g["kcal"] > 0 else None})
    return rows


def summarize_rows(rows):
    if not rows:
        return None
    percentages = [row["pct_err"] for row in rows if row["pct_err"] is not None]
    return {"n": len(rows), "F1": round(st.mean(r["f1"] for r in rows), 3),
            "MAE_kcal": round(st.mean(r["abs_err"] for r in rows), 1),
            "MAPE_%": round(st.mean(percentages), 1) if percentages else None}


def stability(method, root="results", image_ids=None, context=None):
    """只统计指定测试图；失败与旧版预测均不能变成零热量。"""
    context = evaluation_context() if context is None else context
    if image_ids is None:
        image_ids = [iid for iid, g in load_gt().items() if g["split"] == "test"]
    from compare.report import runs
    deviations = []
    for iid in image_ids:
        results = runs(method, iid, root, context)
        if len(results) > 1:
            deviations.append(st.pstdev(r["total"]["kcal"] for r in results))
    return round(st.mean(deviations), 1) if deviations else None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", default="results")
    args = parser.parse_args()
    gt = load_gt()
    for method in ("yolo_sam", "vlm"):
        rows = evaluate(method, gt, args.results_root)
        print(method, "成功结果（同图重复先取平均）:", summarize_rows(rows), "稳定性:", stability(method, args.results_root))
        print("测试图覆盖:", len(rows), "/", sum(g["split"] == "test" for g in gt.values()))
