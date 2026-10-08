"""Every API endpoint checks who is calling (docs/ARCHITECTURE.md section
6). Walks every endpoint the app publishes (its OpenAPI listing), so a
new endpoint that forgets its auth dependency fails here."""

import re

from fastapi.testclient import TestClient

from api.app.main import app

client = TestClient(app)
PUBLIC = {"/health", "/health/harness", "/config"}


def test_every_route_refuses_a_request_without_login(fake_db):
    endpoints = [
        (method.upper(), path)
        for path, methods in app.openapi()["paths"].items()
        if path not in PUBLIC
        for method in methods
    ]
    assert len(endpoints) > 30  # sanity: the walk really found the app's endpoints
    for method, path in endpoints:
        response = client.request(method, re.sub(r"{[^}]+}", "x", path), json={})
        assert response.status_code == 401, f"{method} {path} answered {response.status_code} without login"
