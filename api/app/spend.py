"""Monthly Claude spend: the hard cap and the teacher-facing total.

docs/REQUIREMENTS.md FR-33: estimate before, enforce cap, record after.
Read-then-write rather than an atomic increment: harness calls are
synchronous with no queue (docs/ARCHITECTURE.md section 3) and this is a
single-teacher app, so there's no concurrent-write race to guard against.
"""

from datetime import datetime, timezone

from .firestore_client import get_db


def _month_key(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


def current_month_spend() -> float:
    doc = get_db().collection("spend").document(_month_key()).get()
    if not doc.exists:
        return 0.0
    return doc.to_dict().get("total_usd", 0.0)


def record_spend(cost_usd: float) -> None:
    doc_ref = get_db().collection("spend").document(_month_key())
    doc_ref.set({"total_usd": current_month_spend() + cost_usd})
