"""Prometheus instrumentation.

Deliberately hand-rolled rather than pulled from a library so the cardinality
decisions are visible and reviewable: labels are (method, path_template,
status) -- never the raw path, because `/api/v1/users/<uuid>` as a label value
would create one time series per user and eventually take Prometheus down.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests.",
    ["method", "path", "status"],
)
REQUEST_ERRORS = Counter(
    "http_request_errors_total",
    "HTTP requests that returned 5xx.",
    ["method", "path"],
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "path"],
    # Buckets chosen around the SLO (p95 < 250ms) rather than the library
    # default, so the histogram has resolution where the alert threshold is.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
IN_PROGRESS = Gauge("http_requests_in_progress", "In-flight HTTP requests.")
APP_INFO = Gauge("app_info", "Build and environment info.", ["version", "environment"])
DB_UP = Gauge("app_database_up", "1 when the database answered its last probe, else 0.")


UNMATCHED = "__unmatched__"


def _path_template(request: Request) -> str:
    """Resolve the route template so path parameters never become label values.

    Only valid AFTER the request has been routed: Starlette populates
    ``scope["route"]`` and ``scope["path_params"]`` during routing, which
    happens downstream of this middleware. Reading them before ``call_next``
    yields nothing and every series ends up labelled ``__unmatched__``.

    The template is rebuilt from the concrete path rather than read off
    ``route.path``, because a router included under a prefix reports only its
    own relative path -- ``/users/{user_id}`` instead of
    ``/api/v1/users/{user_id}``. Substituting segment by segment keeps the
    prefix and cannot accidentally rewrite a matching literal elsewhere in
    the path.
    """
    if request.scope.get("route") is None:
        # A 404, or a request that never reached the router. Bucketed under a
        # single label so scanners probing random URLs cannot inflate
        # cardinality without bound.
        return UNMATCHED

    params = request.scope.get("path_params") or {}
    path = request.url.path
    if not params:
        return path

    replacements = {str(value): "{" + name + "}" for name, value in params.items()}
    return "/".join(replacements.get(segment, segment) for segment in path.split("/"))


class MetricsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Scraping must not measure itself, or the series grows on every scrape
        # even when the service is serving no real traffic.
        if request.url.path == "/metrics":
            return await call_next(request)

        method = request.method
        started = time.perf_counter()
        IN_PROGRESS.inc()
        try:
            response = await call_next(request)
        except Exception:
            # An exception escaping here still becomes a 500 downstream, so it
            # must be counted as one or the error rate under-reports exactly
            # when it matters most.
            path = _path_template(request)
            REQUEST_COUNT.labels(method, path, "500").inc()
            REQUEST_ERRORS.labels(method, path).inc()
            REQUEST_LATENCY.labels(method, path).observe(time.perf_counter() - started)
            raise
        finally:
            IN_PROGRESS.dec()

        # Resolved after call_next: see _path_template.
        path = _path_template(request)
        status_code = response.status_code
        REQUEST_LATENCY.labels(method, path).observe(time.perf_counter() - started)
        REQUEST_COUNT.labels(method, path, str(status_code)).inc()
        if status_code >= 500:
            REQUEST_ERRORS.labels(method, path).inc()
        return response


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
