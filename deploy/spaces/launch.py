"""Run the existing application services in one Hugging Face Docker Space."""
import os
from pathlib import Path
import signal
import subprocess
import time
from web.config import Settings
from web.database import database
from web.queue import connection


def main():
    settings = Settings()
    engine, _ = database(settings)
    engine.dispose()
    redis_dir = settings.state_dir / 'redis'
    redis_dir.mkdir(parents=True, exist_ok=True)
    children = []
    def shutdown(*_):
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                child.kill()
    def handle_stop(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)
    try:
        children.append(subprocess.Popen(['redis-server', '--bind', '127.0.0.1', '--port', '6379',
            '--dir', str(redis_dir), '--appendonly', 'yes', '--appendfsync', 'everysec'], stdin=subprocess.DEVNULL))
        for _ in range(60):
            try:
                connection(settings).ping()
                break
            except Exception:
                if children[0].poll() is not None:
                    raise RuntimeError('Redis failed to start')
                time.sleep(.5)
        else:
            raise RuntimeError('Redis startup timed out')
        commands = [
            ['uvicorn', 'web.api:app', '--host', '127.0.0.1', '--port', '8000', '--proxy-headers', '--forwarded-allow-ips', '127.0.0.1'],
            ['python', '-m', 'web.worker'],
            ['nginx', '-c', '/app/deploy/spaces/nginx.conf', '-g', 'daemon off;'],
        ]
        for command in commands:
            children.append(subprocess.Popen(command, stdin=subprocess.DEVNULL))
        while True:
            if any(child.poll() is not None for child in children):
                raise RuntimeError('An application service stopped; restarting the Space is required')
            time.sleep(1)
    finally:
        shutdown()


if __name__ == '__main__':
    main()
