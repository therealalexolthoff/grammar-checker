"""Grammar exercises, end to end (docs/BUILD_PLAN.md Phase 4).

Teacher: generate a draft, edit it, regenerate with a note, assign it
(after the approval checklist), release results, reopen a submission.
Student: list assigned work, open it, autosave answers, submit.

Firestore layout (docs/ARCHITECTURE.md section 4):
- exercises/{id}:   the exercise itself; status "draft" (editable) or
                    "assigned" (frozen).
- submissions/{id}: the student's answers and grades, created on assign.
                    Same id as its exercise - every exercise belongs to
                    exactly one student, so there is one submission each.

Submission states used in this phase (the rest of docs/ARCHITECTURE.md
section 5 comes in Phases 5 and 6):
    assigned -> in_progress -> ready_to_release -> released
                             \\-> scrub_review   (has short answers; Phase 5)

Writing exercises come in Phase 6; only kind "grammar" is accepted here.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from google.api_core.exceptions import FailedPrecondition
from google.cloud.firestore_v1.base_query import FieldFilter

from shared.schemas import (
    PROMPT_VERSION,
    FillBlankItem,
    GenerateExerciseRequest,
    GrammarExerciseDraft,
    ReorderItem,
    ShortAnswerItem,
)

from shared.taxonomy import CODE_DESCRIPTIONS

from .audit import record as record_audit
from .auth import CurrentUser, get_current_user, require_teacher
from .firestore_client import get_db
from .grading import grade_items
from .harness_ops import HarnessValidationFailed, SpendCapReached, call_harness
from .models import (
    AnswersBody,
    AssignBody,
    GenerateExerciseBody,
    RegenerateBody,
    StudentExerciseSummary,
    StudentExerciseView,
    StudentItemView,
)

router = APIRouter(tags=["exercises"])

# States in which the student may still change answers.
_OPEN_STATES = ("assigned", "in_progress")
# States the teacher may reopen from. Not "released": once the student has
# seen results, reopening would let them re-answer with the key in view.
_REOPENABLE_STATES = ("scrub_review", "ready_to_release")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _exercise_ref(exercise_id: str):
    return get_db().collection("exercises").document(exercise_id)


def _submission_ref(exercise_id: str):
    return get_db().collection("submissions").document(exercise_id)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="exercise not found")


def _items_to_firestore(items: list[dict]) -> list[dict]:
    """Firestore can't store a list directly inside a list, and a reorder
    item's accepted_orders is exactly that (a list of word orders). So
    each order is stored wrapped in a map, {"chunks": [...]}, and
    unwrapped again by _items_from_firestore. Everywhere else in the code
    works with the plain shared-schema form."""
    return [
        {**item, "accepted_orders": [{"chunks": order} for order in item["accepted_orders"]]}
        if item["type"] == "reorder"
        else item
        for item in items
    ]


def _items_from_firestore(items: list[dict]) -> list[dict]:
    return [
        {**item, "accepted_orders": [order["chunks"] for order in item["accepted_orders"]]}
        if item["type"] == "reorder"
        else item
        for item in items
    ]


def _load_exercise(exercise_id: str) -> dict:
    doc = _exercise_ref(exercise_id).get()
    if not doc.exists:
        raise _not_found()
    exercise = doc.to_dict()
    exercise["items"] = _items_from_firestore(exercise["items"])
    return exercise


def _load_submission(exercise_id: str) -> dict | None:
    doc = _submission_ref(exercise_id).get()
    return doc.to_dict() if doc.exists else None


def _update_open_submission(exercise_id: str, check, changes: dict) -> None:
    """Applies `changes` to a submission the student can still edit.

    Read, check and write would race otherwise: an autosave already on its
    way when the student taps Submit could read "in_progress", lose the
    race, and then write "in_progress" back over the submit - unlocking
    work that must stay locked (FR-15). So the write only goes through if
    the document is unchanged since it was read; if something else wrote
    in between, read again and re-check. `check` runs between the read
    and the write (answer-shape validation).
    """
    ref = _submission_ref(exercise_id)
    for _ in range(3):
        snapshot = ref.get()
        if not snapshot.exists or snapshot.get("state") not in _OPEN_STATES:
            raise HTTPException(status_code=409, detail="This exercise has already been submitted.")
        check()
        try:
            ref.update(changes, option=get_db().write_option(last_update_time=snapshot.update_time))
            return
        except FailedPrecondition:
            continue  # someone else wrote first; look again
    raise HTTPException(status_code=409, detail="Your answers could not be saved. Please try again.")


def _draft(exercise: dict) -> GrammarExerciseDraft:
    """Re-parses stored items into typed schema objects."""
    return GrammarExerciseDraft(title=exercise["title"], items=exercise["items"])


def _load_for_student(exercise_id: str, user: CurrentUser) -> dict:
    """The student may only see their own exercises, and only once
    assigned. Anything else looks like "not found" so a student can't
    probe which exercise ids exist."""
    exercise = _load_exercise(exercise_id)
    if exercise["student_id"] != user.student_id or exercise["status"] != "assigned":
        raise _not_found()
    return exercise


def _generate(student_id: str, description: str, note: str | None) -> GrammarExerciseDraft:
    """One generate_exercise harness call. Turns harness failures into
    teacher-readable errors; invalid drafts are never returned (FR-8)."""
    req = GenerateExerciseRequest(
        student_id=student_id,
        request_id=str(uuid.uuid4()),
        prompt_version=PROMPT_VERSION,
        kind="grammar",
        description=description,
        regenerate_note=note or None,
    )
    try:
        result = call_harness("generate_exercise", req)
    except SpendCapReached as exc:
        raise HTTPException(status_code=409, detail=f"{exc}. Generation is paused.") from exc
    except HarnessValidationFailed as exc:
        raise HTTPException(
            status_code=502, detail="The AI draft could not be used. Nothing was saved - please try again."
        ) from exc
    if not isinstance(result, GrammarExerciseDraft):
        raise HTTPException(
            status_code=502, detail="The AI returned the wrong kind of exercise. Please try again."
        )
    return result


def _teacher_view(exercise_id: str, exercise: dict) -> dict:
    """Everything, including answer keys and the student's answers."""
    submission = _load_submission(exercise_id) or {}
    return {
        "exercise_id": exercise_id,
        "student_id": exercise["student_id"],
        "status": exercise["status"],
        "title": exercise["title"],
        "items": exercise["items"],
        "teacher_request": exercise["teacher_request"],
        "state": submission.get("state", "draft"),
        "answers": submission.get("answers", {}),
        "grades": submission.get("grades", {}),
    }


