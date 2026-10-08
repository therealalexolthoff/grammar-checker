"""Writing exercises: handwritten work and revision (docs/BUILD_PLAN.md
Phase 6). Generating, assigning, typing, submitting, scrubbing and
evaluating a writing exercise use the same endpoints as grammar
(exercises.py, review.py); this module has what only writing needs.

Handwriting (FR-23 to FR-25), teacher only:
1. Upload photos of the pages, in page order, any time before evaluation
   - whether or not the student typed anything. Metadata is stripped and
   the photos are kept in the private bucket (photos.py).
2. Transcribe: the harness copies the pages verbatim. This locks the
   student's typed answer, as if they had submitted.
       ... -> transcribing -> transcript_review
3. Correct the transcription side by side with the photos.
4. Choose the final source, typed or photo. Its text becomes the scrubbed
   copy, and the usual scrub and evaluation flow follows (review.py).
       transcript_review -> scrub_review
   The transcription is the "original" for the photo source: the teacher
   corrects it to match the page, but never edits it to scrub it.

Revision (FR-26, FR-27): releasing an evaluation with flagged spans opens
the student's one revision round (exercises.py, release). The student
retypes flagged spans (autosaved) and submits, which locks it; then the
teacher marks each changed span fixed, unfixed, or changed_wrongly.
       revision_open -> revision_submitted
Revisions are never sent to the harness.
"""

import base64
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, HTTPException

from shared.schemas import PROMPT_VERSION, TranscribeRequest

from . import jobs, photos
from .auth import CurrentUser, get_current_user, require_teacher
from .exercises import (
    _load_exercise,
    _load_submission,
    _submission_ref,
    _teacher_view,
    call_ai,
    load_for_student,
    update_open_submission,
)
from .models import WRITING_KEY, FinalSourceBody, OutcomesBody, RevisionBody, TranscriptionBody
from .revision import changed_edits, check_edit_keys

router = APIRouter(tags=["writing"])

MAX_PAGES = 10
# The browser sends photos at most 2000 pixels on the long side, which is
# well under 1 MB. 3 MB leaves room while keeping each page under the AI
# provider's 5 MB per-image limit once base64-encoded.
MAX_PHOTO_BYTES = 3_000_000

# Photos can be added or removed, and transcribed, until evaluation starts.
_PHOTO_STATES = ("assigned", "in_progress", "transcript_review", "scrub_review")
# Changing the final source replaces the scrubbed copy, so like a scrub
# edit it throws away any evaluation not yet released.
_FINAL_SOURCE_STATES = ("transcript_review", "scrub_review", "draft_ready", "ready_to_release")
# A transcription "in progress" this long has died with its server (the
# call itself gives up after 280s); it may be started again.
_STALE_TRANSCRIPTION = timedelta(minutes=5)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_writing(exercise_id: str, allowed_states: tuple[str, ...]) -> tuple[dict, dict]:
    exercise = _load_exercise(exercise_id)
    submission = _load_submission(exercise_id)
    if exercise["kind"] != "writing" or submission is None:
        raise HTTPException(status_code=409, detail="This isn't an assigned writing exercise.")
    if submission["state"] not in allowed_states:
        raise HTTPException(status_code=409, detail="This exercise isn't at that stage.")
    return exercise, submission


# ---- handwriting (teacher) ----


@router.post("/exercises/{exercise_id}/photos")
def upload_photo(
    exercise_id: str,
    data: bytes = Body(media_type="image/jpeg"),
    user: CurrentUser = Depends(require_teacher),
) -> dict:
    """Adds one page (a JPEG, as the request body) after the pages already
    uploaded. The screen uploads pages one at a time, in order."""
    exercise, submission = _load_writing(exercise_id, _PHOTO_STATES)
    pages = submission.get("photos", [])
    if len(pages) >= MAX_PAGES:
        raise HTTPException(status_code=409, detail=f"At most {MAX_PAGES} pages per exercise.")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="That photo is too large.")
    try:
        clean = photos.strip_jpeg_metadata(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="That file isn't a JPEG photo.") from exc

    path = photos.photo_path(exercise["student_id"], exercise_id, str(uuid.uuid4()))
    photos.upload(path, clean)
    _submission_ref(exercise_id).update({"photos": pages + [{"path": path, "uploaded_at": _now()}]})
    return _teacher_view(exercise_id, exercise)


