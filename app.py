"""并排展示(读取已保存的结果,无需现场跑模型):python app.py"""
import json
from pathlib import Path
import cv2, numpy as np
from PIL import Image, ImageDraw
from compare.evaluate import load_gt
from detector.viz import _font

GT = load_gt()
TEST_IDS = [i for i, g in GT.items() if g["split"] == "test"]

def table(dishes, total_kcal, title):
    rows = "\n".join(f"| {d['name']} | {d['weight_g']} | {d['kcal']} |" for d in dishes) or "| (无) | | |"
    return f"**{title}**\n\n| 食材 | 克 | 千卡 |\n|---|---|---|\n{rows}\n\n合计 **{total_kcal} kcal**"

def draw_detections(image_id):
    img = cv2.imread(f"data/images/{image_id}.jpg")
    fp = Path("results/features") / f"{image_id}"
    if not fp.with_suffix(".json").exists(): return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    meta = json.load(open(fp.with_suffix(".json"), encoding="utf-8"))
    masks = np.load(fp.with_suffix(".npz"))["masks"]; rng = np.random.RandomState(1)
    for m in masks:
        img[m] = (0.5 * img[m] + 0.5 * rng.randint(60, 255, 3)).astype(np.uint8)
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB)); d = ImageDraw.Draw(pil); f = _font(16)
    for det in meta["dets"]:
        b = det["box"]; d.rectangle(b, outline=(255, 0, 0), width=2)
        d.text((b[0] + 2, b[1] + 1), f"{det['name']} {det['conf']:.2f}", fill=(255, 255, 0), font=f)
    return np.array(pil)

def case(image_id):
    g = GT[image_id]
    gt_dishes = [{"name": n, "weight_g": round(w), "kcal": "-"} for n, w in g["grams"].items()]
    out = [Image.open(f"data/images/{image_id}.jpg"), draw_detections(image_id),
           table(gt_dishes, round(g["kcal"], 1), f"真值(难度:{g['difficulty']},只含看得见的食材)")]
    for m, title in (("yolo_sam", "方案A YOLO-World+SAM"), ("vlm", "方案B 多模态大模型")):
        f = Path("results") / m / f"{image_id}.json"
        if f.exists():
            r = json.load(open(f, encoding="utf-8")); out.append(table(r["dishes"], r["total"]["kcal"], title))
        else:
            out.append(f"**{title}**\n\n(还没有结果)")
    return out

def main():
    import gradio as gr
    with gr.Blocks(title="食堂餐盘营养估算:传统模型 vs 大模型") as demo:
        gr.Markdown("# 餐盘食材与热量估算:YOLO-World+SAM vs 多模态大模型\n数据:Nutrition5k 子集(测试集)。仅供参考,不构成医疗建议。")
        dd = gr.Dropdown(TEST_IDS, value=TEST_IDS[0], label="选择测试图")
        with gr.Row():
            raw = gr.Image(label="原图"); det = gr.Image(label="方案A 检测+分割")
        with gr.Row():
            tg, ta, tb = gr.Markdown(), gr.Markdown(), gr.Markdown()
        dd.change(case, dd, [raw, det, tg, ta, tb]); demo.load(case, dd, [raw, det, tg, ta, tb])
    demo.launch()

if __name__ == "__main__":
    main()