def _student_item(item, released: bool, grades: dict) -> StudentItemView:
    if isinstance(item, FillBlankItem):
        view = StudentItemView(
            id=item.id, type=item.type, text=item.text, blank_ids=[b.id for b in item.blanks]
        )
    elif isinstance(item, ReorderItem):
        view = StudentItemView(id=item.id, type=item.type, chunks=item.chunks)
    else:
        view = StudentItemView(id=item.id, type=item.type, prompt=item.prompt)

    # Results only after release (FR-16: students see nothing until then).
    # Short-answer results arrive with evaluation in Phase 5.
    if released and not isinstance(item, ShortAnswerItem):
        view.correct = grades.get(item.id, False)
        view.explanation = item.explanation
        if not view.correct:  # FR-21: show the correct answer for wrong items
            if isinstance(item, FillBlankItem):
                view.correct_answer = {b.id: b.accepted[0] for b in item.blanks}
            else:
                view.correct_answer = item.accepted_orders[0]
    return view


def _check_answer_shapes(draft: GrammarExerciseDraft, answers: dict) -> None:
    """Each answer must belong to a real item and have that item's shape."""
    items = {item.id: item for item in draft.items}
    for item_id, answer in answers.items():
        item = items.get(item_id)
        if item is None:
            raise HTTPException(status_code=422, detail=f"unknown item {item_id!r}")
        if isinstance(item, FillBlankItem):
            ok = isinstance(answer, dict) and set(answer) <= {b.id for b in item.blanks}
        elif isinstance(item, ReorderItem):
            ok = isinstance(answer, list) and len(answer) <= len(item.chunks)
        else:
            ok = isinstance(answer, str)
        if not ok:
            raise HTTPException(status_code=422, detail=f"answer for {item_id!r} has the wrong shape")


# ---- teacher ----


@router.get("/taxonomy")
def taxonomy(user: CurrentUser = Depends(require_teacher)) -> list[dict]:
    """The 14 codes for the editor's concept picker, served from the one
    shared list rather than copied into the frontend."""
    return [{"code": code.value, "description": desc} for code, desc in CODE_DESCRIPTIONS.items()]


