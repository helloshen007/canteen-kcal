"""一次性联通测试:读 .env 或环境变量,对一张图调用一次 VLM,只打印模型回答。

用法(项目根目录):
    .venv\\Scripts\\python.exe -m vlm.selftest
    .venv\\Scripts\\python.exe -m vlm.selftest --image data/images/dish_1556572657.jpg

安全约定:本脚本任何情况下都不打印密钥,只打印其长度。
"""
import argparse
import base64
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_IMAGE = ROOT / "data" / "images" / "dish_1556572657.jpg"
DEFAULT_PROMPT = "图里是什么食物?一句话回答"

# 按 base_url 判断该用哪些模型名,避免拿 Qwen 的名字去问 DeepSeek。
QWEN_MODELS = ["qwen3-vl-plus", "qwen-vl-max"]
DEEPSEEK_MODELS = ["deepseek-flash", "deepseek-v4-flash-vision-exp"]
FALLBACK_DEFAULT = QWEN_MODELS[0]
PROVIDER_MODELS = {"dashscope": QWEN_MODELS, "aliyuncs": QWEN_MODELS, "deepseek": DEEPSEEK_MODELS}


def candidate_models(model, base_url):
    """首选配置里的模型,再补上同厂商的备用名(去重)。"""
    cands = [model]
    b = (base_url or "").lower()
    extra = []
    for key, names in PROVIDER_MODELS.items():
        if key in b:
            extra = names
            break
    for name in extra:
        if name not in cands:
            cands.append(name)
    return cands


def load_dotenv(path):
    """极简 .env 解析;已存在的环境变量优先,不被文件覆盖。"""
    if not path.exists():
        return False
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, val)
    return True


def mask(secret):
    return f"***已读取(长度 {len(secret)})" if secret else "缺失"


def redact(text, secret=""):
    """把报错里的密钥痕迹抹掉。DeepSeek 会回显密钥末几位(如 'api key: ****heck')。"""
    if secret:
        text = text.replace(secret, "***")
    text = re.sub(r"(?i)(api[\s_-]?key\s*[:=]\s*\**)[^\s,;']+", r"\1***", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_\-]{6,}", "sk-***", text)
    return text


def call_no_thinking(image, prompt, model, key, base_url):
    """兜底:关掉思考模式、放大 max_tokens 再请求一次。
    deepseek-flash 默认开启思考模式,推理 token 也计入 max_tokens,
    小预算下可能只返回推理、content 为空。"""
    from openai import OpenAI

    b64 = base64.b64encode(pathlib.Path(image).read_bytes()).decode()
    mt = "image/png" if str(image).lower().endswith("png") else "image/jpeg"
    client = OpenAI(api_key=key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:{mt};base64,{b64}"}},
        ]}],
        extra_body={"thinking": {"type": "disabled"}},
    )
    return resp.choices[0].message.content


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", default=str(DEFAULT_IMAGE))
    ap.add_argument("--prompt", default=DEFAULT_PROMPT)
    args = ap.parse_args()

    dotenv_used = load_dotenv(ROOT / ".env")
    key = os.getenv("VLM_API_KEY", "").strip()
    provider = os.getenv("VLM_PROVIDER", "").strip() or "openai"
    base_url = os.getenv("VLM_BASE_URL", "").strip()
    model = os.getenv("VLM_MODEL", "").strip() or FALLBACK_DEFAULT

    # 关键:把解析出的默认值写回 os.environ,否则 vlm.client 会用它自己的
    # 默认值(provider=anthropic),把请求发去 Anthropic 而不是 DashScope。
    os.environ["VLM_PROVIDER"] = provider
    if provider == "openai" and not base_url:
        base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    if base_url:
        os.environ["VLM_BASE_URL"] = base_url

    print(f"项目根目录 : {ROOT}")
    print(f".env       : {'已加载' if dotenv_used else '未找到(使用当前环境变量)'}")
    print(f"VLM_PROVIDER: {provider}")
    print(f"VLM_BASE_URL: {base_url or '(空)'}")
    print(f"VLM_MODEL   : {model}")
    print(f"VLM_API_KEY : {mask(key)}")

    if not key:
        print("\n[失败] 没有密钥。请在项目根目录的 .env 里写一行 VLM_API_KEY=你的密钥")
        return 1

    image = pathlib.Path(args.image)
    if not image.exists():
        print(f"\n[失败] 图片不存在: {image}")
        return 1
    print(f"测试图片   : {image} ({image.stat().st_size} 字节)")
    print(f"提示词     : {args.prompt}\n")

    try:
        from vlm.client import call_vlm
    except Exception as exc:  # noqa: BLE001
        print(f"[失败] 导入 vlm.client 出错: {type(exc).__name__}: {exc}")
        return 1

    # 先试配置里的模型,遇到"模型不存在"再退到备用名;鉴权/网络错误不重试。
    tried = []
    candidates = candidate_models(model, base_url)
    for name in candidates:
        os.environ["VLM_MODEL"] = name
        tried.append(name)
        print(f"--- 尝试模型: {name} ---")
        try:
            answer = call_vlm(str(image), args.prompt)
        except Exception as exc:  # noqa: BLE001
            status = getattr(exc, "status_code", None)
            body = redact(str(exc), key)
            print(f"[失败] {type(exc).__name__} (HTTP {status})")
            print(body[:600])
            lowered = str(exc).lower()
            model_problem = status in (400, 404) and (
                "model" in lowered and ("not" in lowered or "unsupported" in lowered or "invalid" in lowered)
            )
            if model_problem and name != candidates[-1]:
                print(f"[提示] 模型 {name} 不可用,换下一个名字重试。\n")
                continue
            print("\n[结论] 这次调用没有成功,完整报错见上。")
            return 1
        if not (answer and str(answer).strip()):
            print("[失败] 接口返回成功,但回答内容是空的。")
            print("       最常见原因:deepseek-flash 默认开启思考模式(effort=high),")
            print("       推理 token 也计入 max_tokens,预算被推理吃光就没正文了。")
            if "deepseek" in (base_url or "").lower():
                print("       正在关闭思考模式 + 放大 max_tokens 重试一次...")
                try:
                    answer = call_no_thinking(str(image), args.prompt, name, key, base_url)
                except Exception as exc:  # noqa: BLE001
                    print(redact(f"[失败] 重试也出错: {type(exc).__name__}: {exc}", key)[:600])
                    answer = None
                if answer and str(answer).strip():
                    print("\n[成功] 模型回答(已关闭思考模式):")
                    print(answer)
                    print(f"\n[结论] 调用成功,模型 {name};但默认思考模式会返回空正文,方案 B 里要关掉它。")
                    return 0
            print("\n[结论] 调用没有拿到正文,请把上面的输出发我。")
            return 1

        print("\n[成功] 模型回答:")
        print(answer)
        print(f"\n[结论] 调用成功,使用模型 {name}。")
        return 0

    print(f"\n[结论] 所有模型名都试过了: {', '.join(tried)},均未成功。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
