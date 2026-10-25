"""YOLO-World + SAM 特征提取。缓存仅在真值、营养表、词表及图片一致时复用。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import uuid

from compare.evaluate import load_gt
from compare.provenance import evaluation_context
from detector.vocab import candidate_names

OUT = Path("results/features")


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def nms_agnostic(dets, thr=0.6):
    kept = []
    for d in sorted(dets, key=lambda d: -d["conf"]):
        if all(iou(d["box"], k["box"]) < thr for k in kept):
            kept.append(d)
    return kept


def read_features(stem, feature_dir, context, image_sha256=None):
    """拒绝旧词表、缺掩膜、损坏文件及不匹配的图片缓存。"""
    import numpy as np
    feature_dir = Path(feature_dir)
    meta = json.loads((feature_dir / f"{stem}.json").read_text(encoding="utf-8"))
    if meta.get("context") != context:
        raise ValueError(f"{stem}: 特征上下文已过期，请重新提取")
    if image_sha256 is not None and meta.get("image_sha256") != image_sha256:
        raise ValueError(f"{stem}: 图片已改变，请重新提取")
    with np.load(feature_dir / f"{stem}.npz", allow_pickle=False) as saved:
        masks = saved["masks"]
    if masks.dtype != np.bool_ or masks.shape != (len(meta["dets"]), meta["h"], meta["w"]):
        raise ValueError(f"{stem}: 掩膜尺寸或数量错误")
    if any(d["name"] not in context["vocabulary"] for d in meta["dets"]):
        raise ValueError(f"{stem}: 检测类别不属于当前词表")
    return meta, masks


def archive_features(stem, feature_dir, results_root):
    existing = [Path(feature_dir) / f"{stem}.{ext}" for ext in ("json", "npz")]
    existing = [p for p in existing if p.exists()]
    if existing:
        destination = Path(results_root) / "archive/features" / uuid.uuid4().hex
        destination.mkdir(parents=True)
        for path in existing:
            shutil.move(str(path), str(destination / path.name))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("limit", nargs="?", type=int)
    parser.add_argument("--results-root", default="results")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        parser.error("limit 必须为正数")
    paths = [Path("data/images") / f"{iid}.jpg" for iid in sorted(load_gt())]
    if args.limit is not None:
        paths = paths[:args.limit]
    missing = [p.name for p in paths if not p.exists()]
    if missing:
        raise SystemExit(f"缺少 {len(missing)} 张原图，请先运行 python -m data.prepare。首项: {missing[0]}")
    if not paths:
        raise SystemExit("没有待处理图片")
    context = evaluation_context()
    out = Path(args.results_root) / "features"
    out.mkdir(parents=True, exist_ok=True)
    pending = []
    for p in paths:
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        try:
            read_features(p.stem, out, context, digest)
        except Exception:
            # 保留旧缓存，以免把重算结果与原始实验混淆。
            archive_features(p.stem, out, args.results_root)
            pending.append((p, digest))
    if not pending:
        print(f"{len(paths)} 张图片的当前特征缓存均有效，无需推理")
        return
    import cv2
    import numpy as np
    import torch
    from ultralytics import YOLOWorld, SAM
    dev = 0 if torch.cuda.is_available() else "cpu"
    yolo = YOLOWorld("yolov8s-worldv2.pt")
    yolo.set_classes(candidate_names())
    sam = SAM("sam_b.pt")
    for k, (p, digest) in enumerate(pending, 1):
        img = cv2.imread(str(p))
        if img is None:
            raise ValueError(f"无法读取图片: {p}")
        h, w = img.shape[:2]
        r = yolo.predict(img, conf=0.05, device=dev, verbose=False)[0]
        dets = [{"name": r.names[int(b.cls)], "conf": round(float(b.conf), 3),
                 "box": [round(v, 1) for v in b.xyxy[0].tolist()]} for b in r.boxes]
        dets = nms_agnostic(dets)[:20]
        masks = (sam(img, bboxes=[d["box"] for d in dets], device=dev, verbose=False)[0]
                 .masks.data.cpu().numpy().astype(bool)) if dets else np.zeros((0, h, w), bool)
        temporary = out / f"{p.stem}.npz.tmp"
        with temporary.open("wb") as stream:
            np.savez_compressed(stream, masks=masks)
        temporary.replace(out / f"{p.stem}.npz")
        meta = {"image": p.name, "h": h, "w": w, "dets": dets,
                "context": context, "image_sha256": digest,
                "settings": {"conf": 0.05, "nms_iou": 0.6, "max_detections": 20}}
        temporary = out / f"{p.stem}.json.tmp"
        temporary.write_text(json.dumps(meta, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        temporary.replace(out / f"{p.stem}.json")
        print(f"[{k}/{len(pending)}] {p.stem}: {len(dets)} 个框", flush=True)


if __name__ == "__main__":
    main()
