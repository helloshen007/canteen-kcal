"""Live adapters for the original two pipelines. Never turn an exception into 0 kcal."""
import csv
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import time
from rq.timeouts import JobTimeoutException

from PIL import Image, ImageOps

from compare.provenance import evaluation_context
from detector.extract import nms_agnostic
from detector.vocab import candidate_names
from web.config import ROOT


class InferenceError(Exception):
    """A message safe to show in the UI (never an upstream HTTP response body)."""


def nutrition():
    with (ROOT/'data/ingredient_nutrition.csv').open(encoding='utf-8') as stream:
        return {row['name']:row for row in csv.DictReader(stream)}


def prepare_input(source, destination):
    # Both live methods receive these exact same pixels. Calibration used 640×480.
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert('RGB')
        image = ImageOps.contain(image,(640,480))
        canvas = Image.new('RGB',(640,480),(245,245,240))
        canvas.paste(image,((640-image.width)//2,(480-image.height)//2))
        canvas.save(destination)
    return hashlib.sha256(Path(destination).read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def load_models(model_directory, vocabulary):
    directory = Path(model_directory)
    required = ('yolov8s-worldv2.pt','sam_b.pt','clip/ViT-B-32.pt')
    if any(not (directory/name).is_file() for name in required):
        raise InferenceError('本地模型尚未准备好，请先运行模型准备命令')
    os.environ.setdefault('YOLO_CONFIG_DIR',str(directory/'config'))
    import torch
    torch.set_num_threads(max(1,int(os.getenv('TORCH_NUM_THREADS','2'))))
    from ultralytics import SAM, YOLOWorld, settings
    settings.update({'weights_dir':str(directory)})
    # Ultralytics snapshots this cache path at import; keep the CLIP loader in
    # sync with the configured weight volume while retaining its SHA validation.
    import ultralytics.nn.text_model as text_model
    text_model.WEIGHTS_DIR = directory
    device = 0 if torch.cuda.is_available() else 'cpu'
    yolo = YOLOWorld(str(directory/'yolov8s-worldv2.pt'))
    yolo.set_classes(list(vocabulary))
    return yolo,SAM(str(directory/'sam_b.pt')),device


def run_a(image_path, directory, settings):
    started = time.monotonic()
    import cv2
    import numpy as np
    from detector.viz import _font
    from PIL import ImageDraw

    context = evaluation_context()
    calibration = json.loads((ROOT/'evidence/revalidated/calibration.json').read_text())
    if calibration['context'] != context:
        raise InferenceError('标定系数与当前数据版本不一致，请重新标定')
    yolo,sam,device = load_models(str(settings.model_dir),tuple(candidate_names()))
    image = cv2.imread(str(image_path))
    prediction = yolo.predict(image,conf=calibration['threshold'],device=device,verbose=False)[0]
    detections = [{'name':prediction.names[int(box.cls)],'conf':round(float(box.conf),3),
                   'box':[round(v,1) for v in box.xyxy[0].tolist()]} for box in prediction.boxes]
    detections = nms_agnostic(detections)[:20]
    masks = (sam(image,bboxes=[d['box'] for d in detections],device=device,verbose=False)[0].masks.data.cpu().numpy().astype(bool)
             if detections else np.zeros((0,*image.shape[:2]),dtype=bool))
    unions = {}
    for detection,mask in zip(detections,masks):
        name = detection['name']
        unions[name] = unions.get(name,np.zeros_like(mask)) | mask
    table = nutrition()
    dishes = []
    for name,mask in unions.items():
        grams = int(mask.sum()) * calibration['class_g_per_pixel'].get(name,calibration['global_g_per_pixel'])
        row = {'name':name,'weight_g':round(grams)}
        for target,source in (('kcal','kcal'),('protein_g','protein'),('fat_g','fat'),('carb_g','carb')):
            row[target] = round(grams/100*float(table[name][source]),1)
        dishes.append(row)
    out = image.copy()
    rng = np.random.RandomState(1)
    for mask in masks:
        out[mask] = (out[mask]*0.5+rng.randint(60,255,3)*0.5).astype(np.uint8)
    visual = Image.fromarray(cv2.cvtColor(out,cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(visual)
    for detection in detections:
        x1,y1,x2,y2 = detection['box']
        draw.rectangle((x1,y1,x2,y2),outline='#e76f51',width=2)
        draw.text((x1+2,y1+2),f"{detection['name']} {detection['conf']:.2f}",font=_font(14),fill='#ffef94')
    visual.save(directory/'overlay.jpg',quality=90)
    totals = {key:round(sum(d[key] for d in dishes),1) for key in ('kcal','protein_g','fat_g','carb_g')}
    return {'status':'success','dishes':dishes,'total':totals,'detections':detections,
            'context':context,'seconds':round(time.monotonic()-started,2),
            'provenance':{'mode':'live','model':'YOLO-World yolov8s-worldv2 + SAM sam_b',
                          'calibration':'40-image calibration set','threshold':calibration['threshold']}}


def run_b(image_path,directory,settings):
    from vlm.client import call_vlm, resolve_model_name
    from vlm.run_vlm import PROMPT, redact, to_result
    if not os.getenv('VLM_API_KEY') or not os.getenv('VLM_MODEL'):
        raise InferenceError('多模态服务尚未配置，请由管理员在服务器环境中设置 API')
    started = time.monotonic()
    failures = []
    vocab = candidate_names()
    prompt = PROMPT.format(vocab=', '.join(vocab))
    for attempt in range(2):
        raw = None
        try:
            timeout = max(10, min(600, int(os.getenv('VLM_TIMEOUT_SECONDS', '120'))))
            raw = call_vlm(str(image_path),prompt,timeout=timeout)
            parsed = to_result(raw,vocab,nutrition())
        except JobTimeoutException:
            raise
        except Exception as exc:
            failures.append({'status':'failed','attempt':attempt+1,'error_type':type(exc).__name__,
                             'raw':redact(raw) if isinstance(raw,str) else None})
            continue
        parsed.update(raw=redact(raw),seconds=round(time.monotonic()-started,2),context=evaluation_context(),
                      provenance={'mode':'live','model':resolve_model_name(os.environ['VLM_MODEL']),
                                  'provider':os.getenv('VLM_PROVIDER','anthropic'),'prompt':prompt,'attempts':attempt+1})
        if failures:
            (directory/'b_failures.json').write_text(json.dumps(failures,ensure_ascii=False,allow_nan=False))
        return parsed
    (directory/'b_failures.json').write_text(json.dumps(failures,ensure_ascii=False,allow_nan=False))
    raise InferenceError('多模态请求或回复校验失败（已尝试 2 次），可单独重试方案 B')
