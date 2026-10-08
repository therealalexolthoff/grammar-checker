from fastapi.testclient import TestClient

from api.app.main import app

from .conftest import as_student

client = TestClient(app)
AUTH = {"Authorization": "Bearer t"}


def test_missing_token_rejected(fake_db):
    response = client.get("/students")
    assert response.status_code == 401


def test_teacher_without_mfa_rejected(monkeypatch, fake_db):
    monkeypatch.setattr(
        "api.app.identity.verify_id_token",
        lambda token: {"uid": "teacher-1", "role": "teacher", "firebase": {"sign_in_provider": "password"}},
    )
    response = client.get("/students", headers=AUTH)
    assert response.status_code == 401


def test_create_requires_teacher(monkeypatch, fake_db):
    as_student(monkeypatch, student_id="s1")
    response = client.post("/students", json={"username": "Alex", "password": "longenough"}, headers=AUTH)
    assert response.status_code == 403


def test_create_student_as_teacher(monkeypatch, fake_db, as_teacher):
    monkeypatch.setattr("api.app.identity.create_student_user", lambda username, password: "auth-uid-1")
    monkeypatch.setattr("api.app.identity.set_student_claims", lambda uid, student_id: None)

    response = client.post("/students", json={"username": "Alex", "password": "longenough"}, headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "Alex"
    assert body["active"] is True

    entries = fake_db.collection("audit").stream()
    assert any(e.get("action") == "create_student" for e in entries)


def test_student_cannot_read_another_students_record(monkeypatch, fake_db):
    fake_db.collection("students").document("s1").set(
        {"username": "Alex", "auth_uid": "u1", "active": True}
    )
    fake_db.collection("students").document("s2").set(
        {"username": "Blair", "auth_uid": "u2", "active": True}
    )

    as_student(monkeypatch, student_id="s1", uid="u1")

    own = client.get("/students/s1", headers=AUTH)
    assert own.status_code == 200

    other = client.get("/students/s2", headers=AUTH)
    assert other.status_code == 403


def test_student_cannot_list_all_students(monkeypatch, fake_db):
    as_student(monkeypatch, student_id="s1")
    response = client.get("/students", headers=AUTH)
    assert response.status_code == 403


def test_deactivate_requires_teacher(monkeypatch, fake_db):
    fake_db.collection("students").document("s1").set(
        {"username": "Alex", "auth_uid": "u1", "active": True}
    )
    as_student(monkeypatch, student_id="s1", uid="u1")
    response = client.post("/students/s1/deactivate", headers=AUTH)
    assert response.status_code == 403


def test_deactivate_is_audited(monkeypatch, fake_db, as_teacher):
    fake_db.collection("students").document("s1").set(
        {"username": "Alex", "auth_uid": "u1", "active": True}
    )
    monkeypatch.setattr("api.app.identity.disable_user", lambda uid: None)

    response = client.post("/students/s1/deactivate", headers=AUTH)
    assert response.status_code == 200

    entries = fake_db.collection("audit").stream()
    assert any(e.get("action") == "deactivate_student" and e.get("target") == "s1" for e in entries)


def test_reset_password_is_audited(monkeypatch, fake_db, as_teacher):
    fake_db.collection("students").document("s1").set(
        {"username": "Alex", "auth_uid": "u1", "active": True}
    )
    monkeypatch.setattr("api.app.identity.reset_password", lambda uid, password: None)

    response = client.post(
        "/students/s1/reset-password", json={"password": "newlongpassword"}, headers=AUTH
    )
    assert response.status_code == 200
    entries = fake_db.collection("audit").stream()
    assert any(e.get("action") == "reset_password" and e.get("target") == "s1" for e in entries)


def test_delete_requires_matching_username(monkeypatch, fake_db, as_teacher):
    fake_db.collection("students").document("s1").set(
        {"username": "Alex", "auth_uid": "u1", "active": True}
    )
    monkeypatch.setattr("api.app.identity.delete_user", lambda uid: None)
    monkeypatch.setattr("api.app.photos.delete_folder", lambda prefix: None)

    wrong = client.request(
        "DELETE", "/students/s1", json={"confirm_username": "NotAlex"}, headers=AUTH
    )
    assert wrong.status_code == 400

    right = client.request(
        "DELETE", "/students/s1", json={"confirm_username": "Alex"}, headers=AUTH
    )
    assert right.status_code == 200

    entries = fake_db.collection("audit").stream()
    assert any(e.get("action") == "delete_student" and e.get("target") == "s1" for e in entries)

    # Really gone, not just marked inactive.
    assert not fake_db.collection("students").document("s1").get().exists
