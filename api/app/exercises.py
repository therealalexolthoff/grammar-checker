"""Exercises, end to end: grammar (docs/BUILD_PLAN.md Phase 4) and
writing (Phase 6).

Teacher: generate a draft, edit it, regenerate with a note, assign it
(after the approval checklist), release results, reopen a submission.
Student: list assigned work, open it, autosave answers, submit.

Firestore layout (docs/ARCHITECTURE.md section 4):
- exercises/{id}:   the exercise itself; status "draft" (editable) or
                    "assigned" (frozen).
- submissions/{id}: the student's answers and grades, created on assign.
                    Same id as its exercise - every exercise belongs to
                    exactly one student, so there is one submission each.

Submission states (docs/ARCHITECTURE.md section 5):
    assigned -> in_progress -> ready_to_release -> released
                             \\-> scrub_review -> evaluating -> draft_ready
                                  -> ready_to_release   (has short answers,
                                                          or writing; see
                                                          review.py)
Writing exercises also have the handwriting and revision states - see
writing.py:
    ... -> transcribing -> transcript_review -> scrub_review
    ready_to_release -> revision_open -> revision_submitted -> revision_reviewed

A submission's "answers" are the student's original answers and are never
changed after submit. Short answers also get a separate "scrubbed_answers"
copy, which the teacher edits and which is the only student text ever sent
to the harness (docs/REQUIREMENTS.md FR-18). A writing response is stored
the same way, as the single answer WRITING_KEY.
"""

import uuid
from collections.abc import Callable
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
    WritingExerciseDraft,
)

from shared.taxonomy import CODE_DESCRIPTIONS, ErrorCode

from .audit import record as record_audit
from .auth import CurrentUser, get_current_user, require_teacher
from .context import build_context
from .firestore_client import get_db
from .grading import grade_items
from .harness_ops import HarnessValidationFailed, SpendCapReached, call_harness
from .revision import revision_view
from .models import (
    AnswersBody,
    AssignBody,
    ExerciseDraft,
    GenerateExerciseBody,
    RegenerateBody,
    StudentExerciseSummary,
    StudentExerciseView,
    StudentItemView,
    SpanView,
    WRITING_KEY,
    WritingForStudentsBody,
)

router = APIRouter(tags=["exercises"])

# States in which the student may still change answers.
OPEN_STATES = ("assigned", "in_progress")
# States the teacher may reopen from. Not "released": once the student has
# seen results, reopening would let them re-answer with the key in view.
# Not "evaluating" or "transcribing": an AI call is in progress.
_REOPENABLE_STATES = ("transcript_review", "scrub_review", "draft_ready", "ready_to_release")
# States in which the student sees results (the last three: writing only).
RESULTS_STATES = ("released", "revision_open", "revision_submitted", "revision_reviewed")


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


def _to_firestore(fields: dict) -> dict:
    """Exercise fields in the form they're stored (see _items_to_firestore)."""
    if "items" in fields:
        return {**fields, "items": _items_to_firestore(fields["items"])}
    return fields


def _load_exercise(exercise_id: str) -> dict:
    doc = _exercise_ref(exercise_id).get()
    if not doc.exists:
        raise _not_found()
    exercise = doc.to_dict()
    if exercise["kind"] == "grammar":
        exercise["items"] = _items_from_firestore(exercise["items"])
    return exercise


def _load_submission(exercise_id: str) -> dict | None:
    doc = _submission_ref(exercise_id).get()
    return doc.to_dict() if doc.exists else None


