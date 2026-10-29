from datetime import datetime, timezone
import uuid

from sqlalchemy import JSON, ForeignKey, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    token_version: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Comparison(Base):
    __tablename__ = 'comparisons'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    filename: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(80))
    note: Mapped[str] = mapped_column(Text, default='')
    mode: Mapped[str] = mapped_column(String(16), default='live')
    sample_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    image_sha256: Mapped[str] = mapped_column(String(64))
    input_path: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default='queued', index=True)
    a_status: Mapped[str] = mapped_column(String(16), default='pending')
    b_status: Mapped[str] = mapped_column(String(16), default='pending')
    a_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    b_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    a_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    b_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    a_attempts: Mapped[int] = mapped_column(default=0)
    b_attempts: Mapped[int] = mapped_column(default=0)
    generation: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)


def database(settings):
    settings.prepare()
    engine = create_engine(settings.database_url, connect_args={'check_same_thread': False, 'timeout': 30})

    @event.listens_for(engine, 'connect')
    def sqlite_setup(connection, _):
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=30000')

    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)
