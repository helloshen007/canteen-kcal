"""汇总方案A与方案B的对比表: python -m compare.report   (同时写入 docs/results.md)"""
import json, statistics as st
from pathlib import Path
from compare.evaluate import load_gt, name_f1, stability

METHODS = {"yolo_sam": "A YOLO-World+SAM", "vlm": "B 多模态大模型"}

def runs(method, iid, root="results"):
    """某方法在某张图上的所有结果文件(大模型有多次重复,取全部;否则取单个)。"""
    d = Path(root) / method
    files = sorted(d.glob(f"{iid}_r*.json")) or ([d / f"{iid}.json"] if (d / f"{iid}.json").exists() else [])
    return [json.load(open(f, encoding="utf-8")) for f in files]

def metrics(method, gt, base, diff=None):
    rows = []
    for iid, g in gt.items():
        if g["split"] != "test" or (diff and g["difficulty"] != diff): continue
        rs = runs(method, iid)
        if not rs: continue
        per = []
        for r in rs:
            pred = {x["name"] for x in r["dishes"]}; tp = len(pred & g["names"])
            per.append((tp / len(pred) if pred else 0.0, tp / len(g["names"]) if g["names"] else 0.0,
                        name_f1(pred, g["names"]), abs(sum(x["weight_g"] for x in r["dishes"]) - g["mass"]),
                        abs(r["total"]["kcal"] - g["kcal"])))
        rows.append([st.mean(c) for c in zip(*per)] + [abs(base - g["kcal"])])   # 每张图先对重复取平均
    if not rows: return None
    m = [round(st.mean(c), 2) for c in zip(*rows)]
    return len(rows), m

def main():
    gt = load_gt()
    base = st.mean(g["kcal"] for g in gt.values() if g["split"] == "calib")
    lines = ["| 方案 | 子集 | 图数 | 菜名P | 菜名R | 菜名F1 | 重量MAE(g) | 热量MAE(kcal) | 基线MAE(kcal) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for key, label in METHODS.items():
        for diff, dlabel in ((None, "全部"), ("single", "单一食材"), ("few", "2-3种"), ("many", "4种以上")):
            r = metrics(key, gt, base, diff)
            if r: lines.append(f"| {label} | {dlabel} | {r[0]} | " + " | ".join(str(v) for v in r[1]) + " |")
    sd = stability("vlm")
    lines += ["", f"- 基线:不看图,一律预测标定集平均热量({base:.1f} kcal)。",
              f"- 大模型稳定性:同一张图重复调用,总热量的平均标准差 = {sd} kcal(越小越稳)。"]
    text = "\n".join(lines); print(text)
    Path("docs").mkdir(exist_ok=True); open("docs/results.md", "w", encoding="utf-8").write(text + "\n")

if __name__ == "__main__":
    main()
