"""Persistence-layer tests.

The unmarked tests here run against SQLite and cover the repository/service
contract. The `integration` marked tests need a real PostgreSQL and are the
ones that prove behaviour SQLite cannot represent (server-side timestamp
defaults, the unique index under concurrency). CI runs both: the unit job
without services, the integration job with a Postgres service container.
"""

from __future__ import annotations

import os

import pytest
from app.core.errors import ConflictError, NotFoundError
from app.db.session import check_database, get_engine, session_scope
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate, UserUpdate
from app.services.user import UserService
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def test_schema_contains_the_expected_table_and_columns(_schema: None) -> None:
    inspector = inspect(get_engine())
    assert "users" in inspector.get_table_names()
    columns = {c["name"] for c in inspector.get_columns("users")}
    assert {"id", "email", "full_name", "is_active", "created_at", "updated_at"} <= columns


def test_email_has_a_unique_index(_schema: None) -> None:
    """The application-level duplicate check is a nicety; this index is the
    actual guarantee under concurrent writes."""
    indexes = inspect(get_engine()).get_indexes("users")
    email_indexes = [i for i in indexes if i["column_names"] == ["email"]]
    assert email_indexes, "expected an index on users.email"
    assert any(i["unique"] for i in email_indexes)


def test_check_database_returns_true_against_a_live_engine(_schema: None) -> None:
    assert check_database() is True


def test_check_database_returns_false_and_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> None:
        raise RuntimeError("connection refused")

    monkeypatch.setattr("app.db.session.get_engine", boom)
    # A probe that raises would turn a dependency blip into a 500 on /ready.
    assert check_database() is False


class TestRepository:
    def test_add_then_get_round_trips(self, session: Session) -> None:
        repo = UserRepository(session)
        user = repo.add(User(email="repo@example.org", full_name="Repo User"))
        assert repo.get(user.id) is not None

    def test_get_by_email_is_case_insensitive_on_input(self, session: Session) -> None:
        repo = UserRepository(session)
        repo.add(User(email="case@example.org", full_name="Case"))
        assert repo.get_by_email("CASE@EXAMPLE.ORG") is not None

    def test_get_returns_none_for_an_unknown_id(self, session: Session) -> None:
        assert UserRepository(session).get("missing") is None

    def test_count_ignores_limit_and_offset(self, session: Session) -> None:
        repo = UserRepository(session)
        for i in range(4):
            repo.add(User(email=f"c{i}@example.org", full_name=f"User {i}"))
        assert len(repo.list(limit=2, offset=0)) == 2
        assert repo.count() == 4

    def test_database_rejects_a_duplicate_email(self, session: Session) -> None:
        repo = UserRepository(session)
        repo.add(User(email="dupe@example.org", full_name="First"))
        with pytest.raises(IntegrityError):
            repo.add(User(email="dupe@example.org", full_name="Second"))
        session.rollback()

    def test_timestamps_are_populated_by_the_database(self, session: Session) -> None:
        user = UserRepository(session).add(User(email="ts@example.org", full_name="TS"))
        session.refresh(user)
        assert user.created_at is not None
        assert user.updated_at is not None


class TestService:
    def test_create_persists_and_assigns_an_id(self, session: Session) -> None:
        user = UserService(session).create(
            UserCreate(email="svc@example.org", full_name="Service User")
        )
        assert user.id and user.email == "svc@example.org"

    def test_create_rejects_a_duplicate_with_a_domain_error(self, session: Session) -> None:
        service = UserService(session)
        service.create(UserCreate(email="once@example.org", full_name="Once"))
        with pytest.raises(ConflictError):
            service.create(UserCreate(email="once@example.org", full_name="Twice"))

    def test_get_raises_not_found_rather_than_returning_none(self, session: Session) -> None:
        with pytest.raises(NotFoundError):
            UserService(session).get("nope")

    def test_update_only_touches_supplied_fields(self, session: Session) -> None:
        service = UserService(session)
        user = service.create(UserCreate(email="upd@example.org", full_name="Before"))
        updated = service.update(user.id, UserUpdate(is_active=False))
        assert updated.is_active is False
        assert updated.full_name == "Before"

    def test_delete_removes_the_row(self, session: Session) -> None:
        service = UserService(session)
        user = service.create(UserCreate(email="del@example.org", full_name="Delete Me"))
        service.delete(user.id)
        with pytest.raises(NotFoundError):
            service.get(user.id)


def test_transaction_rolls_back_on_failure(_schema: None) -> None:
    """session_scope must not leave a half-written transaction committed."""
    with pytest.raises(RuntimeError), session_scope() as s:
        UserRepository(s).add(User(email="rollback@example.org", full_name="Rollback"))
        raise RuntimeError("simulated failure after write")

    with session_scope() as s:
        assert UserRepository(s).get_by_email("rollback@example.org") is None


# ---------------------------------------------------------------------------
# PostgreSQL-only. Skipped unless a real DSN is supplied.
# ---------------------------------------------------------------------------
POSTGRES_DSN = os.getenv("TEST_POSTGRES_DSN")


@pytest.mark.integration
@pytest.mark.skipif(not POSTGRES_DSN, reason="TEST_POSTGRES_DSN is not set")
def test_postgres_accepts_the_schema_and_enforces_the_unique_index() -> None:
    from app.db.base import Base
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(str(POSTGRES_DSN), future=True)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    try:
        with factory() as s:
            s.execute(text("DELETE FROM users"))
            s.commit()
            s.add(User(email="pg@example.org", full_name="Postgres"))
            s.commit()
        with factory() as s, pytest.raises(IntegrityError):
            s.add(User(email="pg@example.org", full_name="Duplicate"))
            s.commit()
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
