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
    return db


@pytest.fixture
def as_teacher(monkeypatch):
    monkeypatch.setattr(
        "api.app.identity.verify_id_token",
        lambda token: {"uid": "teacher-1", "role": "teacher"},
    )


def as_student(monkeypatch, student_id, uid="student-uid-1"):
    """Not a fixture - tests call this directly because the student_id varies."""
    monkeypatch.setattr(
        "api.app.identity.verify_id_token",
        lambda token: {"uid": uid, "role": "student", "student_id": student_id},
    )
