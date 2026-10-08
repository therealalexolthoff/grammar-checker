import pytest

from .fakes import FakeFirestore


@pytest.fixture
def fake_db(monkeypatch):
    db = FakeFirestore()
    monkeypatch.setattr("api.app.students.get_db", lambda: db)
    monkeypatch.setattr("api.app.audit.get_db", lambda: db)
    monkeypatch.setattr("api.app.jobs.get_db", lambda: db)
    monkeypatch.setattr("api.app.spend.get_db", lambda: db)
    monkeypatch.setattr("api.app.settings.get_db", lambda: db)
    monkeypatch.setattr("api.app.exercises.get_db", lambda: db)
    monkeypatch.setattr("api.app.profile.get_db", lambda: db)
    monkeypatch.setattr("api.app.context.get_db", lambda: db)
    monkeypatch.setattr("api.app.lessons.get_db", lambda: db)
    monkeypatch.setattr("api.app.overview.get_db", lambda: db)
    return db


def become_teacher(monkeypatch):
    """Signed in as the teacher, with the TOTP second factor. Tests that
    switch between student and teacher call this directly."""
    monkeypatch.setattr(
        "api.app.identity.verify_id_token",
        lambda token: {"uid": "teacher-1", "role": "teacher", "firebase": {"sign_in_second_factor": "totp"}},
    )


@pytest.fixture
def as_teacher(monkeypatch):
    become_teacher(monkeypatch)


def as_student(monkeypatch, student_id, uid="student-uid-1"):
    """Not a fixture - tests call this directly because the student_id varies."""
    monkeypatch.setattr(
        "api.app.identity.verify_id_token",
        lambda token: {"uid": uid, "role": "student", "student_id": student_id},
    )
