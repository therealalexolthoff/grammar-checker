"""Writing lessons (docs/REQUIREMENTS.md FR-28, FR-29; BUILD_PLAN Phase 7).

A lesson is a short, read-only teaching passage for one student: an
explanation plus a few worked examples, answers shown. Not an exercise -
nothing to answer, nothing evaluated.

Teacher: describe it and generate a draft (the harness gets the context
bundle - see context.py), edit it, regenerate with a note, assign it.
Assigned lessons are frozen. Student: list their assigned lessons, read
one, press "Mark as read" (shown on the class overview).

Firestore: lessons/{id} with status "draft" or "assigned", and read_at
once the student marks it read.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from google.cloud.firestore_v1.base_query import FieldFilter

from shared.schemas import PROMPT_VERSION, GenerateLessonRequest, LessonDraft

from .auth import CurrentUser, get_current_user, require_teacher
from .context import build_context
from .exercises import call_ai
from .firestore_client import get_db
from .models import (
    GenerateLessonBody,
    LessonEditBody,
    RegenerateBody,
    StudentLessonSummary,
    StudentLessonView,
)

router = APIRouter(tags=["lessons"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _lesson_ref(lesson_id: str):
    return get_db().collection("lessons").document(lesson_id)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="lesson not found")


def _load(lesson_id: str) -> dict:
    doc = _lesson_ref(lesson_id).get()
    if not doc.exists:
        raise _not_found()
    return doc.to_dict()


def _load_draft(lesson_id: str) -> dict:
    lesson = _load(lesson_id)
    if lesson["status"] != "draft":
        raise HTTPException(status_code=409, detail="assigned lessons can't be changed")
    return lesson


def _word_count(explanation: str, examples: list[dict]) -> int:
    text = " ".join([explanation] + [f"{e['incorrect']} {e['correct']} {e['note']}" for e in examples])
    return len(text.split())


def _teacher_view(lesson_id: str, lesson: dict) -> dict:
    return {
        "lesson_id": lesson_id,
        "student_id": lesson["student_id"],
        "status": lesson["status"],
        "request": lesson["request"],
        "title": lesson["title"],
        "explanation": lesson["explanation"],
        "examples": lesson["examples"],
        "word_count": lesson["word_count"],
        "read_at": lesson.get("read_at"),
    }


def _generate(student_id: str, description: str, note: str | None) -> dict:
    """One generate_lesson harness call; returns the lesson fields."""
    req = GenerateLessonRequest(
        student_id=student_id,
        request_id=str(uuid.uuid4()),
        prompt_version=PROMPT_VERSION,
        description=description,
        context=build_context(student_id),
        regenerate_note=note or None,
    )
    result, _ = call_ai("generate_lesson", req)
    if not isinstance(result, LessonDraft):
        raise HTTPException(status_code=502, detail="The AI result could not be used. Please try again.")
    return result.model_dump(mode="json")


# ---- teacher ----


@router.post("/lessons/generate")
def generate_lesson(body: GenerateLessonBody, user: CurrentUser = Depends(require_teacher)) -> dict:
    student = get_db().collection("students").document(body.student_id).get()
    if not student.exists or not student.get("active"):
        raise HTTPException(status_code=404, detail="student not found or inactive")
    fields = _generate(body.student_id, body.description, note=None)
    doc_ref = get_db().collection("lessons").document()
    lesson = {
        "student_id": body.student_id,
        "status": "draft",
        "request": body.description,
        **fields,
        "generation_history": [],
        "created_at": _now(),
    }
    doc_ref.set(lesson)
    return _teacher_view(doc_ref.id, lesson)


@router.get("/lessons")
def list_lessons(student_id: str, user: CurrentUser = Depends(require_teacher)) -> list[dict]:
    docs = get_db().collection("lessons").where(filter=FieldFilter("student_id", "==", student_id)).stream()
    lessons = sorted(((doc.id, doc.to_dict()) for doc in docs), key=lambda pair: pair[1]["created_at"], reverse=True)
    return [
        {"lesson_id": lesson_id, "title": l["title"], "status": l["status"], "read_at": l.get("read_at")}
        for lesson_id, l in lessons
    ]


@router.put("/lessons/{lesson_id}")
def edit_lesson(lesson_id: str, body: LessonEditBody, user: CurrentUser = Depends(require_teacher)) -> dict:
    lesson = _load_draft(lesson_id)
    fields = body.model_dump(mode="json")
    fields["word_count"] = _word_count(fields["explanation"], fields["examples"])
    lesson.update(fields)
    _lesson_ref(lesson_id).update(fields)
    return _teacher_view(lesson_id, lesson)


@router.post("/lessons/{lesson_id}/regenerate")
def regenerate_lesson(lesson_id: str, body: RegenerateBody, user: CurrentUser = Depends(require_teacher)) -> dict:
    lesson = _load_draft(lesson_id)
    fields = _generate(lesson["student_id"], lesson["request"], note=body.note)
    # Keep the version being replaced, with the note that replaced it.
    replaced = {key: lesson[key] for key in ("title", "explanation", "examples", "word_count")}
    history = lesson.get("generation_history", []) + [{**replaced, "note": body.note, "replaced_at": _now()}]
    lesson.update({**fields, "generation_history": history})
    _lesson_ref(lesson_id).update({**fields, "generation_history": history})
    return _teacher_view(lesson_id, lesson)


@router.post("/lessons/{lesson_id}/assign")
def assign_lesson(lesson_id: str, user: CurrentUser = Depends(require_teacher)) -> dict:
    lesson = _load_draft(lesson_id)
    lesson.update({"status": "assigned", "assigned_at": _now()})
    _lesson_ref(lesson_id).update({"status": "assigned", "assigned_at": lesson["assigned_at"]})
    return _teacher_view(lesson_id, lesson)


# ---- student (and teacher, for GET) ----


@router.get("/me/lessons", response_model=list[StudentLessonSummary])
def my_lessons(user: CurrentUser = Depends(get_current_user)) -> list[StudentLessonSummary]:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="students only")
    docs = (
        get_db()
        .collection("lessons")
        .where(filter=FieldFilter("student_id", "==", user.student_id))
        .where(filter=FieldFilter("status", "==", "assigned"))
        .stream()
    )
    lessons = sorted((doc for doc in docs), key=lambda doc: doc.get("assigned_at"), reverse=True)
    return [
        StudentLessonSummary(lesson_id=doc.id, title=doc.get("title"), read=doc.get("read_at") is not None)
        for doc in lessons
    ]


def _load_for_student(lesson_id: str, user: CurrentUser) -> dict:
    """Only the student's own assigned lessons; anything else looks like
    "not found", so a student can't probe which lesson ids exist."""
    lesson = _load(lesson_id)
    if lesson["student_id"] != user.student_id or lesson["status"] != "assigned":
        raise _not_found()
    return lesson


@router.get("/lessons/{lesson_id}")
def get_lesson(lesson_id: str, user: CurrentUser = Depends(get_current_user)) -> dict:
    if user.role == "teacher":
        return _teacher_view(lesson_id, _load(lesson_id))
    lesson = _load_for_student(lesson_id, user)
    view = StudentLessonView(
        lesson_id=lesson_id,
        title=lesson["title"],
        explanation=lesson["explanation"],
        examples=lesson["examples"],
        read=lesson.get("read_at") is not None,
    )
    return view.model_dump(mode="json")


@router.post("/lessons/{lesson_id}/read")
def mark_read(lesson_id: str, user: CurrentUser = Depends(get_current_user)) -> dict:
    """The student's "Mark as read" (FR-29). Only the first time counts."""
    if user.role != "student":
        raise HTTPException(status_code=403, detail="students only")
    lesson = _load_for_student(lesson_id, user)
    if lesson.get("read_at") is None:
        _lesson_ref(lesson_id).update({"read_at": _now()})
    return {"status": "read"}
