"""Download the pinned official model assets, or verify an existing model volume."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request

from web.config import ROOT, Settings


def verify(path, expected):
    if not path.is_file() or path.stat().st_size != expected['bytes']:
        return False
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()==expected['sha256']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    settings=Settings()
    manifest=json.loads((ROOT/'web/model-manifest.json').read_text())
    for name,entry in manifest.items():
        target=settings.model_dir/name
        if verify(target,entry):
            print(f'{name}: SHA-256 verified',flush=True)
            continue
        if args.verify_only:
            raise SystemExit(f'{name}: missing or hash mismatch')
        target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_suffix(target.suffix+'.download')
        try:
            print(f'Downloading {name} from the official asset URL',flush=True)
            with urllib.request.urlopen(entry['url'],timeout=120) as source,temporary.open('wb') as output:
                while block:=source.read(1024*1024):
                    output.write(block)
            if not verify(temporary,entry):
                raise SystemExit(f'{name}: hash mismatch; refusing changed model content')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        print(f'{name}: SHA-256 verified',flush=True)


if __name__=='__main__':
    main()
