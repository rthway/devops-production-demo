from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class UserBase(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _normalise_email(cls, v: str) -> str:
        # Normalised at the edge so the unique index does the right thing:
        # "A@b.com" and "a@b.com" must not both be insertable.
        return v.strip().lower()

    @field_validator("full_name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("full_name must not be blank")
        return stripped


class UserCreate(UserBase):
    is_active: bool = True


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserPage(BaseModel):
    """Explicit envelope: clients need the total to render pagination, and
    adding it later would be a breaking change to a bare list response."""

    items: list[UserRead]
    total: int
    limit: int
    offset: int
