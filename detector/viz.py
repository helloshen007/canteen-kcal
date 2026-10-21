"""OpenCV 叠加掩膜 + PIL 写中文(cv2.putText 不支持中文,这是常见坑)。"""
import cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont
FONTS = ["C:/Windows/Fonts/msyh.ttc", "/System/Library/Fonts/PingFang.ttc",
         "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"]
def _font(size=22):
    for p in FONTS:
        try: return ImageFont.truetype(p, size)
        except OSError: pass
    return ImageFont.load_default()
def overlay(image_bgr, dishes, masks=None):
    out = image_bgr.copy(); rng = np.random.RandomState(1)
    for i, m in enumerate(masks if masks is not None else []):
        c = rng.randint(60, 255, 3); out[m > 0] = (0.5 * out[m > 0] + 0.5 * c).astype(np.uint8)
    pil = Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)); d = ImageDraw.Draw(pil); f = _font()
    for dish in dishes:
        x1, y1, x2, y2 = map(int, dish["box"]); d.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=3)
        d.text((x1 + 4, y1 + 2), f'{dish["name"]} {dish["weight_g"]}g {dish["kcal"]}kcal', fill=(255, 255, 0), font=f)
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
