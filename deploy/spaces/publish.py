"""Prepare a reviewed Docker Space, then publish using HF_TOKEN from secure settings."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def prepare(destination):
    destination = Path(destination).resolve()
    if destination.is_relative_to(ROOT):
        raise ValueError('Upload staging directory must be outside the repository')
    destination.mkdir(parents=True, exist_ok=True)
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    for name in filter(None, paths):
        relative = Path(name)
        if relative.name in {'.env', 'session.key'} or relative.parts[0] in {'var', 'models'}:
            raise ValueError('Private file found in tracked source')
        source = ROOT / relative
        if source.is_file():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    dockerfile = (ROOT / 'Dockerfile').read_text()
    dockerfile += '''
USER root
RUN apt-get update && apt-get install -y --no-install-recommends redis-server nginx \\
    && rm -rf /var/lib/apt/lists/*
USER app
RUN python -m web.prepare_models
ENV CANTEEN_STATE_DIR=/tmp/canteen/state REDIS_URL=redis://127.0.0.1:6379/0 COOKIE_SECURE=1
EXPOSE 7860
CMD ["python", "-m", "deploy.spaces.launch"]
'''
    (destination / 'Dockerfile').write_text(dockerfile)
    readme = (ROOT / 'README.md').read_text()
    (destination / 'README.md').write_text('---\ntitle: Canteen Lab\nsdk: docker\napp_port: 7860\n---\n\n' + readme)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--space-name', default='canteen-kcal')
    parser.add_argument('--prepare-only', type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{1,60}', args.space_name):
        parser.error('Invalid Space name')
    if args.prepare_only:
        print('Prepared:', prepare(args.prepare_only))
        return
    token = os.getenv('HF_TOKEN')
    if not token:
        parser.error('HF_TOKEN is missing. Add a Hugging Face Write token through secure environment settings, not chat.')
    from huggingface_hub import HfApi
    api = HfApi(token=token)
    owner = api.whoami()['name']
    repo_id = f'{owner}/{args.space_name}'
    # Never overwrite an existing unrelated Space.
    api.create_repo(repo_id=repo_id, repo_type='space', space_sdk='docker', private=False, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='canteen-space-') as directory:
        api.upload_folder(repo_id=repo_id, repo_type='space', folder_path=prepare(directory),
                          commit_message='Deploy Canteen Lab Docker application')
    print('Space created:', f'https://huggingface.co/spaces/{repo_id}')
    print('Build is pending. Verify its public application URL before sharing it with customers.')


if __name__ == '__main__':
    main()
