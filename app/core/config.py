"""Application configuration.

Every knob comes from the environment. Nothing is read from a file that ships
in the image, and nothing has a production-safe default that could silently be
wrong -- `environment` defaults to "local" so a misconfigured deploy looks
obviously unconfigured rather than pretending to be production.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "dev", "staging", "prod"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="APP_",
        extra="ignore",
    )

    # --- identity -----------------------------------------------------------
    project_name: str = "devops-production-demo"
    version: str = "1.0.0"
    environment: Environment = "local"
    debug: bool = False

    # --- http ---------------------------------------------------------------
    api_v1_prefix: str = "/api/v1"
    # nosec B104 / noqa S104: a container must bind all interfaces to be
    # reachable from the pod network. Exposure is controlled by the Service,
    # NetworkPolicy and Ingress, not by the listen address.
    host: str = "0.0.0.0"  # noqa: S104  # nosec B104
    port: int = 8000

    # --- database -----------------------------------------------------------
    # Kept as a single DSN rather than five separate fields: it is what
    # SQLAlchemy, Alembic and every managed Postgres service already speak,
    # so there is exactly one secret to mount instead of five.
    database_url: str = "postgresql+psycopg://app:app@localhost:5432/app"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_pre_ping: bool = True
    db_echo: bool = False

    # --- observability ------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = True
    metrics_enabled: bool = True

    # --- limits -------------------------------------------------------------
    max_page_size: int = Field(default=100, ge=1, le=1000)

    @field_validator("log_level")
    @classmethod
    def _upper(cls, v: str) -> str:
        valid = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"log_level must be one of {sorted(valid)}")
        return upper

    @field_validator("database_url")
    @classmethod
    def _validate_dsn(cls, v: str) -> str:
        # SQLite is permitted so the unit suite can run with no services at
        # all; anything else must be a DSN Postgres would accept.
        if v.startswith("sqlite"):
            return v
        PostgresDsn(v)
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"


@lru_cache
def get_settings() -> Settings:
    """Cached so config is parsed and validated exactly once per process."""
    return Settings()
