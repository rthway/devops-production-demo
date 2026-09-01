from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _create(client: TestClient, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "email": "user@example.org",
        "full_name": "Test User",
        "is_active": True,
    }
    payload.update(overrides)
    r = client.post("/api/v1/users", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


class TestCreate:
    def test_creates_and_returns_the_resource(
        self, client: TestClient, sample_user_payload: dict[str, object]
    ) -> None:
        r = client.post("/api/v1/users", json=sample_user_payload)
        assert r.status_code == 201
        body = r.json()
        assert body["email"] == "asha.sharma@example.org"
        assert body["full_name"] == "Asha Sharma"
        assert body["is_active"] is True
        assert body["id"]
        assert body["created_at"] and body["updated_at"]

    def test_email_is_normalised_to_lowercase(self, client: TestClient) -> None:
        body = _create(client, email="MiXeD.Case@Example.ORG")
        assert body["email"] == "mixed.case@example.org"

    def test_duplicate_email_conflicts_regardless_of_case(self, client: TestClient) -> None:
        _create(client, email="dup@example.org")
        r = client.post(
            "/api/v1/users",
            json={"email": "DUP@example.org", "full_name": "Other"},
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "conflict"

    def test_rejects_an_invalid_email(self, client: TestClient) -> None:
        r = client.post("/api/v1/users", json={"email": "not-an-email", "full_name": "X"})
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "validation_error"

    def test_rejects_a_blank_name(self, client: TestClient) -> None:
        r = client.post("/api/v1/users", json={"email": "a@example.org", "full_name": "   "})
        assert r.status_code == 422

    def test_error_envelope_carries_the_request_id(self, client: TestClient) -> None:
        r = client.post("/api/v1/users", json={"email": "bad", "full_name": "X"})
        assert r.json()["error"]["request_id"]


class TestRead:
    def test_get_by_id(self, client: TestClient) -> None:
        created = _create(client)
        r = client.get(f"/api/v1/users/{created['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == created["id"]

    def test_unknown_id_is_404_with_the_shared_envelope(self, client: TestClient) -> None:
        r = client.get("/api/v1/users/00000000-0000-0000-0000-000000000000")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"

    def test_list_is_empty_before_anything_exists(self, client: TestClient) -> None:
        r = client.get("/api/v1/users")
        assert r.status_code == 200
        assert r.json() == {"items": [], "total": 0, "limit": 50, "offset": 0}

    def test_list_reports_total_independent_of_the_page(self, client: TestClient) -> None:
        for i in range(5):
            _create(client, email=f"u{i}@example.org")
        r = client.get("/api/v1/users", params={"limit": 2, "offset": 0})
        body = r.json()
        assert len(body["items"]) == 2
        assert body["total"] == 5

    def test_pagination_does_not_repeat_or_skip_records(self, client: TestClient) -> None:
        for i in range(7):
            _create(client, email=f"p{i}@example.org")
        seen: list[str] = []
        for offset in (0, 3, 6):
            page = client.get("/api/v1/users", params={"limit": 3, "offset": offset}).json()
            seen.extend(item["id"] for item in page["items"])
        assert len(seen) == 7
        assert len(set(seen)) == 7

    def test_limit_is_clamped_to_the_configured_maximum(self, client: TestClient) -> None:
        r = client.get("/api/v1/users", params={"limit": 1000})
        # Requesting 1000 must not return a 1000-row page: max_page_size wins.
        assert r.json()["limit"] == 100

    def test_limit_above_the_hard_bound_is_rejected(self, client: TestClient) -> None:
        assert client.get("/api/v1/users", params={"limit": 5000}).status_code == 422

    def test_negative_offset_is_rejected(self, client: TestClient) -> None:
        assert client.get("/api/v1/users", params={"offset": -1}).status_code == 422

    def test_active_only_filters_out_deactivated_users(self, client: TestClient) -> None:
        _create(client, email="active@example.org", is_active=True)
        _create(client, email="inactive@example.org", is_active=False)
        body = client.get("/api/v1/users", params={"active_only": True}).json()
        assert body["total"] == 1
        assert body["items"][0]["email"] == "active@example.org"


class TestUpdate:
    def test_partial_update_leaves_untouched_fields_alone(self, client: TestClient) -> None:
        created = _create(client, email="keep@example.org", full_name="Original Name")
        r = client.patch(f"/api/v1/users/{created['id']}", json={"is_active": False})
        assert r.status_code == 200
        body = r.json()
        assert body["is_active"] is False
        assert body["full_name"] == "Original Name"
        assert body["email"] == "keep@example.org"

    def test_updating_an_unknown_user_is_404(self, client: TestClient) -> None:
        r = client.patch("/api/v1/users/does-not-exist", json={"full_name": "X"})
        assert r.status_code == 404


class TestDelete:
    def test_delete_returns_204_and_the_user_is_gone(self, client: TestClient) -> None:
        created = _create(client)
        assert client.delete(f"/api/v1/users/{created['id']}").status_code == 204
        assert client.get(f"/api/v1/users/{created['id']}").status_code == 404

    def test_deleting_twice_is_404_the_second_time(self, client: TestClient) -> None:
        created = _create(client)
        client.delete(f"/api/v1/users/{created['id']}")
        assert client.delete(f"/api/v1/users/{created['id']}").status_code == 404


def test_validation_details_are_json_safe_and_do_not_echo_the_input(
    client: TestClient,
) -> None:
    """Regression: a custom validator that raises ValueError used to put the
    exception object into the response body, which failed to serialise and
    turned a 422 into a 500."""
    r = client.post("/api/v1/users", json={"email": "a@example.org", "full_name": "  "})
    assert r.status_code == 422
    details = r.json()["error"]["details"]
    assert details and all({"loc", "msg", "type"} == set(d) for d in details)
