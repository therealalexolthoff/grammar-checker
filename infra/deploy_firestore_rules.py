"""Deploys infra/firestore.rules (deny all client access) to the project.

Usage: GOOGLE_CLOUD_PROJECT=<project id> python infra/deploy_firestore_rules.py

Uses your gcloud sign-in (a short-lived token from `gcloud auth
print-access-token`). Safe to re-run: each run
uploads the rules as a new ruleset and points the Firestore release at it.
"""

import os
import subprocess
from pathlib import Path

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

PROJECT = os.environ["GOOGLE_CLOUD_PROJECT"]
API = f"https://firebaserules.googleapis.com/v1/projects/{PROJECT}"
RELEASE = f"projects/{PROJECT}/releases/cloud.firestore"

token = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True, check=True).stdout.strip()
session = AuthorizedSession(Credentials(token))
session.headers["x-goog-user-project"] = PROJECT

source = (Path(__file__).parent / "firestore.rules").read_text()
response = session.post(f"{API}/rulesets", json={"source": {"files": [{"name": "firestore.rules", "content": source}]}})
response.raise_for_status()
ruleset = response.json()["name"]

release = {"name": RELEASE, "rulesetName": ruleset}
existing = session.get(f"{API}/releases/cloud.firestore")
if existing.status_code == 404:
    response = session.post(f"{API}/releases", json=release)
else:
    response = session.patch(f"{API}/releases/cloud.firestore", json={"release": release})
response.raise_for_status()
print(f"Firestore now uses {ruleset}")
