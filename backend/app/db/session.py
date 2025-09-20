from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ..core.config import get_settings

_settings = get_settings()
DATABASE_URL = _settings.database_url or "sqlite:///./greenbucks.db"
if isinstance(DATABASE_URL, str) and DATABASE_URL.strip() == "":
    DATABASE_URL = "sqlite:///./greenbucks.db"

# For SQLite we need check_same_thread=False for multi-threaded uvicorn
connect_args = {"check_same_thread": False} if DATABASE_URL and DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
