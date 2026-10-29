from dataclasses import dataclass, field
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    state_dir: Path = field(default_factory=lambda: Path(os.getenv('CANTEEN_STATE_DIR', ROOT / 'var')).resolve())
    model_dir: Path = field(default_factory=lambda: Path(os.getenv('CANTEEN_MODEL_DIR', ROOT / 'models')).resolve())
    redis_url: str = field(default_factory=lambda: os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0'))
    queue_name: str = 'comparisons'
    task_timeout: int = 900
    max_upload_bytes: int = 10 * 1024 * 1024
    max_image_pixels: int = 16_000_000
    cookie_secure: bool = field(default_factory=lambda: os.getenv('COOKIE_SECURE', '0') == '1')
    token_hours: int = 12

    @property
    def database_url(self):
        return f'sqlite:///{self.state_dir / "canteen.db"}'

    def prepare(self):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / 'jobs').mkdir(exist_ok=True)

    def secret(self):
        configured = os.getenv('APP_SECRET_KEY')
        if configured:
            if len(configured) < 32:
                raise ValueError('APP_SECRET_KEY 至少需要 32 个字符')
            return configured
        # API 重启后 cookie 仍有效；多个进程共享同一持久卷。
        self.prepare()
        path = self.state_dir / 'session.key'
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, 'w') as stream:
                stream.write(secrets.token_urlsafe(48))
        value = path.read_text().strip()
        if len(value) < 32:
            raise ValueError('持久化会话密钥无效')
        return value