@router.delete("/exercises/{exercise_id}/photos")
def remove_photos(exercise_id: str, user: CurrentUser = Depends(require_teacher)) -> dict:
    """Removes every page, to start the upload again (e.g. pages in the
    wrong order). Any transcription already made is kept."""
    exercise, submission = _load_writing(exercise_id, _PHOTO_STATES)
    for page in submission.get("photos", []):
        photos.delete(page["path"])
    _submission_ref(exercise_id).update({"photos": []})
    return _teacher_view(exercise_id, exercise)


@router.get("/exercises/{exercise_id}/photos")
def photo_links(exercise_id: str, user: CurrentUser = Depends(require_teacher)) -> list[dict]:
    """Short-lived links to view each page, in order. Teacher only - never
    shown to students (FR-25)."""
    submission = _load_submission(exercise_id) or {}
    return [
        {"page": number, "url": photos.signed_url(page["path"])}
        for number, page in enumerate(submission.get("photos", []), start=1)
    ]


@router.post("/exercises/{exercise_id}/transcribe")
def transcribe(exercise_id: str, user: CurrentUser = Depends(require_teacher)) -> dict:
    """Sends the photos (and nothing else about the student but the opaque
    id) to the harness for a verbatim transcription (FR-24). If the call
    fails, the submission goes back to where it was (FR-34)."""
    exercise = _load_exercise(exercise_id)
    submission = _load_submission(exercise_id)
    if exercise["kind"] != "writing" or submission is None:
        raise HTTPException(status_code=409, detail="This isn't an assigned writing exercise.")
    state = submission["state"]
    stale = state == "transcribing" and _now() - submission["transcribing_since"] > _STALE_TRANSCRIPTION
    if state not in _PHOTO_STATES and not stale:
        message = "A transcription is already running." if state == "transcribing" else "This exercise isn't at that stage."
        raise HTTPException(status_code=409, detail=message)
    pages = submission.get("photos", [])
    if not pages:
        raise HTTPException(status_code=409, detail="Upload at least one photo first.")
    previous_state = submission["state_before_transcribing"] if stale else state

    req = TranscribeRequest(
        student_id=exercise["student_id"],
        request_id=str(uuid.uuid4()),
        prompt_version=PROMPT_VERSION,
        pages=[base64.b64encode(photos.download(page["path"])).decode("ascii") for page in pages],
    )
    # From here the student can no longer change their typed answer: an
    # autosave on its way only writes if the state is still open (see
    # exercises.update_open_submission).
    ref = _submission_ref(exercise_id)
    changes = {"state": "transcribing", "transcribing_since": _now(), "state_before_transcribing": previous_state}
    if "submitted_at" not in submission:
        changes["submitted_at"] = _now()  # handed in on paper: counts as submitted now
    ref.update(changes)
    try:
        result, job_id = call_ai("transcribe", req)
    except Exception:
        ref.update({"state": previous_state})
        raise

    if submission.get("transcription_job_id"):
        jobs.set_teacher_action(submission["transcription_job_id"], "regenerated")
    text = "\n\n".join(page.text for page in result.pages)
    ref.update(
        {
            "state": "transcript_review",
            "transcription": text,
            "transcription_ai": text,
            "transcription_job_id": job_id,
            "updated_at": _now(),
        }
    )
    return _teacher_view(exercise_id, exercise)


@router.put("/exercises/{exercise_id}/transcription")
def save_transcription(
    exercise_id: str, body: TranscriptionBody, user: CurrentUser = Depends(require_teacher)
) -> dict:
    """The teacher's corrections to the transcription, so it matches what
    the student actually wrote, errors included (FR-24)."""
    exercise, _ = _load_writing(exercise_id, ("transcript_review",))
    _submission_ref(exercise_id).update({"transcription": body.text, "updated_at": _now()})
    return _teacher_view(exercise_id, exercise)


