"""The class overview (docs/REQUIREMENTS.md FR-32): one screen listing
each student with their unfinished work, the stage each piece is at, and
lessons they haven't read yet. Teacher only.

Work counts as finished once released with nothing left to do: released
grammar or writing with no revision, or a checked revision sent back to
the student. Drafts aren't listed - they haven't
reached the student yet.
"""

from fastapi import APIRouter, Depends

from .auth import CurrentUser, require_teacher
from .firestore_client import get_db

router = APIRouter(tags=["overview"])

# The pipeline stages in order (docs/ARCHITECTURE.md section 5), so each
# student's work is listed from earliest to latest stage.
PIPELINE = [
    "assigned",
    "in_progress",
    "transcribing",
    "transcript_review",
    "scrub_review",
    "evaluating",
    "draft_ready",
    "ready_to_release",
    "revision_open",
    "revision_submitted",
    "revision_reviewed",
]


def is_finished(submission: dict) -> bool:
    return submission.get("state") in ("released", "revision_reviewed")


@router.get("/overview")
def class_overview(user: CurrentUser = Depends(require_teacher)) -> list[dict]:
    db = get_db()
    titles = {doc.id: doc.get("title") for doc in db.collection("exercises").stream()}
    rows = {
        doc.id: {"student_id": doc.id, "username": doc.get("username"), "work": [], "unread_lessons": []}
        for doc in db.collection("students").stream()
        if doc.get("active")
    }

    for doc in db.collection("submissions").stream():
        submission = doc.to_dict()
        row = rows.get(submission["student_id"])
        if row is None or is_finished(submission):
            continue
        row["work"].append({"exercise_id": doc.id, "title": titles.get(doc.id, ""), "state": submission["state"]})

    for doc in db.collection("lessons").stream():
        lesson = doc.to_dict()
        row = rows.get(lesson["student_id"])
        if row is not None and lesson["status"] == "assigned" and lesson.get("read_at") is None:
            row["unread_lessons"].append({"lesson_id": doc.id, "title": lesson["title"]})

    for row in rows.values():
        row["work"].sort(key=lambda w: PIPELINE.index(w["state"]))
    return sorted(rows.values(), key=lambda row: row["username"].lower())
