from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.schemas.user import UserCreate, UserPage, UserRead, UserUpdate
from app.services.user import UserService

router = APIRouter(prefix="/users", tags=["users"])

DbSession = Annotated[Session, Depends(get_db)]
Config = Annotated[Settings, Depends(get_settings)]


def get_user_service(session: DbSession) -> UserService:
    return UserService(session)


ServiceDep = Annotated[UserService, Depends(get_user_service)]


@router.get("", response_model=UserPage, summary="List users")
def list_users(
    service: ServiceDep,
    settings: Config,
    limit: Annotated[int, Query(ge=1, le=1000)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    active_only: bool = False,
) -> UserPage:
    # Clamped server-side: an unbounded LIMIT is a trivial way for a client to
    # pull the whole table and exhaust memory.
    limit = min(limit, settings.max_page_size)
    users, total = service.list(limit=limit, offset=offset, active_only=active_only)
    return UserPage(
        items=[UserRead.model_validate(u) for u in users],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user",
)
def create_user(payload: UserCreate, service: ServiceDep) -> UserRead:
    return UserRead.model_validate(service.create(payload))


@router.get("/{user_id}", response_model=UserRead, summary="Get a user by id")
def get_user(user_id: str, service: ServiceDep) -> UserRead:
    return UserRead.model_validate(service.get(user_id))


@router.patch("/{user_id}", response_model=UserRead, summary="Update a user")
def update_user(user_id: str, payload: UserUpdate, service: ServiceDep) -> UserRead:
    return UserRead.model_validate(service.update(user_id, payload))


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user",
)
def delete_user(user_id: str, service: ServiceDep) -> Response:
    service.delete(user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
