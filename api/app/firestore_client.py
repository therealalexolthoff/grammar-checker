"""Firestore access for the API service.

Lazily builds a singleton client. In dev, set FIRESTORE_EMULATOR_HOST (see
scripts/dev_firestore_emulator.sh) and the google-cloud-firestore client
talks to the local emulator automatically instead of real Firestore.

Project resolution: FIRESTORE_PROJECT_ID if set (for local dev against the
emulator, where the project id is arbitrary); otherwise let the client
auto-detect from the environment's credentials - on Cloud Run that's the
real project, via the metadata server. There is no real-project fallback
here on purpose: guessing wrong would silently point production at the
wrong project instead of failing loudly.
"""

import os

from google.cloud import firestore

_db: firestore.Client | None = None


def get_db() -> firestore.Client:
    global _db
    if _db is None:
        project_id = os.environ.get("FIRESTORE_PROJECT_ID")
        _db = firestore.Client(project=project_id) if project_id else firestore.Client()
    return _db
