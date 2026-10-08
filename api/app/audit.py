"""Audit log: who did what to whom, and when.

Per docs/REQUIREMENTS.md FR-5: overrides, reopens, deletions, and password
resets are recorded here. Write-only from the app's side for now - nothing
reads this back until a teacher-facing audit view is built.
"""

from datetime import datetime, timezone

from .firestore_client import get_db


def record(actor_uid: str, action: str, target: str) -> None:
    get_db().collection("audit").add(
        {
            "actor": actor_uid,
            "action": action,
            "target": target,
            "timestamp": datetime.now(timezone.utc),
        }
    )
