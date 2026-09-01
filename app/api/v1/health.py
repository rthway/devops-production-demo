"""Health, readiness and liveness.

Three endpoints rather than one because Kubernetes asks three different
questions:

  /health   -- is the process up at all (used by humans and load balancers)
  /health/live  -- should the kubelet restart me? Must NOT touch the database:
                   a Postgres outage would otherwise restart every pod in a
                   crash loop and turn a recoverable dependency failure into
                   a full outage.
  /health/ready -- should I receive traffic? This one DOES check the database,
                   so a pod that cannot serve is pulled from the Service
                   endpoints without being killed.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.metrics import DB_UP
from app.db.session import check_database

router = APIRouter(tags=["health"])


@router.get("/health", summary="Service health")
def health() -> dict[str, Any]:
    s = get_settings()
    return {
        "status": "ok",
        "service": s.project_name,
        "version": s.version,
        "environment": s.environment,
    }


@router.get("/health/live", summary="Liveness probe")
def live() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/health/ready", summary="Readiness probe")
def ready() -> JSONResponse:
    db_ok = check_database()
    DB_UP.set(1 if db_ok else 0)
    body = {"status": "ready" if db_ok else "not_ready", "checks": {"database": db_ok}}
    code = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=code, content=body)
