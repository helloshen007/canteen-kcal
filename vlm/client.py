"""方案B:调用多模态大模型。环境变量配置,密钥不要写进代码或提交到仓库!
  VLM_PROVIDER = anthropic | openai   (openai 表示 OpenAI 兼容接口,Qwen-VL/GPT-4o 等都可用)
  VLM_MODEL, VLM_API_KEY, VLM_BASE_URL(openai 兼容时填)"""
import base64, json, math, os, re

def _img_b64(path):
    with open(path, "rb") as f: return base64.b64encode(f.read()).decode()

def call_vlm(image_path, prompt):
    provider = os.getenv("VLM_PROVIDER", "anthropic"); model = os.getenv("VLM_MODEL", "claude-sonnet-4-6")
    if provider not in {"anthropic", "openai"}:
        raise ValueError("VLM_PROVIDER 必须为 anthropic 或 openai")
    if not os.getenv("VLM_API_KEY"):
        raise ValueError("缺少 VLM_API_KEY，请通过环境设置或本地 .env 配置")
    if provider == "openai" and not os.getenv("VLM_MODEL"):
        raise ValueError("OpenAI 兼容接口需要显式配置 VLM_MODEL")
    b64 = _img_b64(image_path); mt = "image/png" if image_path.lower().endswith("png") else "image/jpeg"
    if provider == "anthropic":
        import anthropic
        c = anthropic.Anthropic(api_key=os.getenv("VLM_API_KEY"))
        r = c.messages.create(model=model, max_tokens=1500, messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}},
            {"type": "text", "text": prompt}]}])
        return r.content[0].text
    from openai import OpenAI
    c = OpenAI(api_key=os.getenv("VLM_API_KEY"), base_url=os.getenv("VLM_BASE_URL") or None)
    extra = {"thinking": {"type": "disabled"}} if os.getenv("VLM_DISABLE_THINKING", "0").lower() in {"1", "true"} else None
    r = c.chat.completions.create(model=model, max_tokens=1500, extra_body=extra, messages=[{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": f"data:{mt};base64,{b64}"}},
        {"type": "text", "text": prompt}]}])
    return r.choices[0].message.content

def parse_json(text):
    """容错解析:去掉 ```json 围栏,截取第一个 { 到最后一个 }。失败返回 None。"""
    if not isinstance(text, str): return None
    text = re.sub(r"```(?:json)?", "", text)
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j < 0: return None
    try: return json.loads(text[i:j + 1])
    except json.JSONDecodeError: return None

def normalize(d):
    """验证旧的结构化接口；缺失字段和解析失败不能静默补成零。"""
    if not isinstance(d, dict) or not isinstance(d.get("dishes"), list):
        raise ValueError("无效模型回复，不能归一化为零热量预测")
    keys = ("weight_g", "kcal", "protein_g", "fat_g", "carb_g")
    def number(value):
        try:
            valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value >= 0
        except OverflowError:
            valid = False
        if not valid:
            raise ValueError("营养和重量必须是非负有限数值")
        return float(value)
    dishes = []
    for item in d["dishes"]:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValueError("菜品名称无效")
        if any(key not in item for key in keys):
            raise ValueError("菜品缺少重量或营养字段")
        dishes.append({"name":item["name"], **{key:number(item[key]) for key in keys}, "reason":item.get("reason", "")})
    supplied = d.get("total", {})
    if not isinstance(supplied, dict):
        raise ValueError("total 必须是对象")
    total = {key:number(supplied[key]) if key in supplied else number(sum(x[key] for x in dishes))
             for key in keys[1:]}
    advice = d.get("advice", [])
    if isinstance(advice, str): advice = [advice]
    return {"dishes":dishes, "total":total, "advice":advice}

def run(image_path, goal="减脂", prompt_style="structured_ref"):
    from vlm.prompts import PROMPTS
    return normalize(parse_json(call_vlm(image_path, PROMPTS[prompt_style](goal))))
