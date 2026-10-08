"""Student account lifecycle: create, deactivate, reset password, delete.

Only the teacher may call these - see docs/REQUIREMENTS.md FR-1/FR-3/FR-4.
Deletion requires the caller to pass the student's exact username as
confirmation (the UI-level "type the username to confirm" from FR-4,
enforced here too, not just in the React screen). Every lifecycle change
is audit-logged, per docs/REQUIREMENTS.md FR-5 as extended by the teacher:
account creation and deactivation are audited too, not just deletion and
password reset.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from . import identity
from .audit import record as record_audit
from .auth import CurrentUser, require_self_or_teacher, require_teacher
from .firestore_client import get_db
from .profile import student_profile
from .models import (
    DeleteStudentRequest,
    NotesBody,
    ResetPasswordRequest,
    StudentCreateRequest,
    StudentPublic,
)

router = APIRouter(prefix="/students", tags=["students"])


def _student_doc(student_id: str):
    return get_db().collection("students").document(student_id)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="student not found")


@router.post("", response_model=StudentPublic)
def create_student(
    body: StudentCreateRequest, user: CurrentUser = Depends(require_teacher)
) -> StudentPublic:
    doc_ref = get_db().collection("students").document()
    uid = identity.create_student_user(body.username, body.password)
    identity.set_student_claims(uid, doc_ref.id)
    doc_ref.set(
        {
            "username": body.username,
            "auth_uid": uid,
            "active": True,
            "teacher_notes": "",
            "created_at": datetime.now(timezone.utc),
        }
    )
    record_audit(user.uid, "create_student", target=doc_ref.id)
    return StudentPublic(student_id=doc_ref.id, username=body.username, active=True)


@router.get("", response_model=list[StudentPublic])
def list_students(user: CurrentUser = Depends(require_teacher)) -> list[StudentPublic]:
    docs = get_db().collection("students").stream()
    return [
        StudentPublic(student_id=doc.id, username=doc.get("username"), active=doc.get("active"))
        for doc in docs
    ]


@router.get("/{student_id}", response_model=StudentPublic)
def get_student(
    student_id: str, user: CurrentUser = Depends(require_self_or_teacher)
) -> StudentPublic:
    doc = _student_doc(student_id).get()
    if not doc.exists:
        raise _not_found()
    return StudentPublic(student_id=doc.id, username=doc.get("username"), active=doc.get("active"))


@router.get("/{student_id}/profile")
def get_profile(student_id: str, user: CurrentUser = Depends(require_teacher)) -> dict:
    """The learner profile (FR-30) and the teacher's private notes (FR-31).
    Teacher only: students never see either."""
    doc = _student_doc(student_id).get()
    if not doc.exists:
        raise _not_found()
    return {"profile": student_profile(student_id), "teacher_notes": doc.get("teacher_notes") or ""}


@router.put("/{student_id}/notes")
def save_notes(student_id: str, body: NotesBody, user: CurrentUser = Depends(require_teacher)) -> dict:
    """The teacher's notes. They are sent to the AI provider with
    generation requests (under the opaque id - see context.py), which the
    notes screen warns about."""
    doc_ref = _student_doc(student_id)
    if not doc_ref.get().exists:
        raise _not_found()
    doc_ref.update({"teacher_notes": body.teacher_notes})
    return {"status": "ok"}


@router.post("/{student_id}/deactivate", response_model=StudentPublic)
def deactivate_student(
    student_id: str, user: CurrentUser = Depends(require_teacher)
) -> StudentPublic:
    doc_ref = _student_doc(student_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise _not_found()
    identity.disable_user(doc.get("auth_uid"))
    doc_ref.update({"active": False})
    record_audit(user.uid, "deactivate_student", target=student_id)
    return StudentPublic(student_id=student_id, username=doc.get("username"), active=False)


@router.post("/{student_id}/reset-password")
def reset_password(
    student_id: str, body: ResetPasswordRequest, user: CurrentUser = Depends(require_teacher)
) -> dict:
    doc = _student_doc(student_id).get()
    if not doc.exists:
        raise _not_found()
    identity.reset_password(doc.get("auth_uid"), body.password)
    record_audit(user.uid, "reset_password", target=student_id)
    return {"status": "ok"}


@router.delete("/{student_id}")
def delete_student(
    student_id: str, body: DeleteStudentRequest, user: CurrentUser = Depends(require_teacher)
) -> dict:
    doc_ref = _student_doc(student_id)
    doc = doc_ref.get()
    if not doc.exists:
        raise _not_found()
    if body.confirm_username != doc.get("username"):
        raise HTTPException(status_code=400, detail="confirm_username does not match")

    identity.delete_user(doc.get("auth_uid"))
    doc_ref.delete()
    record_audit(user.uid, "delete_student", target=student_id)
    return {"status": "ok"}