def update_open_submission(exercise_id: str, check, changes: dict | Callable[[dict], dict], open_states=OPEN_STATES) -> None:
    """Applies `changes` to a submission the student can still edit (one
    of `open_states`).

    Read, check and write would race otherwise: an autosave already on its
    way when the student taps Submit could read "in_progress", lose the
    race, and then write "in_progress" back over the submit - unlocking
    work that must stay locked (FR-15). So the write only goes through if
    the document is unchanged since it was read; if something else wrote
    in between, read again and re-check. `check` runs between the read
    and the write (answer-shape validation). `changes` may also be a
    function of the submission just read, for changes that build on it
    (e.g. adding a photo page to the list).
    """
    ref = _submission_ref(exercise_id)
    for _ in range(3):
        snapshot = ref.get()
        if not snapshot.exists or snapshot.get("state") not in open_states:
            raise HTTPException(status_code=409, detail="This exercise has already been submitted.")
        check()
        new = changes(snapshot.to_dict()) if callable(changes) else changes
        try:
            ref.update(new, option=get_db().write_option(last_update_time=snapshot.update_time))
            return
        except FailedPrecondition:
            continue  # someone else wrote first; look again
    raise HTTPException(status_code=409, detail="Your answers could not be saved. Please try again.")


def _draft(exercise: dict) -> GrammarExerciseDraft | WritingExerciseDraft:
    """Re-parses a stored exercise into its typed schema object."""
    if exercise["kind"] == "writing":
        return WritingExerciseDraft(
            title=exercise["title"],
            prompt=exercise["prompt"],
            min_words=exercise["min_words"],
            max_words=exercise["max_words"],
        )
    return GrammarExerciseDraft(title=exercise["title"], items=exercise["items"])


def load_for_student(exercise_id: str, user: CurrentUser) -> dict:
    """The student may only see their own exercises, and only once
    assigned. Anything else looks like "not found" so a student can't
    probe which exercise ids exist."""
    exercise = _load_exercise(exercise_id)
    if exercise["student_id"] != user.student_id or exercise["status"] != "assigned":
        raise _not_found()
    return exercise


def call_ai(operation: str, req) -> tuple[object, str]:
    """One harness call, with failures turned into teacher-readable errors.
    Invalid output is never returned (FR-8). Returns (result, job id)."""
    try:
        return call_harness(operation, req)
    except SpendCapReached as exc:
        raise HTTPException(status_code=409, detail=f"{exc}. AI generation and evaluation are paused.") from exc
    except HarnessValidationFailed as exc:
        raise HTTPException(
            status_code=502, detail="The AI result could not be used. Nothing was changed - please try again."
        ) from exc


def _generate(student_id: str, kind: str, description: str, note: str | None) -> GrammarExerciseDraft | WritingExerciseDraft:
    """One generate_exercise harness call."""
    req = GenerateExerciseRequest(
        student_id=student_id,
        request_id=str(uuid.uuid4()),
        prompt_version=PROMPT_VERSION,
        kind=kind,
        description=description,
        context=build_context(student_id),
        regenerate_note=note or None,
    )
    result, _ = call_ai("generate_exercise", req)
    if result.kind != kind:
        raise HTTPException(
            status_code=502, detail="The AI returned the wrong kind of exercise. Please try again."
        )
    return result


def _teacher_view(exercise_id: str, exercise: dict) -> dict:
    """Everything, including answer keys and the student's answers."""
    submission = _load_submission(exercise_id) or {}
    view = {
        "exercise_id": exercise_id,
        "student_id": exercise["student_id"],
        "kind": exercise["kind"],
        "status": exercise["status"],
        "title": exercise["title"],
        "items": exercise.get("items", []),
        "teacher_request": exercise["teacher_request"],
        "state": submission.get("state", "draft"),
        "answers": submission.get("answers", {}),
        "grades": submission.get("grades", {}),
        # Short answers and writing: see review.py.
        "scrubbed_answers": submission.get("scrubbed_answers", {}),
        "evaluation": submission.get("evaluation"),
        "evaluation_valid": submission.get("evaluation_valid", False),
    }
    if exercise["kind"] == "writing":
        # Handwriting and revision: see writing.py. Photos themselves come
        # from GET /exercises/{id}/photos as short-lived links.
        view.update(
            {
                "prompt": exercise["prompt"],
                "min_words": exercise["min_words"],
                "max_words": exercise["max_words"],
                "photo_count": len(submission.get("photos", [])),
                "transcription": submission.get("transcription"),
                "final_source": submission.get("final_source"),
                "revision": revision_view(submission),
            }
        )
    return view


