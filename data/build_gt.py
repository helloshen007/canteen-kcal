"""Generate nutrition table and 40/20 ground truth from fixed metadata and IDs.

python -m data.build_gt
Labels are corrected by ingredient ID; see docs/annotation-audit.md.
"""
import csv
import json
from collections import defaultdict
from pathlib import Path

from data.labels import INVISIBLE, ingredient_name


def build_ground_truth(metadata_path="data/raw/metadata.jsonl", ids_path="data/dish_ids.json",
                       output_dir="data"):
    with open(metadata_path, encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream if line.strip()]
    with open(ids_path, encoding="utf-8") as stream:
        ids = json.load(stream)
    if not ids or len(ids) != len(set(ids)) or ids != sorted(ids):
        raise ValueError("dish IDs must be unique, nonempty, and in chronological order")
    by_id = {r["id"]: r for r in rows}
    missing = set(ids) - by_id.keys()
    if missing:
        raise ValueError(f"metadata missing dish IDs: {sorted(missing)}")
    for iid in ids:
        for ingredient in by_id[iid]["ingredients"]:
            name = ingredient_name(ingredient)
            if name.startswith("unresolved "):
                raise ValueError(f"{iid}: {name} needs manual label review before evaluation")

    aggregate = defaultdict(lambda: dict(g=0.0, kcal=0.0, p=0.0, f=0.0, c=0.0, n=0))
    for row in rows:
        for ingredient in row["ingredients"]:
            stats = aggregate[ingredient_name(ingredient)]
            for target, source in (("g", "grams"), ("kcal", "calories"),
                                   ("p", "protein"), ("f", "fat"), ("c", "carb")):
                stats[target] += ingredient[source]
            stats["n"] += 1

    # Construct both outputs before writing, so an unresolved selected label
    # cannot leave a partly updated ground-truth/nutrition pair.
    nutrition_rows = []
    for name, stats in sorted(aggregate.items(), key=lambda item: -item[1]["n"]):
        if stats["g"] > 0:
            nutrition_rows.append([name] + [round(stats[key] / stats["g"] * 100, 2)
                                           for key in ("kcal", "p", "f", "c")] + [stats["n"]])

    cut = round(len(ids) * 2 / 3)
    truth_rows = []
    for index, iid in enumerate(ids):
        row = by_id[iid]
        ingredients = row["ingredients"]
        visible = [x for x in ingredients if ingredient_name(x) not in INVISIBLE]
        count = len({ingredient_name(x) for x in visible})
        difficulty = "none" if count == 0 else "single" if count == 1 else "few" if count <= 3 else "many"

        def format_grams(items):
            grams = {}
            for item in items:
                name = ingredient_name(item)
                grams[name] = grams.get(name, 0.0) + item["grams"]
            return ";".join(f"{name}:{weight:g}" for name, weight in grams.items())

        truth_rows.append([iid, difficulty, format_grams(ingredients),
                           round(row["total_calories"], 1), round(row["total_protein"], 1),
                           round(row["total_fat"], 1), round(row["total_carb"], 1),
                           "calib" if index < cut else "test", round(row["total_mass"], 1),
                           format_grams(visible), round(sum(x["calories"] for x in visible), 1),
                           round(sum(x["grams"] for x in visible), 1)])
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, header, output_rows in (
        ("ingredient_nutrition.csv", ["name", "kcal", "protein", "fat", "carb", "count"], nutrition_rows),
        ("ground_truth.csv", ["image_id", "difficulty", "dishes", "total_kcal", "total_protein_g",
                              "total_fat_g", "total_carb_g", "split", "total_mass_g",
                              "visible_dishes", "visible_kcal", "visible_mass_g"], truth_rows),
    ):
        temporary = output_dir / (filename + ".tmp")
        with temporary.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            writer.writerows(output_rows)
        temporary.replace(output_dir / filename)
    print(f"食材种类: {len(nutrition_rows)} | 图片真值: {len(ids)} | 标定/测试 = {cut}/{len(ids)-cut}")
    return {"images": len(ids), "calib": cut, "test": len(ids) - cut}


if __name__ == "__main__":
    build_ground_truth()
