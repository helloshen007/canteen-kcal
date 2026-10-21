"""阶段一(慢,只需跑一次):对每张图跑 YOLO-World + SAM,
保存检测框/置信度/掩膜到 results/features/。之后的标定与评估直接读这些文件,调参不用重跑模型。
用法: python -m detector.extract [最多处理张数]      (支持断点续跑,已处理的会跳过)"""
import json, sys
from pathlib import Path
from detector.vocab import candidate_names

OUT = Path("results/features")

def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0

def nms_agnostic(dets, thr=0.6):
    """跨类别去重:框重叠超过 thr 时只留置信度高的(解决同一物体被标成 olives 又标成 blueberries)。"""
    kept = []
    for d in sorted(dets, key=lambda d: -d["conf"]):
        if all(iou(d["box"], k["box"]) < thr for k in kept):
            kept.append(d)
    return kept

def main():
    import cv2, numpy as np, torch
    from ultralytics import YOLOWorld, SAM
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10**9
    OUT.mkdir(parents=True, exist_ok=True)
    dev = 0 if torch.cuda.is_available() else "cpu"
    yolo = YOLOWorld("yolov8s-worldv2.pt"); yolo.set_classes(candidate_names())
    sam = SAM("sam_b.pt")
    paths = sorted(Path("data/images").glob("*.jpg"))[:limit]
    for k, p in enumerate(paths, 1):
        if (OUT / f"{p.stem}.json").exists(): continue
        img = cv2.imread(str(p)); h, w = img.shape[:2]
        r = yolo.predict(img, conf=0.05, device=dev, verbose=False)[0]
        dets = [{"name": r.names[int(b.cls)], "conf": round(float(b.conf), 3),
                 "box": [round(v, 1) for v in b.xyxy[0].tolist()]} for b in r.boxes]
        dets = nms_agnostic(dets)[:20]
        if dets:
            masks = sam(img, bboxes=[d["box"] for d in dets], verbose=False)[0].masks.data.cpu().numpy().astype(bool)
        else:
            masks = np.zeros((0, h, w), bool)
        np.savez_compressed(OUT / f"{p.stem}.npz", masks=masks)
        json.dump({"image": p.name, "h": h, "w": w, "dets": dets},
                  open(OUT / f"{p.stem}.json", "w", encoding="utf-8"), ensure_ascii=False)   # 最后写 json,存在即代表处理完整
        print(f"[{k}/{len(paths)}] {p.stem}: {len(dets)} 个框,", sorted({d['name'] for d in dets}))

if __name__ == "__main__":
    main()