"""Health-Endpoint-Tests (Sprint 1)."""

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert body["environment"] in {"development", "test", "production"}


def test_openapi_available(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Heizungssteuerung Hotel Sonnblick"
