"""冒烟测试:YOLO-World(文字类别)检测 → SAM 框提示分割 → 保存叠加图
用法: python detector/try_world.py dish_1556572657"""
import csv, sys
import cv2, numpy as np, torch
from PIL import Image, ImageDraw
from ultralytics import YOLOWorld, SAM
from detector.viz import _font

dish = sys.argv[1] if len(sys.argv) > 1 else "dish_1556572657"
img = cv2.imread(f"data/images/{dish}.jpg")

# 候选类别来自整个数据集的食材词表(不偷看这张图的答案),排除不可见的调料
INVISIBLE = {"olive oil", "salt", "pepper", "vinegar", "garlic", "deprecated", "water"}
names = [r["name"] for r in csv.DictReader(open("data/ingredient_nutrition.csv", encoding="utf-8"))
         if r["name"] not in INVISIBLE][:40]

dev = 0 if torch.cuda.is_available() else "cpu"
yolo = YOLOWorld("yolov8s-worldv2.pt")
yolo.set_classes(names)
r = yolo.predict(img, conf=0.05, device=dev, verbose=False)[0]
dets = sorted([(r.names[int(b.cls)], float(b.conf), b.xyxy[0].tolist()) for b in r.boxes],
              key=lambda d: -d[1])[:6]
for n, c, b in dets:
    print(f"{n:22s} conf={c:.2f} box={[round(v) for v in b]}")
if not dets:
    sys.exit("没检测到任何东西,把 conf 调低或换一张图试试")

sam = SAM("sam_b.pt")
masks = sam(img, bboxes=[d[2] for d in dets], verbose=False)[0].masks.data.cpu().numpy()
vis = img.copy(); rng = np.random.RandomState(1)
for m in masks:
    vis[m > 0] = (0.5 * vis[m > 0] + 0.5 * rng.randint(60, 255, 3)).astype(np.uint8)
pil = Image.fromarray(cv2.cvtColor(vis, cv2.COLOR_BGR2RGB)); d = ImageDraw.Draw(pil); f = _font(18)
for n, c, b in dets:
    d.rectangle(b, outline=(255, 0, 0), width=2)
    d.text((b[0] + 3, b[1] + 2), f"{n} {c:.2f}", fill=(255, 255, 0), font=f)
pil.save(f"docs/try_{dish}.jpg")
print("已保存 docs/try_" + dish + ".jpg")