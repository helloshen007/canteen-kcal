"""下载已提交的固定清单和原始元数据，不覆盖 dish_ids.json。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault('HF_HOME', str(ROOT / 'data/raw/.hf-cache'))
os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
REPO = 'Sebastianrtj/food-nutrients'
REVISION = 'bb00a088f5b963635da23711766af90e25b9f4a9'


def main(argv=None):
    from huggingface_hub import hf_hub_download
    from PIL import Image
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata-only', action='store_true')
    args = parser.parse_args(argv)
    def download(filename):
        return hf_hub_download(REPO, filename, repo_type='dataset', revision=REVISION,
                               local_dir=ROOT / 'data/raw')
    metadata = Path(download('metadata.jsonl'))
    sha = hashlib.sha256(metadata.read_bytes()).hexdigest()
    if sha != '77401dbd6f7e75fde017cc3f6efec24cb144e52abbe0cec2b52164451c4dec53':
        raise SystemExit('原始元数据校验失败')
    print(f'原始元数据已校验: {sha}')
    if args.metadata_only:
        return
    ids = json.loads((ROOT / 'data/dish_ids.json').read_text())
    def fetch(iid):
        target = ROOT / 'data/images' / f'{iid}.jpg'
        if target.exists():
            with Image.open(target) as image:
                image.verify()
            return iid
        source = download(f'test/{iid}.png')
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.tmp')
        with Image.open(source) as image:
            image.convert('RGB').save(temporary, format='JPEG')
        temporary.replace(target)
        return iid
    with ThreadPoolExecutor(max_workers=4) as pool:
        for n, iid in enumerate(pool.map(fetch, ids), 1):
            print(f'{n}/{len(ids)} {iid}', flush=True)


if __name__ == '__main__':
    main()
