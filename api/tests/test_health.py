from fastapi.testclient import TestClient

from api.app.main import app

client = TestClient(app)


def test_health_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_harness_reports_502_when_unreachable():
    # No harness running in this test, and no network access in CI -
    # this just proves the error path is wired, not a real integration test.
    response = client.get("/health/harness")
    assert response.status_code == 502