def _student_spans(annotations: list[dict]) -> list[SpanView]:
    """Error spans as a student may see them: position and code only,
    never the correction or explanation (FR-21). Kept in annotation order,
    which is how revision edits refer to them."""
    return [
        SpanView(start=a["start"], end=a["end"], code=a["code"], meaning=CODE_DESCRIPTIONS[ErrorCode(a["code"])])
        for a in annotations
    ]


def _student_writing_view(exercise_id: str, exercise: dict, submission: dict) -> StudentExerciseView:
    """A writing exercise for its student: the prompt and word limits, and
    once released, their evaluated text with coded spans, the overall
    comment (FR-21), and their revision (FR-26). Never the photos, the
    transcription, corrections or explanations (FR-25) - except that once
    the teacher sends back the checked revision, each changed span's
    outcome, and the correction for each one not fixed (FR-27)."""
    state = submission.get("state", "assigned")
    view = StudentExerciseView(
        exercise_id=exercise_id,
        kind="writing",
        title=exercise["title"],
        state=state,
        answers=submission.get("answers", {}),
        items=[],
        prompt=exercise["prompt"],
        min_words=exercise["min_words"],
        max_words=exercise["max_words"],
    )
    if state in RESULTS_STATES:
        evaluation = submission["evaluation"]
        # The evaluated (scrubbed) text, which the spans point into.
        view.answer_text = submission["scrubbed_answers"][WRITING_KEY]
        view.spans = _student_spans(evaluation["annotations"])
        view.comment = evaluation["comment"]
        revision = revision_view(submission)
        if revision is not None:
            view.revision_edits = revision["edits"]
            view.revised_text = revision["revised_text"]
            if state == "revision_reviewed":
                view.outcomes = revision["outcomes"]
                view.corrections = {
                    index: evaluation["annotations"][int(index)]["correction"]
                    for index, outcome in revision["outcomes"].items()
                    if outcome != "fixed"
                }
    return view


def _student_item(item, released: bool, grades: dict, evaluation: dict | None, scrubbed: dict) -> StudentItemView:
    if isinstance(item, FillBlankItem):
        view = StudentItemView(
            id=item.id, type=item.type, text=item.text, blank_ids=[b.id for b in item.blanks]
        )
    elif isinstance(item, ReorderItem):
        view = StudentItemView(id=item.id, type=item.type, chunks=item.chunks)
    else:
        view = StudentItemView(id=item.id, type=item.type, prompt=item.prompt)

    # Results only after release (FR-16: students see nothing until then).
    if released and isinstance(item, ShortAnswerItem):
        # FR-21: the mark, the feedback sentence, and the answer with its
        # error spans marked by code only - corrections and explanations
        # are teacher-only. Spans are offsets into the scrubbed text (the
        # text that was evaluated), so that is the text shown here.
        result = next((r for r in (evaluation or {}).get("items", []) if r["item_id"] == item.id), None)
        if result is not None:
            view.mark = result["mark"]
            view.feedback = result["feedback"]
            view.answer_text = scrubbed.get(item.id, "")
            view.spans = _student_spans(result["annotations"])
    elif released:
        view.correct = grades.get(item.id, False)
        view.explanation = item.explanation
        if not view.correct:  # FR-21: show the correct answer for wrong items
            if isinstance(item, FillBlankItem):
                view.correct_answer = {b.id: b.accepted[0] for b in item.blanks}
            else:
                view.correct_answer = item.accepted_orders[0]
    return view


def _check_answer_shapes(draft: GrammarExerciseDraft | WritingExerciseDraft, answers: dict) -> None:
    """Each answer must belong to a real item and have that item's shape.
    A writing exercise has one answer: the response text."""
    if isinstance(draft, WritingExerciseDraft):
        if set(answers) - {WRITING_KEY} or not isinstance(answers.get(WRITING_KEY, ""), str):
            raise HTTPException(status_code=422, detail=f"a writing answer is just {{{WRITING_KEY!r}: text}}")
        return
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

    draft = _generate(body.student_id, body.kind, body.description, note=None)

    doc_ref = get_db().collection("exercises").document()
    exercise = {
        "student_id": body.student_id,
        "status": "draft",
        **draft.model_dump(mode="json"),  # kind, title, and items or prompt
        "teacher_request": body.description,
        "generation_history": [],
        "created_at": _now(),
    }
    doc_ref.set(_to_firestore(exercise))
    return _teacher_view(doc_ref.id, exercise)


