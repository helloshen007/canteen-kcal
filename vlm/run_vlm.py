"""方案B:大模型只回答"有哪些食材 + 各多少克",名称限定在词表内;热量用与方案A同一张营养表计算。
用法: python -m vlm.run_vlm [重复次数=3]
环境变量: VLM_PROVIDER=openai  VLM_API_KEY=...  VLM_BASE_URL=...  VLM_MODEL=..."""
import csv, json, sys, time
from pathlib import Path
from compare.evaluate import load_gt
from detector.vocab import candidate_names
from vlm.client import call_vlm, parse_json

OUT = Path("results/vlm")
PROMPT = """你是食物营养分析助手。这是一张食堂餐盘的俯拍照片(盘子放在秤台上)。
请判断盘中有哪些食物,并估计每种食物的重量(克)。
要求:
1. 食物名称只能从下面的列表中选择,原样输出英文名,列表之外的一律不要输出:
{vocab}
2. 只列出图中能看到的食物,不要猜测看不见的调料或油。
3. 重量用克表示,是你对该食物在盘中总量的估计。
4. 只输出一个 JSON,不要任何其他文字,格式:
{{"items":[{{"name":"strawberries","grams":57}}]}}"""

def to_result(text, vocab, table):
    """解析大模型回复 → 与方案A相同的统一格式。名称不在词表里的丢弃并记录。"""
    d = parse_json(text) or {}
    canon = {v.lower(): v for v in vocab}
    grams, dropped = {}, []
    for it in (d.get("items", []) if isinstance(d, dict) else []):
        if not isinstance(it, dict): continue
        name = canon.get(str(it.get("name", "")).strip().lower())
        try: g = float(it.get("grams"))
        except (TypeError, ValueError): g = 0.0
        if name is None: dropped.append(it.get("name")); continue
        grams[name] = grams.get(name, 0.0) + max(g, 0.0)
    dishes = []
    for name, g in grams.items():
        t = table.get(name)
        nut = lambda k: round(g / 100 * float(t[k]), 1) if t else 0.0
        dishes.append({"name": name, "weight_g": round(g), "kcal": nut("kcal"), "protein_g": nut("protein"),
                       "fat_g": nut("fat"), "carb_g": nut("carb")})
    total = {k: round(sum(x[k] for x in dishes), 1) for k in ("kcal", "protein_g", "fat_g", "carb_g")}
    return {"dishes": dishes, "total": total, "advice": [], "dropped": dropped, "parse_ok": bool(d)}

def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    reps = int(argv[0]) if argv else 3
    gt = load_gt(); vocab = candidate_names()
    table = {r["name"]: r for r in csv.DictReader(open("data/ingredient_nutrition.csv", encoding="utf-8"))}
    prompt = PROMPT.format(vocab=", ".join(vocab))
    OUT.mkdir(parents=True, exist_ok=True)
    ids = [i for i, g in gt.items() if g["split"] == "test"]          # 只跑测试集,省时间和费用
    for n, iid in enumerate(ids, 1):
        img = Path("data/images") / f"{iid}.jpg"
        for k in range(reps):
            f = OUT / f"{iid}_r{k}.json"
            if f.exists(): continue                                    # 断点续跑
            t = time.time()
            for attempt in range(3):                                   # 网络/限流偶发失败自动重试
                try:
                    text = call_vlm(str(img), prompt)
                    # 空正文多半是思考模式把 max_tokens 吃光了,当成失败重试,别静默写进结果
                    if not (text and str(text).strip()):
                        raise ValueError("空回答(可能是思考模式占满 max_tokens)")
                    break
                except Exception as e:
                    print("  重试", attempt + 1, type(e).__name__, str(e)[:80]); time.sleep(3)
            else:
                print("  跳过", iid, k); continue
            res = to_result(text, vocab, table); res["seconds"] = round(time.time() - t, 2); res["raw"] = text
            json.dump(res, open(f, "w", encoding="utf-8"), ensure_ascii=False)
            if k == 0: json.dump(res, open(OUT / f"{iid}.json", "w", encoding="utf-8"), ensure_ascii=False)
            print(f"[{n}/{len(ids)}] {iid} r{k}: {[ (d['name'], d['weight_g']) for d in res['dishes']]} 丢弃={res['dropped']}")

if __name__ == "__main__":
    main()
