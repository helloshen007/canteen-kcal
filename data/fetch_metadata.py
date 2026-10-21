"""下载 metadata.jsonl,先只看前两行的结构"""
import json
from huggingface_hub import hf_hub_download

p = hf_hub_download("Sebastianrtj/food-nutrients", "metadata.jsonl",
                    repo_type="dataset", local_dir="data/raw")
lines = open(p, encoding="utf-8").read().splitlines()
print("共", len(lines), "行")
for l in lines[:2]:
    print(l[:1200])
    print("---")
print("第1行字段:", list(json.loads(lines[0]).keys()))