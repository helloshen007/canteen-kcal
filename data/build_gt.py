"""从 metadata.jsonl 生成:
  1) data/ingredient_nutrition.csv  食材营养密度表(每100g)
  2) data/ground_truth.csv          已下载图片的真值;区分"全部配料"与"图上看得见的食材"
     并按连续块划分 calib(标定,前2/3)/ test(测试,后1/3)"""
import csv, json, sys
from collections import defaultdict
sys.path.insert(0, ".")
from detector.vocab import INVISIBLE

rows = [json.loads(l) for l in open("data/raw/metadata.jsonl", encoding="utf-8")]
clean = lambda s: s.replace(":", " ").replace(";", " ").strip()

# 1) 食材营养密度 = 全部菜品里该食材的总营养 / 总克数 × 100
agg = defaultdict(lambda: dict(g=0.0, kcal=0.0, p=0.0, f=0.0, c=0.0, n=0))
for r in rows:
    for x in r["ingredients"]:
        a = agg[clean(x["name"])]
        a["g"] += x["grams"]; a["kcal"] += x["calories"]; a["p"] += x["protein"]
        a["f"] += x["fat"]; a["c"] += x["carb"]; a["n"] += 1
with open("data/ingredient_nutrition.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["name", "kcal", "protein", "fat", "carb", "count"])
    for name, a in sorted(agg.items(), key=lambda kv: -kv[1]["n"]):
        if a["g"] > 0:
            w.writerow([name] + [round(a[k] / a["g"] * 100, 2) for k in ("kcal", "p", "f", "c")] + [a["n"]])

# 2) 真值。ID 按时间排序,相邻编号常是同一盘菜的增量扫描,
#    所以按"连续块"划分而不是随机划分,以减少测试集泄漏。
ids = json.load(open("data/dish_ids.json"))
by_id = {r["id"]: r for r in rows}
cut = round(len(ids) * 2 / 3)
with open("data/ground_truth.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["image_id", "difficulty", "dishes", "total_kcal", "total_protein_g",
                "total_fat_g", "total_carb_g", "split", "total_mass_g",
                "visible_dishes", "visible_kcal", "visible_mass_g"])
    for i, d in enumerate(ids):
        r = by_id[d]
        vis = [x for x in r["ingredients"] if clean(x["name"]) not in INVISIBLE]
        n = len(vis)
        diff = "none" if n == 0 else ("single" if n == 1 else ("few" if n <= 3 else "many"))   # 难度=可见食材种类数
        fmt = lambda xs: ";".join(f'{clean(x["name"])}:{x["grams"]:g}' for x in xs)
        w.writerow([d, diff, fmt(r["ingredients"]), round(r["total_calories"], 1), round(r["total_protein"], 1),
                    round(r["total_fat"], 1), round(r["total_carb"], 1),
                    "calib" if i < cut else "test", round(r["total_mass"], 1),
                    fmt(vis), round(sum(x["calories"] for x in vis), 1), round(sum(x["grams"] for x in vis), 1)])
print("食材种类:", len(agg), "| 图片真值:", len(ids), "| 标定/测试 =", cut, "/", len(ids) - cut)