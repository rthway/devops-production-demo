from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_reports_service_identity(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "devops-production-demo"
    assert body["version"]
    assert body["environment"] == "local"


def test_liveness_does_not_depend_on_the_database(client: TestClient, monkeypatch) -> None:
    """A database outage must not make the kubelet restart the pod.

    This is the single most important health-check property in the service:
    if liveness touched the database, a Postgres failover would crash-loop
    every replica at once.
    """
    monkeypatch.setattr("app.db.session.check_database", lambda: False)
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "alive"}


def test_readiness_is_ok_when_the_database_answers(client: TestClient) -> None:
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "checks": {"database": True}}


def test_readiness_fails_closed_when_the_database_is_down(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr("app.api.v1.health.check_database", lambda: False)
    r = client.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["database"] is False


def test_metrics_endpoint_exposes_prometheus_text_format(client: TestClient) -> None:
    client.get("/health")
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert "http_requests_total" in r.text
    assert "http_request_duration_seconds" in r.text


def test_request_id_is_returned_and_echoed(client: TestClient) -> None:
    generated = client.get("/health").headers["x-request-id"]
    assert generated

    supplied = "trace-abc-123"
    r = client.get("/health", headers={"x-request-id": supplied})
    # An upstream id must survive the hop, not be replaced.
    assert r.headers["x-request-id"] == supplied


def test_root_endpoint(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["service"] == "devops-production-demo"


def _metric_paths(metrics_text: str) -> set[str]:
    """Pull every distinct `path="..."` label out of the exposition text."""
    import re

    return set(re.findall(r'http_requests_total\{[^}]*path="([^"]+)"', metrics_text))


def test_metrics_label_uses_the_route_template_not_the_concrete_path(
    client: TestClient,
) -> None:
    """Regression: the label must be `/api/v1/users/{user_id}`.

    The first implementation resolved the template before `call_next`, but
    Starlette only populates `scope["route"]` during routing -- so every
    series was labelled `__unmatched__`. Metrics were being collected and
    looked healthy; they were simply useless, which is the worst failure mode
    for instrumentation.
    """
    created = client.post(
        "/api/v1/users", json={"email": "metric@example.org", "full_name": "Metric"}
    ).json()
    user_id = created["id"]
    client.get(f"/api/v1/users/{user_id}")

    paths = _metric_paths(client.get("/metrics").text)

    assert "/api/v1/users/{user_id}" in paths
    assert "/api/v1/users" in paths
    # The uuid itself must never appear as a label value: one series per user
    # is how a Prometheus instance is taken down.
    assert user_id not in " ".join(paths)
    assert "__unmatched__" not in paths


def test_unrouted_paths_collapse_into_a_single_label(client: TestClient) -> None:
    """A scanner probing random URLs must not be able to create unbounded
    series, so every 404 shares one bucket."""
    for suffix in ("alpha", "beta", "gamma"):
        client.get(f"/definitely-not-a-route-{suffix}")

    paths = _metric_paths(client.get("/metrics").text)
    assert "__unmatched__" in paths
    assert not any("definitely-not-a-route" in p for p in paths)


def test_prefixed_route_keeps_its_full_path_label(client: TestClient) -> None:
    """A router included under /api/v1 reports only its relative path, so the
    template has to be rebuilt from the concrete path to keep the prefix."""
    client.get("/api/v1/users")
    assert "/api/v1/users" in _metric_paths(client.get("/metrics").text)
