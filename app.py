"""Gradio 并排对比界面:python app.py"""
import time, cv2, gradio as gr

def fmt(out):
    rows = "\n".join(f"| {d['name']} | {d['weight_g']} | {d['kcal']} | {d.get('protein_g','')} | {d.get('fat_g','')} | {d.get('carb_g','')} |"
                     for d in out["dishes"])
    t = out["total"]; adv = "\n".join(f"- {x}" for x in out["advice"])
    return (f"| 菜品 | 重量g | 热量kcal | 蛋白g | 脂肪g | 碳水g |\n|---|---|---|---|---|---|\n{rows}\n\n"
            f"**合计:{t['kcal']} kcal**(蛋白 {t['protein_g']}g / 脂肪 {t['fat_g']}g / 碳水 {t['carb_g']}g)\n\n{adv}")

def go(path, goal, plate_cm):
    from detector import yolo_sam; from vlm import client; from hybrid import pipeline
    res = []
    for name, fn in (("A", lambda: yolo_sam.run(cv2.imread(path), goal, plate_cm)),
                     ("B", lambda: client.run(path, goal)), ("C", lambda: pipeline.run(path, goal, plate_cm))):
        t = time.time()
        try: o = fn(); txt = fmt(o) + f"\n\n耗时 {time.time()-t:.1f}s"; vis = o.get("_vis")
        except Exception as e: o, txt, vis = {}, f"出错:{e}", None
        res += [txt, cv2.cvtColor(vis, cv2.COLOR_BGR2RGB) if vis is not None else None]
    return res

with gr.Blocks(title="食堂餐盘热量估算") as demo:
    gr.Markdown("# 食堂餐盘热量估算:传统模型 vs 大模型 vs 融合\n> 仅供参考,不构成医疗建议")
    with gr.Row():
        img = gr.Image(type="filepath", label="餐盘照片"); goal = gr.Radio(["减脂", "维持", "增肌"], value="减脂", label="目标")
        plate = gr.Number(24, label="餐盘直径(cm)"); btn = gr.Button("开始对比")
    with gr.Row():
        with gr.Column(): gr.Markdown("### A YOLO+SAM"); ta = gr.Markdown(); ia = gr.Image(label="掩膜叠加")
        with gr.Column(): gr.Markdown("### B 多模态大模型"); tb = gr.Markdown(); ib = gr.Image(visible=False)
        with gr.Column(): gr.Markdown("### C 融合"); tc = gr.Markdown(); ic = gr.Image(label="检测结果")
    btn.click(go, [img, goal, plate], [ta, ia, tb, ib, tc, ic])
demo.launch()
