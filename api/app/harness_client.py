"""Calls to the private harness service.

Cloud Run rejects unauthenticated requests to the harness (see
docs/ARCHITECTURE.md section 1: "private, service-account-only invoke").
The standard pattern for one Cloud Run service calling another is a
Google-signed OIDC ID token, audienced to the target URL, fetched from the
metadata server that's only present when actually running on Cloud Run/GCE.

In dev mode (ENVIRONMENT=dev, the default) the harness runs locally without
auth, so no token is fetched.
"""

import requests
from google.auth.transport.requests import Request
from google.oauth2 import id_token

from .config import settings


def _auth_headers() -> dict:
    if settings.is_dev:
        return {}
    token = id_token.fetch_id_token(Request(), settings.harness_url)
    return {"Authorization": f"Bearer {token}"}


def call_harness_health() -> dict:
    response = requests.get(f"{settings.harness_url}/health", headers=_auth_headers(), timeout=5)
    response.raise_for_status()
    return response.json()


def post_to_harness(path: str, body: dict) -> dict:
    response = requests.post(
        f"{settings.harness_url}/{path}", json=body, headers=_auth_headers(), timeout=60
    )
    response.raise_for_status()
    return response.json()