@router.post("/exercises/generate")
def generate_exercise(body: GenerateExerciseBody, user: CurrentUser = Depends(require_teacher)) -> dict:
    student = get_db().collection("students").document(body.student_id).get()
    if not student.exists or not student.get("active"):
        raise HTTPException(status_code=404, detail="student not found or inactive")

    # Context bundle (profile, notes, recent titles) is assembled in
    # Phase 7; until then the harness gets the teacher's description only.
    draft = _generate(body.student_id, body.description, note=None)

    doc_ref = get_db().collection("exercises").document()
    exercise = {
        "student_id": body.student_id,
        "kind": "grammar",
        "status": "draft",
        "title": draft.title,
        "items": draft.model_dump(mode="json")["items"],
        "teacher_request": body.description,
        "generation_history": [],
        "created_at": _now(),
    }
    doc_ref.set({**exercise, "items": _items_to_firestore(exercise["items"])})
    return _teacher_view(doc_ref.id, exercise)


@router.get("/exercises")
def list_exercises(student_id: str, user: CurrentUser = Depends(require_teacher)) -> list[dict]:
    docs = get_db().collection("exercises").where(filter=FieldFilter("student_id", "==", student_id)).stream()
    summaries = []
    for doc in docs:
        submission = _load_submission(doc.id) or {}
        summaries.append(
            {
                "exercise_id": doc.id,
                "title": doc.get("title"),
                "status": doc.get("status"),
                "state": submission.get("state", "draft"),
            }
        )
    return summaries


@router.put("/exercises/{exercise_id}")
def edit_exercise(
    exercise_id: str, body: GrammarExerciseDraft, user: CurrentUser = Depends(require_teacher)
) -> dict:
    """The teacher's direct edits (FR-9). The body is parsed with the same
    shared schema the harness output must pass, so an edit can't create
    an exercise the student screen or the grader can't handle."""
    exercise = _load_exercise(exercise_id)
    if exercise["status"] != "draft":
        raise HTTPException(status_code=409, detail="assigned exercises can't be edited")
    exercise["title"] = body.title
    exercise["items"] = body.model_dump(mode="json")["items"]
    _exercise_ref(exercise_id).update(
        {"title": exercise["title"], "items": _items_to_firestore(exercise["items"])}
    )
    return _teacher_view(exercise_id, exercise)


@router.post("/exercises/{exercise_id}/regenerate")
def regenerate_exercise(
    exercise_id: str, body: RegenerateBody, user: CurrentUser = Depends(require_teacher)
) -> dict:
    exercise = _load_exercise(exercise_id)
    if exercise["status"] != "draft":
        raise HTTPException(status_code=409, detail="assigned exercises can't be regenerated")

    draft = _generate(exercise["student_id"], exercise["teacher_request"], note=body.note)

    # Keep the version being replaced, with the note that replaced it.
    history = exercise.get("generation_history", []) + [
        {
            "title": exercise["title"],
            "items": _items_to_firestore(exercise["items"]),
            "note": body.note,
            "replaced_at": _now(),
        }
    ]
    exercise.update(
        {"title": draft.title, "items": draft.model_dump(mode="json")["items"], "generation_history": history}
    )
    _exercise_ref(exercise_id).update(
        {
            "title": exercise["title"],
            "items": _items_to_firestore(exercise["items"]),
            "generation_history": history,
        }
    )
    return _teacher_view(exercise_id, exercise)


@router.post("/exercises/{exercise_id}/assign")
def assign_exercise(exercise_id: str, body: AssignBody, user: CurrentUser = Depends(require_teacher)) -> dict:
    exercise = _load_exercise(exercise_id)
    if exercise["status"] != "draft":
        raise HTTPException(status_code=409, detail="already assigned")
    if not body.answers_and_concepts_checked:
        raise HTTPException(status_code=422, detail="check every answer key and concept code before assigning")

    exercise["status"] = "assigned"
    _exercise_ref(exercise_id).update({"status": "assigned", "assigned_at": _now()})
    _submission_ref(exercise_id).set(
        {
            "exercise_id": exercise_id,
            "student_id": exercise["student_id"],
            "state": "assigned",
            "answers": {},
            "grades": {},
            "updated_at": _now(),
        }
    )
    return _teacher_view(exercise_id, exercise)


