"""vlm 包。

导入本包时自动加载项目根目录的 .env(已存在的环境变量优先,不会被文件覆盖)。
这样下面两种用法都不需要先在终端里 export 那四个 VLM_* 变量:
    python -m vlm.run_vlm 3
    python -c "from vlm.client import call_vlm; print(call_vlm('data/images/dish_1556572657.jpg','图里是什么食物?一句话回答'))"

安全约定:.env 已在 .gitignore 中,任何代码都不应把密钥打印出来。
"""
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path=None):
    """极简 .env 解析:KEY=VALUE,支持 # 注释与成对引号,BOM 兼容。返回是否读到文件。"""
    p = Path(path) if path else _ROOT / ".env"
    if not p.exists():
        return False
    for raw in p.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, val)
    return True


load_dotenv()
