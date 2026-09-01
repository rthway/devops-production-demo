"""Business rules for users.

Imports no web framework on purpose: these rules are testable by constructing
the service with a session, which keeps the API layer a thin adapter.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate, UserUpdate

log = get_logger(__name__)


class UserService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = UserRepository(session)

    def get(self, user_id: str) -> User:
        user = self._repo.get(user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} does not exist.", user_id=user_id)
        return user

    def list(self, *, limit: int, offset: int, active_only: bool = False) -> tuple[list[User], int]:
        return (
            self._repo.list(limit=limit, offset=offset, active_only=active_only),
            self._repo.count(active_only=active_only),
        )

    def create(self, payload: UserCreate) -> User:
        # Checked first for a clean 409 message, but the unique index below is
        # the real guarantee -- two concurrent requests both pass this check.
        if self._repo.get_by_email(payload.email) is not None:
            raise ConflictError(f"A user with email {payload.email} already exists.")

        user = User(
            email=payload.email,
            full_name=payload.full_name,
            is_active=payload.is_active,
        )
        try:
            self._repo.add(user)
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError(f"A user with email {payload.email} already exists.") from exc

        log.info("user_created", user_id=user.id)
        return user

    def update(self, user_id: str, payload: UserUpdate) -> User:
        user = self.get(user_id)
        data = payload.model_dump(exclude_unset=True)
        for field, value in data.items():
            setattr(user, field, value)
        self._session.flush()
        log.info("user_updated", user_id=user.id, fields=sorted(data))
        return user

    def delete(self, user_id: str) -> None:
        user = self.get(user_id)
        self._repo.delete(user)
        log.info("user_deleted", user_id=user_id)
