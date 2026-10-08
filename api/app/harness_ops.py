"""Orchestrates one harness call: cap check, job record, authenticated
call to the harness, independent re-validation, cost recording.

docs/HARNESS_SPEC.md: "the API re-validates independently" - the
_validate_semantics check here is separate from whatever the harness
already ran, not a shortcut that trusts it.
"""

from shared.schemas import (
    EvaluateExerciseRequest,
    EvaluateExerciseResponse,
    EvaluateWritingRequest,
    EvaluateWritingResponse,
    GenerateExerciseRequest,
    GenerateExerciseResponse,
    GenerateLessonRequest,
    GenerateLessonResponse,
    TranscribeRequest,
    TranscribeResponse,
)
from shared.validation import check_item_ids, check_page_numbers, resolve_annotations

from . import jobs, spend
from .cost import estimate_cost
from .harness_client import post_to_harness
from .settings import get_settings

_OPERATIONS = {
    "generate_exercise": (GenerateExerciseRequest, GenerateExerciseResponse),
    "transcribe": (TranscribeRequest, TranscribeResponse),
    "evaluate_exercise": (EvaluateExerciseRequest, EvaluateExerciseResponse),
    "evaluate_writing": (EvaluateWritingRequest, EvaluateWritingResponse),
    "generate_lesson": (GenerateLessonRequest, GenerateLessonResponse),
}


class SpendCapReached(Exception):
    pass


class HarnessValidationFailed(Exception):
    pass


def _validate_semantics(operation: str, req, result) -> None:
    """The semantic checks worth re-running independently of the harness:
    annotation spans (docs/HARNESS_SPEC.md section 3), and that each item
    or page sent came back exactly once, in order. Every
    other rule (unique ids, permutations, codes, ...) is already enforced
    by the shared Pydantic schema itself, which both sides parse with.
    """
    if operation == "evaluate_exercise":
        check_item_ids([i.item_id for i in result.items], [i.item_id for i in req.items])
        for item, item_req in zip(result.items, req.items, strict=True):
            resolve_annotations(item.annotations, item_req.response)
    elif operation == "evaluate_writing":
        resolve_annotations(result.annotations, req.text)
    elif operation == "transcribe":
        check_page_numbers([p.page for p in result.pages], len(req.pages))


def call_harness(operation: str, req) -> tuple[object, str]:
    """Calls one harness operation end to end. Returns the validated
    operation-specific result (not the response envelope) and the job id,
    so the caller can later record what the teacher did with the result."""
    if operation not in _OPERATIONS:
        raise ValueError(f"unknown operation {operation!r}")
    _, response_cls = _OPERATIONS[operation]

    settings = get_settings()
    if spend.current_month_spend() + settings.estimated_cost_per_call_usd > settings.monthly_cap_usd:
        raise SpendCapReached(f"monthly spend cap (${settings.monthly_cap_usd:.2f}) would be exceeded")

    job_id = jobs.create_job(operation, req.student_id, req.prompt_version)

    try:
        raw = post_to_harness(operation, req.model_dump(mode="json"))
        envelope = response_cls.model_validate(raw)
        _validate_semantics(operation, req, envelope.result)
    except Exception as exc:
        jobs.fail_job(job_id, str(exc))
        raise HarnessValidationFailed(str(exc)) from exc

    cost_usd = estimate_cost(envelope.model, envelope.tokens_in, envelope.tokens_out, envelope.tokens_cached)
    jobs.complete_job(
        job_id,
        model=envelope.model,
        tokens_in=envelope.tokens_in,
        tokens_out=envelope.tokens_out,
        tokens_cached=envelope.tokens_cached,
        latency_ms=envelope.latency_ms,
        cost_usd=cost_usd,
        validation_outcome="passed",
    )
    spend.record_spend(cost_usd)
    return envelope.result, job_id
