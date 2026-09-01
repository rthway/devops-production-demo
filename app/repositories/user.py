"""Data access for users.

The repository owns SQL and nothing else -- no HTTP, no business rules. That
boundary is what makes it swappable (the service layer is tested against a
SQLite-backed repository and behaves identically).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: str) -> User | None:
        return self._session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.strip().lower())
        return self._session.execute(stmt).scalar_one_or_none()

    def list(self, *, limit: int, offset: int, active_only: bool = False) -> list[User]:
        stmt = select(User).order_by(User.created_at.desc(), User.id)
        if active_only:
            stmt = stmt.where(User.is_active.is_(True))
        stmt = stmt.limit(limit).offset(offset)
        return list(self._session.execute(stmt).scalars().all())

    def count(self, *, active_only: bool = False) -> int:
        stmt = select(func.count()).select_from(User)
        if active_only:
            stmt = stmt.where(User.is_active.is_(True))
        return int(self._session.execute(stmt).scalar_one())

    def add(self, user: User) -> User:
        self._session.add(user)
        # Flush, not commit: the request-scoped dependency owns the
        # transaction boundary, so a later failure in the same request still
        # rolls this back.
        self._session.flush()
        return user

    def delete(self, user: User) -> None:
        self._session.delete(user)
        self._session.flush()
