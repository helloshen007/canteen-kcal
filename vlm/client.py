"""方案B:调用多模态大模型。环境变量配置,密钥不要写进代码或提交到仓库!
  VLM_PROVIDER = anthropic | openai   (openai 表示 OpenAI 兼容接口,Qwen-VL/GPT-4o 等都可用)
  VLM_MODEL, VLM_API_KEY, VLM_BASE_URL(openai 兼容时填)"""
import base64, json, os, re

def _img_b64(path):
    with open(path, "rb") as f: return base64.b64encode(f.read()).decode()

def call_vlm(image_path, prompt):
    provider = os.getenv("VLM_PROVIDER", "anthropic"); model = os.getenv("VLM_MODEL", "claude-sonnet-4-6")
    b64 = _img_b64(image_path); mt = "image/png" if image_path.lower().endswith("png") else "image/jpeg"
    if provider == "anthropic":
        import anthropic
        c = anthropic.Anthropic(api_key=os.getenv("VLM_API_KEY"))
        r = c.messages.create(model=model, max_tokens=1500, messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}},
            {"type": "text", "text": prompt}]}])
        return r.content[0].text
    from openai import OpenAI
    c = OpenAI(api_key=os.getenv("VLM_API_KEY"), base_url=os.getenv("VLM_BASE_URL"))
    r = c.chat.completions.create(model=model, max_tokens=1500, messages=[{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:{mt};base64,{b64}"}},
        {"type": "text", "text": prompt}]}])
    return r.choices[0].message.content

def parse_json(text):
    """容错解析:去掉 ```json 围栏,截取第一个 { 到最后一个 }。失败返回 None。"""
    text = re.sub(r"```(?:json)?", "", text)
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j < 0: return None
    try: return json.loads(text[i:j + 1])
    except json.JSONDecodeError: return None

def normalize(d):
    """统一成与方案A相同的输出格式,缺失字段补 0,total 缺失时自动求和。"""
    if not d: return {"dishes": [], "total": {"kcal": 0, "protein_g": 0, "fat_g": 0, "carb_g": 0}, "advice": [], "parse_error": True}
    dishes = [{"name": str(x.get("name", "?")), **{k: float(x.get(k) or 0) for k in
              ("weight_g", "kcal", "protein_g", "fat_g", "carb_g")}, "reason": x.get("reason", "")} for x in d.get("dishes", [])]
    total = d.get("total") or {}
    for k in ("kcal", "protein_g", "fat_g", "carb_g"):
        total[k] = float(total.get(k) or sum(x[k] for x in dishes))
    adv = d.get("advice", []); adv = [adv] if isinstance(adv, str) else adv
    return {"dishes": dishes, "total": total, "advice": adv}

def run(image_path, goal="减脂", prompt_style="structured_ref"):
    from vlm.prompts import PROMPTS
    return normalize(parse_json(call_vlm(image_path, PROMPTS[prompt_style](goal))))
