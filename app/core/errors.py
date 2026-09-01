"""Domain errors and the handlers that translate them into HTTP.

The application layer raises these; only this module knows about status codes.
That is what keeps `app/services` free of FastAPI imports and therefore unit
testable without spinning up an app.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.logging import get_logger, request_id_ctx

# Starlette renamed this constant; support both so the service builds against
# the pinned range in pyproject rather than one exact Starlette version.
HTTP_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)

log = get_logger(__name__)


class AppError(Exception):
    """Base class for every expected failure."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "internal_error"
    message: str = "An unexpected error occurred."

    def __init__(self, message: str | None = None, **context: Any) -> None:
        self.message = message or self.message
        self.context = context
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"
    message = "Resource not found."


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"
    message = "Resource already exists."


class ValidationError(AppError):
    status_code = HTTP_422
    code = "validation_error"
    message = "Request was not valid."


class ServiceUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "service_unavailable"
    message = "A dependency is unavailable."


def _envelope(code: str, message: str, **extra: Any) -> dict[str, Any]:
    """One error shape for the whole API, so clients parse one thing."""
    body: dict[str, Any] = {
        "error": {"code": code, "message": message, "request_id": request_id_ctx.get()}
    }
    if extra:
        body["error"].update(extra)
    return body


def _safe_validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    """Reduce pydantic errors to JSON-safe, non-leaking fields.

    `exc.errors()` embeds the original exception object under `ctx` whenever a
    custom validator raises, which is (a) not JSON serialisable -- it turns a
    422 into a 500 -- and (b) a way for internal detail to reach the client.
    Only loc/msg/type are echoed, and `input` is dropped so a rejected payload
    is never mirrored back.
    """
    details: list[dict[str, Any]] = []
    for err in exc.errors():
        details.append(
            {
                "loc": [str(part) for part in err.get("loc", ())],
                "msg": str(err.get("msg", "invalid value")),
                "type": str(err.get("type", "value_error")),
            }
        )
    return details


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError) -> JSONResponse:
        log.warning("app_error", code=exc.code, message=exc.message, **exc.context)
        return JSONResponse(status_code=exc.status_code, content=_envelope(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def _validation(_r: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=HTTP_422,
            content=_envelope(
                "validation_error",
                "Request body or parameters failed validation.",
                details=_safe_validation_details(exc),
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        # Log the detail, return none of it: stack traces and driver messages
        # are exactly the kind of thing that leaks schema and topology.
        log.exception("unhandled_exception", error=str(exc))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope("internal_error", "An unexpected error occurred."),
        )
