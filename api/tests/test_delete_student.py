"""Deleting a student removes everything they own (FR-4), and nothing of
anyone else's."""

from fastapi.testclient import TestClient

from api.app.main import app

from .test_exercises import AUTH, harness, student  # noqa: F401 (fixtures)
from .test_profile_lessons import _lesson
from .test_writing import PHOTO, _assigned, bucket  # noqa: F401 (fixture)

client = TestClient(app)


def test_delete_removes_all_their_data_and_photos(monkeypatch, fake_db, as_teacher, harness, student, bucket):  # noqa: F811
    monkeypatch.setattr("api.app.photos.delete_folder", lambda prefix: [bucket.pop(p) for p in list(bucket) if p.startswith(prefix)])
    deleted_logins = []
    monkeypatch.setattr("api.app.identity.delete_user", deleted_logins.append)

    mine = _assigned(harness)
    client.post(f"/exercises/{mine}/photos", content=PHOTO, headers={"Content-Type": "image/jpeg", **AUTH})
    _lesson(harness)
    # Sam's work, which must survive.
    fake_db.collection("exercises").document("sams").set({"student_id": "s2", "title": "x"})
    fake_db.collection("jobs").document("sams-job").set({"student_id": "s2"})
    assert bucket and fake_db.collection("jobs").stream()

    response = client.request("DELETE", "/students/s1", json={"confirm_username": "Alex"}, headers=AUTH)
    assert response.status_code == 200, response.text

    assert bucket == {}
    assert deleted_logins == ["u1"]
    for collection in ("exercises", "submissions", "lessons", "jobs"):
        assert all(doc.get("student_id") == "s2" for doc in fake_db.collection(collection).stream()), collection
    assert fake_db.collection("exercises").document("sams").get().exists
    assert fake_db.collection("jobs").document("sams-job").get().exists
    assert not fake_db.collection("students").document("s1").get().exists
    assert fake_db.collection("students").document("s2").get().exists
