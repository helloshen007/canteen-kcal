"""列出 HuggingFace 仓库文件并下载前 N 张图,文件名保留菜品编号 dish_xxxxxxxxxx.jpg"""
import json, sys, time
from pathlib import Path
from huggingface_hub import HfApi, hf_hub_download
from PIL import Image

REPO = "Sebastianrtj/food-nutrients"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 60

files = sorted(HfApi().list_repo_files(REPO, repo_type="dataset"))
print("仓库共", len(files), "个文件")
print("非 test/ 目录的文件(可能是真值):", [f for f in files if not f.startswith("test/")][:20])

imgs = [f for f in files if f.startswith("test/") and f.lower().endswith(".png")][:N]
out = Path("data/images"); out.mkdir(parents=True, exist_ok=True)
ids = []
for i, f in enumerate(imgs):
    for attempt in range(3):                      # 镜像不稳定,失败自动重试
        try:
            p = hf_hub_download(REPO, f, repo_type="dataset", local_dir="data/raw")
            break
        except Exception as e:
            print("重试", attempt + 1, f, type(e).__name__); time.sleep(2)
    else:
        print("跳过", f); continue
    dish_id = Path(f).stem
    Image.open(p).convert("RGB").save(out / f"{dish_id}.jpg")
    ids.append(dish_id)
    print(i + 1, "/", len(imgs), dish_id)

json.dump(ids, open("data/dish_ids.json", "w"), indent=1)
print("保存了", len(ids), "张;前3个编号:", ids[:3])