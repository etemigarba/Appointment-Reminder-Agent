from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok(tmp_path):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'health.db'}")
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
