"""评估:菜品识别 F1、总热量 MAE/MAPE(按难度分组)、大模型多次调用稳定性。
结果文件约定: results/<method>/<image_id>.json (多次重复为 <image_id>_r0.json, _r1.json ...)"""
import csv, json, statistics as st
from collections import defaultdict
from pathlib import Path

def load_gt(path="data/ground_truth.csv"):
    """读取真值。评估只看"图上看得见的食材"(visible_*),调料油盐等看不见的热量不计入。"""
    gt = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        grams = {x.rsplit(":", 1)[0]: float(x.rsplit(":", 1)[1]) for x in r["visible_dishes"].split(";") if x}
        gt[r["image_id"]] = {"difficulty": r["difficulty"], "kcal": float(r["visible_kcal"]), "names": set(grams),
                             "grams": grams, "split": r["split"], "mass": float(r["visible_mass_g"])}
    return gt

def name_f1(pred, true):
    tp = len(pred & true)
    if not pred or not true or tp == 0: return 0.0
    p, r = tp / len(pred), tp / len(true); return 2 * p * r / (p + r)

def evaluate(method, gt, root="results"):
    rows = []
    for iid, g in gt.items():
        if g["split"] != "test": continue          # 只在测试集上评估
        f = Path(root) / method / f"{iid}.json"
        if not f.exists(): continue
        d = json.load(open(f, encoding="utf-8"))
        names = {x["name"] for x in d["dishes"]}; kcal = d["total"]["kcal"]
        rows.append({"id": iid, "diff": g["difficulty"], "f1": name_f1(names, g["names"]),
                     "abs_err": abs(kcal - g["kcal"]), "pct_err": abs(kcal - g["kcal"]) / g["kcal"] * 100})
    return rows

def summarize_rows(rows):
    if not rows: return None
    return {"n": len(rows), "F1": round(st.mean(r["f1"] for r in rows), 3),
            "MAE_kcal": round(st.mean(r["abs_err"] for r in rows), 1),
            "MAPE_%": round(st.mean(r["pct_err"] for r in rows), 1)}

def stability(method, root="results"):
    """同一张图多次调用的总热量标准差(越小越稳)。"""
    groups = defaultdict(list)
    for f in Path(root, method).glob("*_r*.json"):
        groups[f.stem.rsplit("_r", 1)[0]].append(json.load(open(f, encoding="utf-8"))["total"]["kcal"])
    sds = [st.pstdev(v) for v in groups.values() if len(v) > 1]
    return round(st.mean(sds), 1) if sds else None

if __name__ == "__main__":
    gt = load_gt()
    for m in ("yolo_sam", "vlm", "hybrid"):
        rows = evaluate(m, gt); print(f"\n== {m} ==  整体:", summarize_rows(rows), " 稳定性(kcal标准差):", stability(m))
        by = defaultdict(list)
        for r in rows: by[r["diff"]].append(r)
        for k, v in by.items(): print(f"  [{k}]", summarize_rows(v))