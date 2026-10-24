"""临时自检:验证 vlm/run_vlm.py 的解析逻辑(不需要密钥)。跑完即删。"""
import csv
import sys
import pathlib

ROOT = pathlib.Path(r"D:\code\canteen-kcal")
sys.path.insert(0, str(ROOT))

from vlm.run_vlm import to_result, PROMPT  # noqa: E402
from detector.vocab import candidate_names  # noqa: E402

vocab = candidate_names()
table = {r["name"]: r for r in csv.DictReader(open(ROOT / "data/ingredient_nutrition.csv", encoding="utf-8"))}

print("olives /100g:", {k: table["olives"][k] for k in ("kcal", "protein", "fat", "carb")})
print()

cases = {
    "大小写混用": '{"items":[{"name":"Olives","grams":36}]}',
    "词表外":     '{"items":[{"name":"pizza","grams":200},{"name":"olives","grams":30}]}',
    "脏克数":     '{"items":[{"name":"olives","grams":"abc"}]}',
    "重复合并":   '{"items":[{"name":"olives","grams":20},{"name":"olives","grams":16}]}',
    "解析失败":   "抱歉,我无法回答这个问题。",
    "代码围栏":   '```json\n{"items":[{"name":"strawberries","grams":57}]}\n```',
}

for label, text in cases.items():
    r = to_result(text, vocab, table)
    dishes = [(d["name"], d["weight_g"], d["kcal"]) for d in r["dishes"]]
    print(f"{label:8s} parse_ok={str(r['parse_ok']):5s} dishes={dishes} dropped={r['dropped']} total_kcal={r['total']['kcal']}")

print()
r = to_result(cases["大小写混用"], vocab, table)
print(f"真值对照: 模型答 36g olives -> 算得 {r['total']['kcal']} kcal;真值 41.4 kcal;误差 {abs(r['total']['kcal'] - 41.4):.1f}")
print()

p = PROMPT.format(vocab=", ".join(vocab))
print("prompt 长度:", len(p), "| 无残留花括号:", "{{" not in p, "| 含 olives:", "olives" in p)