@router.post("/exercises/{exercise_id}/release")
def release_results(exercise_id: str, user: CurrentUser = Depends(require_teacher)) -> dict:
    exercise = _load_exercise(exercise_id)
    submission = _load_submission(exercise_id)
    if submission is None or submission["state"] != "ready_to_release":
        raise HTTPException(status_code=409, detail="not ready to release")
    _submission_ref(exercise_id).update({"state": "released", "released_at": _now()})
    return _teacher_view(exercise_id, exercise)


@router.post("/exercises/{exercise_id}/reopen")
def reopen_submission(exercise_id: str, user: CurrentUser = Depends(require_teacher)) -> dict:
    """Sends a submitted exercise back to the student (FR-15). Audit-logged."""
    exercise = _load_exercise(exercise_id)
    submission = _load_submission(exercise_id)
    if submission is None or submission["state"] not in _REOPENABLE_STATES:
        raise HTTPException(status_code=409, detail="only submitted, unreleased work can be reopened")
    # Answers are kept so the student continues where they left off.
    _submission_ref(exercise_id).update({"state": "in_progress", "grades": {}, "updated_at": _now()})
    record_audit(user.uid, "reopen_submission", target=exercise_id)
    return _teacher_view(exercise_id, exercise)


# ---- student (and teacher, for GET) ----


@router.get("/me/exercises", response_model=list[StudentExerciseSummary])
def my_exercises(user: CurrentUser = Depends(get_current_user)) -> list[StudentExerciseSummary]:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="students only")
    docs = (
        get_db()
        .collection("exercises")
        .where(filter=FieldFilter("student_id", "==", user.student_id))
        .where(filter=FieldFilter("status", "==", "assigned"))
        .stream()
    )
    return [
        StudentExerciseSummary(
            exercise_id=doc.id,
            title=doc.get("title"),
            state=(_load_submission(doc.id) or {}).get("state", "assigned"),
        )
        for doc in docs
    ]


@router.get("/exercises/{exercise_id}")
def get_exercise(exercise_id: str, user: CurrentUser = Depends(get_current_user)) -> dict:
    if user.role == "teacher":
        return _teacher_view(exercise_id, _load_exercise(exercise_id))

    exercise = _load_for_student(exercise_id, user)
    submission = _load_submission(exercise_id) or {}
    state = submission.get("state", "assigned")
    released = state == "released"
    draft = _draft(exercise)
    answers = submission.get("answers", {})
    grades = submission.get("grades", {})
    view = StudentExerciseView(
        exercise_id=exercise_id,
        title=exercise["title"],
        state=state,
        answers=answers,
        items=[_student_item(item, released, grades) for item in draft.items],
    )
    # Serialized through the model, so only the fields it declares go out.
    return view.model_dump(mode="json", exclude_none=True)


@router.put("/exercises/{exercise_id}/answers")
def save_answers(exercise_id: str, body: AnswersBody, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Autosave (FR-13). Replaces the saved answers with the ones sent."""
    if user.role != "student":
        raise HTTPException(status_code=403, detail="students only")
    exercise = _load_for_student(exercise_id, user)
    _update_open_submission(
        exercise_id,
        check=lambda: _check_answer_shapes(_draft(exercise), body.answers),
        changes={"answers": body.answers, "state": "in_progress", "updated_at": _now()},
    )
    return {"status": "saved"}


@router.post("/exercises/{exercise_id}/submit")
def submit_answers(exercise_id: str, body: AnswersBody, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Final submit (FR-15/FR-16). Takes the answers once more so nothing
    typed after the last autosave is lost, then grades and locks."""
    if user.role != "student":
        raise HTTPException(status_code=403, detail="students only")
    exercise = _load_for_student(exercise_id, user)
    draft = _draft(exercise)
    has_short_answers = any(isinstance(item, ShortAnswerItem) for item in draft.items)
    _update_open_submission(
        exercise_id,
        check=lambda: _check_answer_shapes(draft, body.answers),
        changes={
            "answers": body.answers,
            "grades": grade_items(draft.items, body.answers),
            # FR-17: no short answers means no scrub or evaluation step.
            "state": "scrub_review" if has_short_answers else "ready_to_release",
            "submitted_at": _now(),
            "updated_at": _now(),
        },
    )
    return {"status": "submitted"}
