"""阶段二(快):读取阶段一的特征,用标定集拟合"像素面积→克数"系数,在测试集上评估方案A。
用法: python -m detector.fit_eval [置信度阈值=0.15]
改阈值后直接重跑即可,不用重新跑模型。"""
import csv, json, statistics as st, sys
from collections import defaultdict
from pathlib import Path
import numpy as np
from compare.evaluate import load_gt, name_f1

FEAT, OUT = Path("results/features"), Path("results/yolo_sam")

def class_pixels(stem, thr):
    """{类别: (掩膜并集像素数, 最高置信度)}。同类别的多个掩膜取并集,避免重叠部分被重复计算。"""
    meta = json.load(open(FEAT / f"{stem}.json", encoding="utf-8"))
    masks = np.load(FEAT / f"{stem}.npz")["masks"]
    out = {}
    for d, m in zip(meta["dets"], masks):
        if d["conf"] < thr: continue
        u, c = out.get(d["name"], (np.zeros_like(m), 0.0))
        out[d["name"]] = (u | m, max(c, d["conf"]))
    return {k: (int(u.sum()), c) for k, (u, c) in out.items()}

def main():
    thr = float(sys.argv[1]) if len(sys.argv) > 1 else 0.15
    gt = load_gt()
    table = {r["name"]: r for r in csv.DictReader(open("data/ingredient_nutrition.csv", encoding="utf-8"))}
    px = {i: class_pixels(i, thr) for i in gt if (FEAT / f"{i}.json").exists()}

    # ---- 标定:克数/像素 的比值,只用标定集里"检测对了"的 (图, 类别) 配对;取中位数抗离群 ----
    ratios = defaultdict(list)
    for i, g in gt.items():
        if g["split"] != "calib" or i not in px: continue
        for name, (n, _) in px[i].items():
            if name in g["grams"] and n > 0:
                ratios[name].append(g["grams"][name] / n)
    allr = [r for v in ratios.values() for r in v]
    if not allr: sys.exit("标定集里没有任何检测对的配对,试试降低置信度阈值,如 python -m detector.fit_eval 0.05")
    k_global = st.median(allr)
    k_cls = {n: st.median(v) for n, v in ratios.items() if len(v) >= 3}   # 样本≥3 才用类别专属系数,否则用全局系数
    print(f"阈值={thr} | 标定配对 {len(allr)} 个 | 全局系数 {k_global:.5f} g/px | 类别专属系数 {len(k_cls)} 个")

    # ---- 预测:每张图每个检测到的类别 → 克数 → 热量,保存为统一格式 ----
    OUT.mkdir(parents=True, exist_ok=True)
    for i, g in gt.items():
        if i not in px: continue
        dishes = []
        for name, (n, c) in px[i].items():
            w = k_cls.get(name, k_global) * n
            t = table.get(name)
            nut = lambda key: round(w / 100 * float(t[key]), 1) if t else 0.0
            dishes.append({"name": name, "weight_g": round(w), "kcal": nut("kcal"), "protein_g": nut("protein"),
                           "fat_g": nut("fat"), "carb_g": nut("carb"), "conf": c})
        total = {k: round(sum(d[k] for d in dishes), 1) for k in ("kcal", "protein_g", "fat_g", "carb_g")}
        json.dump({"dishes": dishes, "total": total, "advice": [], "split": g["split"]},
                  open(OUT / f"{i}.json", "w", encoding="utf-8"), ensure_ascii=False)

    # ---- 测试集评估 ----
    base = st.mean(g["kcal"] for g in gt.values() if g["split"] == "calib")   # 基线:不看图,一律预测标定集平均热量
    rows = []
    for i, g in gt.items():
        if g["split"] != "test" or i not in px: continue
        r = json.load(open(OUT / f"{i}.json", encoding="utf-8"))
        pred = {d["name"] for d in r["dishes"]}; tp = len(pred & g["names"])
        rows.append({"diff": g["difficulty"], "f1": name_f1(pred, g["names"]),
                     "p": tp / len(pred) if pred else 0.0, "r": tp / len(g["names"]) if g["names"] else 0.0,
                     "kcal_err": abs(r["total"]["kcal"] - g["kcal"]), "base_err": abs(base - g["kcal"]),
                     "pct_err": abs(r["total"]["kcal"] - g["kcal"]) / max(g["kcal"], 1) * 100,
                     "w_err": abs(sum(d["weight_g"] for d in r["dishes"]) - g["mass"])})
    def show(tag, rs):
        m = lambda k: round(st.mean(x[k] for x in rs), 2)
        print(f"{tag:8s} n={len(rs):2d} | 菜名 P={m('p')} R={m('r')} F1={m('f1')} | 重量MAE={m('w_err')}g "
              f"| 热量MAE={m('kcal_err')} MAPE={m('pct_err')}% | 基线(平均值)MAE={m('base_err')}")
    print("\n==== 测试集(只算看得见的食材) ====")
    if not rows: sys.exit("没有测试图的特征,先跑 python -m detector.extract")
    show("全部", rows)
    for dname in ("single", "few", "many"):
        rs = [x for x in rows if x["diff"] == dname]
        if rs: show(dname, rs)

if __name__ == "__main__":
    main()