"""Writing exercises: handwritten work and revision (docs/BUILD_PLAN.md
Phase 6). Generating, assigning, typing, submitting, scrubbing and
evaluating a writing exercise use the same endpoints as grammar
(exercises.py, review.py); this module has what only writing needs.

Handwriting (FR-23 to FR-25):
1. Upload photos of the pages, in page order. The teacher can do this any
   time before evaluation - whether or not the student typed anything.
   The student can add photos of their own pages while the exercise is
   still open, see only those pages, and start them again; submitting
   locks them like the typed answer. Metadata is stripped and the photos
   are kept in the private bucket (photos.py).
   Steps 2-4 are teacher only.
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
teacher marks each changed span fixed, unfixed, or changed_wrongly
(saved as often as they like), and once every one is marked, sends the
marks back to the student, which locks them.
       revision_open -> revision_submitted -> revision_reviewed
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
    OPEN_STATES,
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


# ---- handwriting: photos (teacher, and the student while open) ----


def _store_page(exercise_id: str, student_id: str, data: bytes, uploaded_by: str) -> dict:
    """Strips the photo's metadata, saves it to the bucket, and returns its
    entry for the submission's "photos" list."""
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="That photo is too large.")
    try:
        clean = photos.strip_jpeg_metadata(data)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="That file isn't a JPEG photo.") from exc
    path = photos.photo_path(student_id, exercise_id, str(uuid.uuid4()))
    photos.upload(path, clean)
    return {"path": path, "uploaded_at": _now(), "uploaded_by": uploaded_by}


def _is_students(page: dict) -> bool:
    # Pages from before students could upload have no "uploaded_by": they
    # are the teacher's.
    return page.get("uploaded_by") == "student"


def _links(pages: list[dict]) -> list[dict]:
    return [{"page": number, "url": photos.signed_url(page["path"])} for number, page in enumerate(pages, start=1)]


def _load_student_writing(exercise_id: str, user: CurrentUser) -> dict:
    exercise = load_for_student(exercise_id, user)
    if exercise["kind"] != "writing":
        raise HTTPException(status_code=409, detail="Photos are only for writing exercises.")
    return exercise


def _student_pages(exercise_id: str) -> list[dict]:
    """The student's own pages, as short-lived links - only while the
    exercise is open. After submitting they see no photos (FR-25), and
    never pages the teacher uploaded."""
    submission = _load_submission(exercise_id) or {}
    if submission.get("state") not in OPEN_STATES:
        return []
    return _links([page for page in submission.get("photos", []) if _is_students(page)])


@router.post("/exercises/{exercise_id}/photos")
def upload_photo(
    exercise_id: str,
    data: bytes = Body(media_type="image/jpeg"),
    user: CurrentUser = Depends(get_current_user),
):
    """Adds one page (a JPEG, as the request body) after the pages already
    uploaded. The screen uploads pages one at a time, in order."""
    if user.role == "student":
        return _student_upload(exercise_id, data, user)
    exercise, submission = _load_writing(exercise_id, _PHOTO_STATES)
    pages = submission.get("photos", [])
    if len(pages) >= MAX_PAGES:
        raise HTTPException(status_code=409, detail=f"At most {MAX_PAGES} pages per exercise.")
    page = _store_page(exercise_id, exercise["student_id"], data, "teacher")
    _submission_ref(exercise_id).update({"photos": pages + [page]})
    return _teacher_view(exercise_id, exercise)


def _student_upload(exercise_id: str, data: bytes, user: CurrentUser) -> list[dict]:
    exercise = _load_student_writing(exercise_id, user)
    if len((_load_submission(exercise_id) or {}).get("photos", [])) >= MAX_PAGES:
        raise HTTPException(status_code=409, detail=f"You can add at most {MAX_PAGES} pages.")
    page = _store_page(exercise_id, exercise["student_id"], data, "student")
    try:
        # Only while the exercise is still open: a submit (or the teacher
        # starting a transcription) at the same moment wins.
        update_open_submission(
            exercise_id,
            check=lambda: None,
            changes=lambda current: {
                "photos": current.get("photos", []) + [page],
                "state": "in_progress",
                "updated_at": _now(),
            },
        )
    except HTTPException:
        photos.delete(page["path"])  # not attached to the submission: don't keep it
        raise
    return _student_pages(exercise_id)


@router.delete("/exercises/{exercise_id}/photos")
def remove_photos(exercise_id: str, user: CurrentUser = Depends(get_current_user)):
    """Removes every page, to start the upload again (e.g. pages in the
    wrong order). Any transcription already made is kept. A student
    removes only their own pages, and only while the exercise is open."""
    if user.role == "student":
        return _student_remove(exercise_id, user)
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="teacher only")
    exercise, submission = _load_writing(exercise_id, _PHOTO_STATES)
    for page in submission.get("photos", []):
        photos.delete(page["path"])
    _submission_ref(exercise_id).update({"photos": []})
    return _teacher_view(exercise_id, exercise)


def _student_remove(exercise_id: str, user: CurrentUser) -> list[dict]:
    _load_student_writing(exercise_id, user)
    removed: list[str] = []

    def keep_teachers_pages(current: dict) -> dict:
        pages = current.get("photos", [])
        removed[:] = [page["path"] for page in pages if _is_students(page)]
        return {"photos": [page for page in pages if not _is_students(page)], "updated_at": _now()}

    update_open_submission(exercise_id, check=lambda: None, changes=keep_teachers_pages)
    for path in removed:
        photos.delete(path)
    return _student_pages(exercise_id)


@router.get("/exercises/{exercise_id}/photos")
def photo_links(exercise_id: str, user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    """Short-lived links to view each page, in order. The teacher sees
    every page; a student sees only their own, and only until they submit
    (FR-25)."""
    if user.role == "student":
        _load_student_writing(exercise_id, user)
        return _student_pages(exercise_id)
    if user.role != "teacher":
        raise HTTPException(status_code=403, detail="teacher only")
    return _links((_load_submission(exercise_id) or {}).get("photos", []))


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


@router.post("/exercises/{exercise_id}/revision/send")
def send_outcomes(exercise_id: str, user: CurrentUser = Depends(require_teacher)) -> dict:
    """Shows the student how their revision went: each changed span's
    outcome, and the correction for each one not fixed (FR-27). Only once
    every changed span is marked; the marks can't be changed after."""
    exercise, submission = _load_writing(exercise_id, ("revision_submitted",))
    revision = submission["revision"]
    if set(revision["edits"]) - set(revision.get("outcomes", {})):
        raise HTTPException(status_code=409, detail="Mark every change before sending.")
    _submission_ref(exercise_id).update({"state": "revision_reviewed", "updated_at": _now()})
    return _teacher_view(exercise_id, exercise)