@router.post("/exercises/writing-for-students")
def assign_writing_to_students(body: WritingForStudentsBody, user: CurrentUser = Depends(require_teacher)) -> dict:
    """A writing exercise the teacher wrote, assigned straight away to each
    chosen student (teacher decision 2026-10-14). There's no AI draft, so
    nothing to check before assigning. Each student gets their own copy,
    which then works like any other writing exercise (FR-10). Either every
    copy is created or none is."""
    draft = body.draft
    if not draft.title.strip() or not draft.prompt.strip():
        raise HTTPException(status_code=422, detail="Give the exercise a title and a prompt.")
    student_ids = list(dict.fromkeys(body.student_ids))  # each student once, in the order picked
    for student_id in student_ids:
        student = get_db().collection("students").document(student_id).get()
        if not student.exists or not student.get("active"):
            raise HTTPException(status_code=404, detail="A chosen student was not found or is inactive.")

    count = len(student_ids)
    batch = get_db().batch()
    exercise_ids = []
    for student_id in student_ids:
        ref = get_db().collection("exercises").document()
        exercise = {
            "student_id": student_id,
            "status": "assigned",
            **draft.model_dump(mode="json"),  # kind, title, prompt, word limits
            "teacher_request": f"Written by you, for {count} student{'s' if count > 1 else ''}.",
            "generation_history": [],
            "created_at": _now(),
            "assigned_at": _now(),
        }
        batch.set(ref, exercise)
        batch.set(_submission_ref(ref.id), _new_submission(ref.id, student_id))
        exercise_ids.append(ref.id)
    batch.commit()
    return {"exercise_ids": exercise_ids}


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
def edit_exercise(exercise_id: str, body: ExerciseDraft, user: CurrentUser = Depends(require_teacher)) -> dict:
    """The teacher's direct edits (FR-9). The body is parsed with the same
    shared schema the harness output must pass, so an edit can't create
    an exercise the student screen or the grader can't handle."""
    exercise = _load_exercise(exercise_id)
    if exercise["status"] != "draft":
        raise HTTPException(status_code=409, detail="assigned exercises can't be edited")
    if body.kind != exercise["kind"]:
        raise HTTPException(status_code=422, detail=f"this is a {exercise['kind']} exercise")
    fields = body.model_dump(mode="json")
    exercise.update(fields)
    _exercise_ref(exercise_id).update(_to_firestore(fields))
    return _teacher_view(exercise_id, exercise)


@router.post("/exercises/{exercise_id}/regenerate")
def regenerate_exercise(
    exercise_id: str, body: RegenerateBody, user: CurrentUser = Depends(require_teacher)
) -> dict:
    exercise = _load_exercise(exercise_id)
    if exercise["status"] != "draft":
        raise HTTPException(status_code=409, detail="assigned exercises can't be regenerated")

    draft = _generate(exercise["student_id"], exercise["kind"], exercise["teacher_request"], note=body.note)

    # Keep the version being replaced, with the note that replaced it.
    replaced = _to_firestore(_draft(exercise).model_dump(mode="json"))
    history = exercise.get("generation_history", []) + [{**replaced, "note": body.note, "replaced_at": _now()}]
    fields = draft.model_dump(mode="json")
    exercise.update({**fields, "generation_history": history})
    _exercise_ref(exercise_id).update({**_to_firestore(fields), "generation_history": history})
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
    _submission_ref(exercise_id).set(_new_submission(exercise_id, exercise["student_id"]))
    return _teacher_view(exercise_id, exercise)


def _new_submission(exercise_id: str, student_id: str) -> dict:
    """The student's empty submission, created when an exercise is assigned."""
    return {
        "exercise_id": exercise_id,
        "student_id": student_id,
        "state": "assigned",
        "answers": {},
        "grades": {},
        "updated_at": _now(),
    }


