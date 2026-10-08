"""Scrubbing and evaluation of short answers (docs/BUILD_PLAN.md Phase 5).

After a grammar exercise with short answers is submitted, the teacher:
1. edits the scrubbed copy of each short answer (removing personal
   details) - the original answers are never changed or sent anywhere;
2. sends the scrubbed copy for evaluation (or regenerates, with a note);
3. reviews the AI draft: changes marks, feedback, and annotations (add,
   remove, recode);
4. approves it, then releases it (the release endpoint is in exercises.py).

States (docs/ARCHITECTURE.md section 5):
    scrub_review -> evaluating -> draft_ready -> ready_to_release
Editing the scrubbed text after evaluation throws the evaluation away and
returns to scrub_review, since its spans pointed into the old text.

The evaluation is stored twice on the submission: "evaluation_ai" as the
AI returned it, and "evaluation" as the teacher has edited it. Comparing
the two at approval gives the job's teacher_action (the quality signal),
and a changed mark is an override, which is audit-logged (FR-5).
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException

from shared.schemas import (
    PROMPT_VERSION,
    EvaluateExerciseRequest,
    EvaluateExerciseResult,
    ScrubbedShortAnswer,
    ShortAnswerItem,
)
from shared.validation import SpanError, check_item_ids, resolve_annotations

from . import jobs
from .audit import record as record_audit
from .auth import CurrentUser, require_teacher
from .exercises import _draft, _load_exercise, _load_submission, _submission_ref, _teacher_view, call_ai
from .models import EvaluateBody, ScrubbedBody

router = APIRouter(tags=["review"])

# States in which the scrubbed copy and the evaluation can be worked on.
_EVALUATED_STATES = ("draft_ready", "ready_to_release")
_REVIEW_STATES = ("scrub_review",) + _EVALUATED_STATES
# An evaluation that has been "in progress" this long has died with its
# server (the call itself gives up after 280s); it may be started again.
_STALE_EVALUATION = timedelta(minutes=5)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _short_answer_items(exercise: dict) -> list[ShortAnswerItem]:
    return [item for item in _draft(exercise).items if isinstance(item, ShortAnswerItem)]


def _load_for_review(exercise_id: str, allowed_states: tuple[str, ...]) -> tuple[dict, dict]:
    exercise = _load_exercise(exercise_id)
    submission = _load_submission(exercise_id)
    if submission is None or submission["state"] not in allowed_states:
        raise HTTPException(status_code=409, detail="This exercise isn't at that stage.")
    return exercise, submission


def _with_offsets(result: EvaluateExerciseResult, scrubbed: dict[str, str]) -> dict:
    """The evaluation as stored: each annotation gains the character
    offsets the API computed against the exact scrubbed text
    (docs/HARNESS_SPEC.md section 3). Raises SpanError if a span isn't in
    the text or two spans overlap."""
    items = []
    for item in result.items:
        spans = resolve_annotations(item.annotations, scrubbed[item.item_id])
        annotations = [
            {**a.model_dump(mode="json"), "start": start, "end": end}
            for a, (start, end) in zip(item.annotations, spans, strict=True)
        ]
        items.append({"item_id": item.item_id, "mark": item.mark, "feedback": item.feedback, "annotations": annotations})
    return {"items": items}


@router.put("/exercises/{exercise_id}/scrubbed")
def save_scrubbed(exercise_id: str, body: ScrubbedBody, user: CurrentUser = Depends(require_teacher)) -> dict:
    """The teacher's edits to the scrubbed copy (FR-18). If an evaluation
    exists and the text changed, the evaluation is discarded - its spans
    pointed into the old text."""
    exercise, submission = _load_for_review(exercise_id, _REVIEW_STATES)
    expected = sorted(item.id for item in _short_answer_items(exercise))
    if sorted(body.scrubbed_answers) != expected:
        raise HTTPException(status_code=422, detail=f"expected scrubbed text for items {expected}")

    changes: dict = {"scrubbed_answers": body.scrubbed_answers, "updated_at": _now()}
    if body.scrubbed_answers != submission.get("scrubbed_answers") and submission["state"] in _EVALUATED_STATES:
        changes.update(
            {"state": "scrub_review", "evaluation": None, "evaluation_ai": None, "evaluation_valid": False}
        )
    _submission_ref(exercise_id).update(changes)
    return _teacher_view(exercise_id, exercise)


@router.post("/exercises/{exercise_id}/evaluate")
def evaluate(exercise_id: str, body: EvaluateBody, user: CurrentUser = Depends(require_teacher)) -> dict:
    """Send for evaluation (FR-19), or regenerate the evaluation with an
    optional note (FR-20). Only the scrubbed text is sent - never the
    original answers, never the username. If the call fails, the
    submission goes back to where it was and nothing is lost (FR-34)."""
    exercise = _load_exercise(exercise_id)
    submission = _load_submission(exercise_id)
    state = submission["state"] if submission else None
    stale = (
        state == "evaluating"
        and _now() - submission["evaluating_since"] > _STALE_EVALUATION
    )
    if state not in _REVIEW_STATES and not stale:
        message = "An evaluation is already running." if state == "evaluating" else "This exercise isn't at that stage."
        raise HTTPException(status_code=409, detail=message)
    previous_state = submission["state_before_evaluating"] if stale else state

    scrubbed = submission["scrubbed_answers"]
    items = _short_answer_items(exercise)
    req = EvaluateExerciseRequest(
        student_id=exercise["student_id"],
        request_id=str(uuid.uuid4()),
        prompt_version=PROMPT_VERSION,
        items=[ScrubbedShortAnswer(item_id=item.id, prompt=item.prompt, response=scrubbed[item.id]) for item in items],
        regenerate_note=body.note or None,
    )

    ref = _submission_ref(exercise_id)
    ref.update({"state": "evaluating", "evaluating_since": _now(), "state_before_evaluating": previous_state})
    try:
        result, job_id = call_ai("evaluate_exercise", req)
        evaluation = _with_offsets(result, scrubbed)  # the API re-validated these spans already
    except Exception:
        ref.update({"state": previous_state})
        raise

    old_job_id = submission.get("evaluation_job_id")
    if old_job_id and submission.get("evaluation_valid"):
        jobs.set_teacher_action(old_job_id, "regenerated")
    ref.update(
        {
            "state": "draft_ready",
            "evaluation": evaluation,
            "evaluation_ai": evaluation,
            "evaluation_valid": True,
            "evaluation_job_id": job_id,
            "updated_at": _now(),
        }
    )
    return _teacher_view(exercise_id, exercise)


@router.put("/exercises/{exercise_id}/evaluation")
def edit_evaluation(
    exercise_id: str, body: EvaluateExerciseResult, user: CurrentUser = Depends(require_teacher)
) -> dict:
    """The teacher's edits to the draft (FR-20): marks, feedback, and
    annotations. Parsed with the same shared schema as the AI's output and
    span-checked the same way, so an edit can't produce something the
    student screen can't show. A changed mark is audit-logged as an
    override (FR-5)."""
    exercise, submission = _load_for_review(exercise_id, _EVALUATED_STATES)
    scrubbed = submission["scrubbed_answers"]
    check_item_ids([i.item_id for i in body.items], [item.id for item in _short_answer_items(exercise)])
    try:
        evaluation = _with_offsets(body, scrubbed)
    except SpanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    ai_marks = {i["item_id"]: i["mark"] for i in submission["evaluation_ai"]["items"]}
    saved_marks = {i["item_id"]: i["mark"] for i in submission["evaluation"]["items"]}
    for item in body.items:
        # Logged once, when the mark first moves away from what is saved.
        if item.mark != saved_marks[item.item_id] and item.mark != ai_marks[item.item_id]:
            record_audit(user.uid, "override_mark", target=f"{exercise_id}/{item.item_id}")

    # Editing after approval means it needs approving again.
    _submission_ref(exercise_id).update({"evaluation": evaluation, "state": "draft_ready", "updated_at": _now()})
    return _teacher_view(exercise_id, exercise)


@router.post("/exercises/{exercise_id}/approve")
def approve(exercise_id: str, user: CurrentUser = Depends(require_teacher)) -> dict:
    """The teacher is done reviewing: draft_ready -> ready_to_release.
    Records on the evaluation's job what the teacher did with it."""
    exercise, submission = _load_for_review(exercise_id, ("draft_ready",))
    final, ai = submission["evaluation"], submission["evaluation_ai"]
    if final == ai:
        action = "accepted"
    elif [i["mark"] for i in final["items"]] != [i["mark"] for i in ai["items"]]:
        action = "overridden"
    else:
        action = "edited"
    jobs.set_teacher_action(submission["evaluation_job_id"], action)
    _submission_ref(exercise_id).update({"state": "ready_to_release", "updated_at": _now()})
    return _teacher_view(exercise_id, exercise)
