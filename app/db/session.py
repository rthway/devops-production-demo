"""Engine and session lifecycle.

The engine is created once per process and held module-level; a new engine per
request would open a new TCP connection per request and make the pool
pointless. `get_db` is the FastAPI dependency and is the only place a session
is committed or rolled back.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _build_engine() -> Engine:
    s = get_settings()
    kwargs: dict[str, object] = {"echo": s.db_echo, "future": True}
    if s.database_url.startswith("sqlite"):
        # SQLite has no server-side pool to size, and the test suite shares one
        # in-memory database across threads.
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update(
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            # pre_ping costs one round trip and removes the entire class of
            # "server closed the connection unexpectedly" errors that happen
            # when a pooled connection outlives a Postgres restart or a
            # Kubernetes rollout of pgbouncer.
            pool_pre_ping=s.db_pool_pre_ping,
            pool_recycle=1800,
        )
    return create_engine(s.database_url, **kwargs)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(
            bind=get_engine(), autocommit=False, autoflush=False, expire_on_commit=False
        )
    return _SessionFactory


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request, committed on success."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Same contract as `get_db`, for use outside the request cycle (CLI, jobs)."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database() -> bool:
    """Cheapest possible liveness probe against the database."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        log.warning("database_probe_failed", error=str(exc))
        return False


def reset_engine() -> None:
    """Drop the cached engine. Used by tests after overriding settings."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
