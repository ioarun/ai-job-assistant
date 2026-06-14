"""Synchronous SQLAlchemy session for Phase C tools.

The FastAPI app uses the async `sqlite+aiosqlite` URL, but the Phase C tools
(Adzuna client, gap analyzer, ...) are plain sync functions that LangGraph
nodes call directly, so they get a sync engine derived from the same DB file.
Both point at the same `./data/app.db`; only the driver differs.
"""
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.db.models import Base


def _sync_url() -> str:
    """Derive the sync SQLite URL from the configured async one."""
    return get_settings().database_url.replace("+aiosqlite", "")


# `check_same_thread=False` keeps SQLite usable across the threads FastAPI /
# LangGraph may invoke tools from. One engine per process.
_engine = create_engine(_sync_url(), connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    """Create any missing tables. Idempotent; safe to call at startup."""
    Base.metadata.create_all(bind=_engine)


@contextmanager
def get_sync_session() -> Iterator[Session]:
    """Yield a sync session, committing on success and rolling back on error."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
