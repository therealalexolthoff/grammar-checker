"""The learner profile (docs/REQUIREMENTS.md FR-30): which error codes a
student has been making recently, and how their revisions went.

Computed by plain code, never by the harness, and only from data the
teacher has approved:
- each annotation in an approved evaluation (short answers and writing),
- each wrong fill_blank / reorder item, counted under its concept code,
- each revision outcome the teacher marked, under the span's code.
"Approved" means the teacher approved the evaluation (or there was none
to approve: graded-only grammar exercises). Only the most recent
submissions count - the window is a setting (default 5).

Nothing is stored: the profile is worked out again each time it's needed,
so it always matches the data it comes from.
"""

from google.cloud.firestore_v1.base_query import FieldFilter

from shared.taxonomy import CODE_DESCRIPTIONS, ErrorCode

from .firestore_client import get_db
from .models import WRITING_KEY
from .settings import get_settings

# Submission states that come after the teacher's approval.
APPROVED_STATES = ("ready_to_release", "released", "revision_open", "revision_submitted", "revision_reviewed")
OUTCOMES = ("fixed", "unfixed", "changed_wrongly")


def recent_approved(student_id: str, window: int | None = None) -> list[tuple[dict, dict]]:
    """The student's `window` most recently submitted approved pieces of
    work, newest first, as (exercise, submission) pairs."""
    if window is None:
        window = get_settings().profile_window
    db = get_db()
    docs = db.collection("submissions").where(filter=FieldFilter("student_id", "==", student_id)).stream()
    submissions = [(doc.id, doc.to_dict()) for doc in docs]
    approved = [(sid, s) for sid, s in submissions if s.get("state") in APPROVED_STATES]
    # Every submit sets submitted_at; updated_at is a fallback for any older
    # record without it.
    approved.sort(key=lambda pair: pair[1].get("submitted_at") or pair[1]["updated_at"], reverse=True)
    pairs = []
    for exercise_id, submission in approved[:window]:
        exercise = db.collection("exercises").document(exercise_id).get().to_dict()
        pairs.append((exercise, submission))
    return pairs


def annotated_spans(submission: dict) -> list[dict]:
    """Every approved annotation in a submission, with the scrubbed text it
    points into: [{"code", "text", "start", "end"}, ...]."""
    evaluation = submission.get("evaluation") or {}
    scrubbed = submission.get("scrubbed_answers", {})
    if "annotations" in evaluation:  # writing
        groups = [(scrubbed[WRITING_KEY], evaluation["annotations"])]
    else:  # short answers
        groups = [(scrubbed[item["item_id"]], item["annotations"]) for item in evaluation.get("items", [])]
    return [
        {"code": a["code"], "text": text, "start": a["start"], "end": a["end"]}
        for text, annotations in groups
        for a in annotations
    ]


def wrong_item_codes(exercise: dict, submission: dict) -> list[str]:
    """The concept code of each fill_blank / reorder item answered wrongly."""
    concepts = {item["id"]: item["concept"] for item in exercise.get("items", []) if "concept" in item}
    return [concepts[item_id] for item_id, correct in submission.get("grades", {}).items() if not correct]


def compute_profile(pairs: list[tuple[dict, dict]]) -> list[dict]:
    """Per error code: how many errors, and how the revision went. Most
    frequent first; codes with nothing recorded are left out."""
    counts = {code.value: {"errors": 0, **{o: 0 for o in OUTCOMES}} for code in ErrorCode}
    for exercise, submission in pairs:
        for span in annotated_spans(submission):
            counts[span["code"]]["errors"] += 1
        for code in wrong_item_codes(exercise, submission):
            counts[code]["errors"] += 1
        revision = submission.get("revision") or {}
        annotations = (submission.get("evaluation") or {}).get("annotations", [])
        for index, outcome in revision.get("outcomes", {}).items():
            counts[annotations[int(index)]["code"]][outcome] += 1

    rows = [
        {"code": code, "meaning": CODE_DESCRIPTIONS[ErrorCode(code)], **c}
        for code, c in counts.items()
        if c["errors"] or any(c[o] for o in OUTCOMES)
    ]
    rows.sort(key=lambda row: row["errors"], reverse=True)
    return rows


def student_profile(student_id: str) -> dict:
    window = get_settings().profile_window
    pairs = recent_approved(student_id, window)
    return {"window": window, "submissions_counted": len(pairs), "codes": compute_profile(pairs)}