@router.post("/exercises/{exercise_id}/final-source")
def choose_final_source(
    exercise_id: str, body: FinalSourceBody, user: CurrentUser = Depends(require_teacher)
) -> dict:
    """Which version is evaluated: the typed answer or the transcription
    (FR-24). Its text becomes a fresh scrubbed copy, so any scrub edits and
    any evaluation of the other version are discarded."""
    _, submission = _load_writing(exercise_id, _FINAL_SOURCE_STATES)
    if body.source == "photo":
        text = submission.get("transcription")
        if text is None:
            raise HTTPException(status_code=409, detail="There's no transcription yet.")
    else:
        text = submission["answers"].get(WRITING_KEY, "")
    if not text.strip():
        raise HTTPException(status_code=409, detail="That version is empty.")

    _submission_ref(exercise_id).update(
        {
            "final_source": body.source,
            "scrubbed_answers": {WRITING_KEY: text},
            "state": "scrub_review",
            "evaluation": None,
            "evaluation_ai": None,
            "evaluation_valid": False,
            "updated_at": _now(),
        }
    )
    if body.source == "photo":
        action = "accepted" if text == submission["transcription_ai"] else "edited"
        jobs.set_teacher_action(submission["transcription_job_id"], action)
    return _teacher_view(exercise_id, _load_exercise(exercise_id))


# ---- revision ----


def _revision_context(exercise_id: str, user: CurrentUser) -> tuple[str, list[dict]]:
    """The released text and its annotations, for the student's own
    writing exercise."""
    if user.role != "student":
        raise HTTPException(status_code=403, detail="students only")
    load_for_student(exercise_id, user)
    submission = _load_submission(exercise_id) or {}
    if submission.get("state") not in ("revision_open", "revision_submitted"):
        raise HTTPException(status_code=409, detail="This work can't be revised.")
    return submission["scrubbed_answers"][WRITING_KEY], submission["evaluation"]["annotations"]


@router.put("/exercises/{exercise_id}/revision")
def save_revision(exercise_id: str, body: RevisionBody, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Autosave of the student's span edits (FR-26)."""
    _, annotations = _revision_context(exercise_id, user)
    update_open_submission(
        exercise_id,
        check=lambda: check_edit_keys(body.edits, len(annotations)),
        changes={"revision": {"edits": body.edits}, "updated_at": _now()},
        open_states=("revision_open",),
    )
    return {"status": "saved"}


@router.post("/exercises/{exercise_id}/revision/submit")
def submit_revision(exercise_id: str, body: RevisionBody, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Submits the one revision round and locks it (FR-26). Only spans the
    student actually changed are kept."""
    text, annotations = _revision_context(exercise_id, user)
    check_edit_keys(body.edits, len(annotations))
    edits = changed_edits(body.edits, text, annotations)
    update_open_submission(
        exercise_id,
        check=lambda: None,
        changes={
            "revision": {"edits": edits, "submitted_at": _now()},
            "state": "revision_submitted",
            "updated_at": _now(),
        },
        open_states=("revision_open",),
    )
    return {"status": "submitted"}


@router.put("/exercises/{exercise_id}/revision/outcomes")
def mark_outcomes(exercise_id: str, body: OutcomesBody, user: CurrentUser = Depends(require_teacher)) -> dict:
    """The teacher marks each changed span fixed, unfixed, or
    changed_wrongly (FR-27). Spans can be marked a few at a time."""
    exercise, submission = _load_writing(exercise_id, ("revision_submitted",))
    revision = submission["revision"]
    unknown = sorted(set(body.outcomes) - set(revision["edits"]))
    if unknown:
        raise HTTPException(status_code=422, detail=f"span {unknown[0]!r} wasn't changed by the student")
    _submission_ref(exercise_id).update({"revision": {**revision, "outcomes": body.outcomes}, "updated_at": _now()})
    return _teacher_view(exercise_id, exercise)
