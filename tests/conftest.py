"""Shared test fixtures.

The unit suite runs against a file-backed SQLite database so the entire API
can be exercised in CI with no service containers at all -- fast feedback is
worth more than dialect fidelity for request/response behaviour. The
Postgres-specific behaviour that SQLite cannot represent is covered separately
by the `integration` marker in test_database.py.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from app.core.config import Settings, get_settings
from app.db import session as db_session
from app.db.base import Base
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


@pytest.fixture(scope="session")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Settings]:
    db_path: Path = tmp_path_factory.mktemp("db") / "test.sqlite3"
    os.environ["APP_DATABASE_URL"] = f"sqlite+pysqlite:///{db_path.as_posix()}"
    os.environ["APP_ENVIRONMENT"] = "local"
    os.environ["APP_LOG_JSON"] = "false"
    os.environ["APP_LOG_LEVEL"] = "WARNING"

    # get_settings is lru_cached, so the override only takes effect once the
    # cache is dropped -- and the engine must be rebuilt against the new DSN.
    get_settings.cache_clear()
    db_session.reset_engine()

    yield get_settings()

    get_settings.cache_clear()
    db_session.reset_engine()


@pytest.fixture(scope="session")
def _schema(settings: Settings) -> Iterator[None]:
    Base.metadata.create_all(bind=db_session.get_engine())
    yield
    Base.metadata.drop_all(bind=db_session.get_engine())


@pytest.fixture(autouse=True)
def clean_tables(_schema: None) -> Iterator[None]:
    """Every test starts from an empty database.

    Truncating after each test rather than recreating the schema keeps the
    suite fast while still giving full isolation and order-independence.
    """
    yield
    with db_session.get_engine().begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture
def client(settings: Settings, _schema: None) -> Iterator[TestClient]:
    with TestClient(create_app(settings), raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def session(_schema: None) -> Iterator[Session]:
    with db_session.session_scope() as s:
        yield s


@pytest.fixture
def sample_user_payload() -> dict[str, object]:
    return {"email": "asha.sharma@example.org", "full_name": "Asha Sharma", "is_active": True}
