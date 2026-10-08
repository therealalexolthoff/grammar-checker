"""Job records: one per harness call.

Used for cost tracking and, eventually, the override-rate quality signal
per prompt version/operation - docs/ARCHITECTURE.md sections 4 and 8.
"""

from datetime import datetime, timezone

from .firestore_client import get_db


def create_job(operation: str, student_id: str, prompt_version: str) -> str:
    doc_ref = get_db().collection("jobs").document()
    doc_ref.set(
        {
            "operation": operation,
            "student_id": student_id,
            "prompt_version": prompt_version,
            "status": "running",
            "created_at": datetime.now(timezone.utc),
        }
    )
    return doc_ref.id


def complete_job(
    job_id: str,
    *,
    model: str,
    tokens_in: int,
    tokens_out: int,
    tokens_cached: int,
    latency_ms: float,
    cost_usd: float,
    validation_outcome: str,
) -> None:
    get_db().collection("jobs").document(job_id).update(
        {
            "status": "done",
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "tokens_cached": tokens_cached,
            "latency_ms": latency_ms,
            "cost_usd": cost_usd,
            "validation_outcome": validation_outcome,
        }
    )


def fail_job(job_id: str, error: str, *, validation_outcome: str = "rejected") -> None:
    get_db().collection("jobs").document(job_id).update(
        {"status": "error", "error": error, "validation_outcome": validation_outcome}
    )