@router.post("/exercises/{exercise_id}/release")
def release_results(exercise_id: str, user: CurrentUser = Depends(require_teacher)) -> dict:
    exercise = _load_exercise(exercise_id)
    submission = _load_submission(exercise_id)
    if submission is None or submission["state"] != "ready_to_release":
        raise HTTPException(status_code=409, detail="not ready to release")
    # Writing with flagged errors opens the student's one revision round
    # straight away (FR-26). Nothing flagged means nothing to revise.
    revisable = exercise["kind"] == "writing" and submission["evaluation"]["annotations"]
    state = "revision_open" if revisable else "released"
    _submission_ref(exercise_id).update({"state": state, "released_at": _now()})
    return _teacher_view(exercise_id, exercise)


@router.post("/exercises/{exercise_id}/reopen")
def reopen_submission(exercise_id: str, user: CurrentUser = Depends(require_teacher)) -> dict:
    """Sends a submitted exercise back to the student (FR-15). Audit-logged."""
    exercise = _load_exercise(exercise_id)
    submission = _load_submission(exercise_id)
    if submission is None or submission["state"] not in _REOPENABLE_STATES:
        raise HTTPException(status_code=409, detail="only submitted, unreleased work can be reopened")
    # Answers are kept so the student continues where they left off. Grades,
    # the scrubbed copy and any evaluation are rebuilt after the next submit.
    # Handwriting photos and their transcription are the teacher's work and
    # are kept too; the final source is chosen again.
    _submission_ref(exercise_id).update(
        {
            "state": "in_progress",
            "grades": {},
            "scrubbed_answers": {},
            "final_source": None,
            "evaluation": None,
            "evaluation_ai": None,
            "evaluation_valid": False,
            "updated_at": _now(),
        }
    )
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

    exercise = load_for_student(exercise_id, user)
    submission = _load_submission(exercise_id) or {}
    if exercise["kind"] == "writing":
        view = _student_writing_view(exercise_id, exercise, submission)
        return view.model_dump(mode="json", exclude_none=True)

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
        items=[
            _student_item(
                item, released, grades, submission.get("evaluation"), submission.get("scrubbed_answers", {})
            )
            for item in draft.items
        ],
    )
    # Serialized through the model, so only the fields it declares go out.
    return view.model_dump(mode="json", exclude_none=True)


@router.put("/exercises/{exercise_id}/answers")
def save_answers(exercise_id: str, body: AnswersBody, user: CurrentUser = Depends(get_current_user)) -> dict:
    """Autosave (FR-13). Replaces the saved answers with the ones sent."""
    if user.role != "student":
        raise HTTPException(status_code=403, detail="students only")
    exercise = load_for_student(exercise_id, user)
    update_open_submission(
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
    exercise = load_for_student(exercise_id, user)
    draft = _draft(exercise)
    if isinstance(draft, WritingExerciseDraft):
        update_open_submission(
            exercise_id,
            check=lambda: _check_answer_shapes(draft, body.answers),
            changes={
                "answers": body.answers,
                # The teacher's editable copy starts as the original (FR-18).
                "scrubbed_answers": {WRITING_KEY: body.answers.get(WRITING_KEY, "")},
                "final_source": "typed",
                "state": "scrub_review",
                "submitted_at": _now(),
                "updated_at": _now(),
            },
        )
        return {"status": "submitted"}

    short_answer_ids = [item.id for item in draft.items if isinstance(item, ShortAnswerItem)]
    update_open_submission(
        exercise_id,
        check=lambda: _check_answer_shapes(draft, body.answers),
        changes={
            "answers": body.answers,
            "grades": grade_items(draft.items, body.answers),
            # The teacher's editable copy starts as the original (FR-18).
            "scrubbed_answers": {item_id: body.answers.get(item_id, "") for item_id in short_answer_ids},
            # FR-17: no short answers means no scrub or evaluation step.
            "state": "scrub_review" if short_answer_ids else "ready_to_release",
            "submitted_at": _now(),
            "updated_at": _now(),
        },
    )
    return {"status": "submitted"}
