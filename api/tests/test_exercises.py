"""Phase 4 flow: generate -> edit/regenerate -> assign -> autosave ->
submit -> release, plus who may see what along the way."""

import pytest
from fastapi.testclient import TestClient

from api.app.main import app

from .conftest import as_student, become_teacher

client = TestClient(app)
AUTH = {"Authorization": "Bearer t"}

DRAFT = {
    "kind": "grammar",
    "title": "Past tense practice",
    "items": [
        {
            "id": "i1",
            "type": "fill_blank",
            "text": "She ___ to school yesterday.",
            "blanks": [{"id": "b1", "accepted": ["went"]}],
            "concept": "VT",
            "explanation": "Past tense of 'go' is 'went'.",
        },
        {
            "id": "i2",
            "type": "reorder",
            "chunks": ["always", "I", "eat", "breakfast"],
            "accepted_orders": [["I", "always", "eat", "breakfast"]],
            "concept": "WO",
            "explanation": "Frequency adverbs go after the subject.",
        },
    ],
}
RIGHT = {"i1": {"b1": "went"}, "i2": [1, 0, 2, 3]}
WRONG = {"i1": {"b1": "goed"}, "i2": [0, 1, 2, 3]}


def _envelope(result):
    return {"result": result, "model": "mock", "tokens_in": 10, "tokens_out": 10, "latency_ms": 1.0}


@pytest.fixture
def harness(monkeypatch):
    """Stands in for the harness service. Set `harness.result` to change
    what it returns; records each request body it receives."""

    class Fake:
        result = DRAFT
        calls: list = []

        def __call__(self, path, body):
            self.calls.append(body)
            return _envelope(self.result)

    fake = Fake()
    fake.calls = []
    monkeypatch.setattr("api.app.harness_ops.post_to_harness", fake)
    return fake


@pytest.fixture
def student(fake_db):
    fake_db.collection("students").document("s1").set({"username": "Alex", "auth_uid": "u1", "active": True})
    fake_db.collection("students").document("s2").set({"username": "Sam", "auth_uid": "u2", "active": True})


def _generate(student_id="s1"):
    response = client.post(
        "/exercises/generate", json={"student_id": student_id, "description": "past tense"}, headers=AUTH
    )
    assert response.status_code == 200, response.text
    return response.json()["exercise_id"]


def _assign(exercise_id):
    response = client.post(
        f"/exercises/{exercise_id}/assign", json={"answers_and_concepts_checked": True}, headers=AUTH
    )
    assert response.status_code == 200, response.text


# ---- generation ----


def test_generate_stores_draft_and_records_job(fake_db, as_teacher, harness, student):
    exercise_id = _generate()
    exercise = fake_db.collection("exercises").document(exercise_id).get().to_dict()
    assert exercise["status"] == "draft"
    assert exercise["items"][0]["blanks"][0]["accepted"] == ["went"]
    assert [j.get("status") for j in fake_db.collection("jobs").stream()] == ["done"]
    # Only the opaque id goes to the harness, never the username.
    assert harness.calls[0]["student_id"] == "s1"
    assert "Alex" not in str(harness.calls[0])


def test_student_cannot_generate(monkeypatch, fake_db, harness, student):
    as_student(monkeypatch, student_id="s1")
    response = client.post("/exercises/generate", json={"student_id": "s1", "description": "x"}, headers=AUTH)
    assert response.status_code == 403


def test_invalid_harness_output_is_never_saved(fake_db, as_teacher, harness, student):
    bad = {**DRAFT, "items": [{**DRAFT["items"][0], "concept": "NOPE"}]}
    harness.result = bad
    response = client.post("/exercises/generate", json={"student_id": "s1", "description": "x"}, headers=AUTH)
    assert response.status_code == 502
    assert fake_db.collection("exercises").stream() == []


def test_spend_cap_blocks_generation(fake_db, as_teacher, harness, student):
    fake_db.collection("settings").document("global").set({"monthly_cap_usd": 0.0})
    response = client.post("/exercises/generate", json={"student_id": "s1", "description": "x"}, headers=AUTH)
    assert response.status_code == 409
    assert harness.calls == []


# ---- teacher editing ----


def test_edit_is_validated_with_the_shared_schema(fake_db, as_teacher, harness, student):
    exercise_id = _generate()
    two_markers = {**DRAFT, "items": [{**DRAFT["items"][0], "text": "She ___ and ___."}]}
    assert client.put(f"/exercises/{exercise_id}", json=two_markers, headers=AUTH).status_code == 422

    edited = {**DRAFT, "title": "Edited"}
    response = client.put(f"/exercises/{exercise_id}", json=edited, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["title"] == "Edited"


def test_regenerate_keeps_previous_version(fake_db, as_teacher, harness, student):
    exercise_id = _generate()
    harness.result = {**DRAFT, "title": "Second try"}
    response = client.post(f"/exercises/{exercise_id}/regenerate", json={"note": "harder"}, headers=AUTH)
    assert response.json()["title"] == "Second try"
    assert harness.calls[1]["regenerate_note"] == "harder"
    history = fake_db.collection("exercises").document(exercise_id).get().get("generation_history")
    assert history[0]["title"] == "Past tense practice"
    assert history[0]["note"] == "harder"


def test_assign_requires_checklist_and_freezes(fake_db, as_teacher, harness, student):
    exercise_id = _generate()
    response = client.post(
        f"/exercises/{exercise_id}/assign", json={"answers_and_concepts_checked": False}, headers=AUTH
    )
    assert response.status_code == 422
    _assign(exercise_id)
    assert client.put(f"/exercises/{exercise_id}", json=DRAFT, headers=AUTH).status_code == 409
    assert client.post(f"/exercises/{exercise_id}/regenerate", json={}, headers=AUTH).status_code == 409


# ---- what students can see ----


def test_student_cannot_see_drafts_or_other_students_work(monkeypatch, fake_db, as_teacher, harness, student):
    draft_id = _generate("s1")
    other_id = _generate("s2")
    _assign(other_id)

    as_student(monkeypatch, student_id="s1")
    assert client.get(f"/exercises/{draft_id}", headers=AUTH).status_code == 404
    assert client.get(f"/exercises/{other_id}", headers=AUTH).status_code == 404
    assert client.put(f"/exercises/{other_id}/answers", json={"answers": {}}, headers=AUTH).status_code == 404
    assert client.get("/me/exercises", headers=AUTH).json() == []


def test_student_view_hides_answer_keys_before_release(monkeypatch, fake_db, as_teacher, harness, student):
    exercise_id = _generate()
    _assign(exercise_id)

    as_student(monkeypatch, student_id="s1")
    body = client.get(f"/exercises/{exercise_id}", headers=AUTH).json()
    text = str(body)
    for hidden in ("accepted", "explanation", "concept", "teacher_request", "correct", "went"):
        assert hidden not in text, hidden
    assert body["items"][0]["blank_ids"] == ["b1"]
    assert body["items"][1]["chunks"] == ["always", "I", "eat", "breakfast"]


# ---- doing and submitting ----


def test_autosave_submit_release_flow(monkeypatch, fake_db, as_teacher, harness, student):
    exercise_id = _generate()
    _assign(exercise_id)

    as_student(monkeypatch, student_id="s1")
    assert client.get("/me/exercises", headers=AUTH).json()[0]["state"] == "assigned"
    saved = client.put(f"/exercises/{exercise_id}/answers", json={"answers": {"i1": {"b1": "go"}}}, headers=AUTH)
    assert saved.status_code == 200
    resumed = client.get(f"/exercises/{exercise_id}", headers=AUTH).json()
    assert resumed["state"] == "in_progress"
    assert resumed["answers"] == {"i1": {"b1": "go"}}

    submit = {"answers": {"i1": {"b1": "went"}, "i2": [0, 1, 2, 3]}}  # first right, second wrong
    assert client.post(f"/exercises/{exercise_id}/submit", json=submit, headers=AUTH).status_code == 200
    # Locked after submit, and still no results before release.
    assert client.put(f"/exercises/{exercise_id}/answers", json=submit, headers=AUTH).status_code == 409
    assert client.post(f"/exercises/{exercise_id}/submit", json=submit, headers=AUTH).status_code == 409
    assert "correct" not in str(client.get(f"/exercises/{exercise_id}", headers=AUTH).json()["items"])

    become_teacher(monkeypatch)
    teacher_view = client.get(f"/exercises/{exercise_id}", headers=AUTH).json()
    assert teacher_view["state"] == "ready_to_release"
    assert teacher_view["grades"] == {"i1": True, "i2": False}
    assert client.post(f"/exercises/{exercise_id}/release", headers=AUTH).status_code == 200

    as_student(monkeypatch, student_id="s1")
    items = client.get(f"/exercises/{exercise_id}", headers=AUTH).json()["items"]
    assert items[0]["correct"] is True
    assert "correct_answer" not in items[0]  # only shown for wrong items
    assert items[1]["correct"] is False
    assert items[1]["correct_answer"] == ["I", "always", "eat", "breakfast"]
    assert items[1]["explanation"] == "Frequency adverbs go after the subject."
    assert "concept" not in str(items)


def test_answers_must_match_item_shapes(monkeypatch, fake_db, as_teacher, harness, student):
    exercise_id = _generate()
    _assign(exercise_id)
    as_student(monkeypatch, student_id="s1")
    for bad in ({"nope": "x"}, {"i1": "went"}, {"i2": {"b1": "x"}}, {"i1": {"zz": "x"}}):
        response = client.put(f"/exercises/{exercise_id}/answers", json={"answers": bad}, headers=AUTH)
        assert response.status_code == 422, bad


def test_late_autosave_cannot_undo_a_submit(monkeypatch, fake_db, as_teacher, harness, student):
    """An autosave already on its way when the student taps Submit reads
    "in_progress"; the submit lands before the autosave writes. The
    autosave must then fail rather than unlock the submitted work."""
    exercise_id = _generate()
    _assign(exercise_id)
    as_student(monkeypatch, student_id="s1")

    def submit_lands_meanwhile(draft, answers):
        fake_db.collection("submissions").document(exercise_id).update({"state": "ready_to_release"})

    monkeypatch.setattr("api.app.exercises._check_answer_shapes", submit_lands_meanwhile)
    response = client.put(f"/exercises/{exercise_id}/answers", json={"answers": RIGHT}, headers=AUTH)
    assert response.status_code == 409
    assert fake_db.collection("submissions").document(exercise_id).get().get("state") == "ready_to_release"


def test_reorder_answer_cannot_be_longer_than_its_chunks(monkeypatch, fake_db, as_teacher, harness, student):
    exercise_id = _generate()
    _assign(exercise_id)
    as_student(monkeypatch, student_id="s1")
    too_long = {"answers": {"i2": list(range(10_000))}}
    assert client.put(f"/exercises/{exercise_id}/answers", json=too_long, headers=AUTH).status_code == 422


def test_short_answers_go_to_scrub_review(monkeypatch, fake_db, as_teacher, harness, student):
    harness.result = {**DRAFT, "items": DRAFT["items"] + [{"id": "i3", "type": "short_answer", "prompt": "Why?"}]}
    exercise_id = _generate()
    _assign(exercise_id)
    as_student(monkeypatch, student_id="s1")
    client.post(f"/exercises/{exercise_id}/submit", json={"answers": {**RIGHT, "i3": "Because."}}, headers=AUTH)
    assert fake_db.collection("submissions").document(exercise_id).get().get("state") == "scrub_review"


def test_teacher_cannot_answer_for_a_student(fake_db, as_teacher, harness, student):
    exercise_id = _generate()
    _assign(exercise_id)
    response = client.put(f"/exercises/{exercise_id}/answers", json={"answers": RIGHT}, headers=AUTH)
    assert response.status_code == 403


def test_reopen_is_audited_and_not_allowed_after_release(monkeypatch, fake_db, as_teacher, harness, student):
    exercise_id = _generate()
    _assign(exercise_id)
    as_student(monkeypatch, student_id="s1")
    client.post(f"/exercises/{exercise_id}/submit", json={"answers": WRONG}, headers=AUTH)

    become_teacher(monkeypatch)
    assert client.post(f"/exercises/{exercise_id}/reopen", headers=AUTH).status_code == 200
    submission = fake_db.collection("submissions").document(exercise_id).get().to_dict()
    assert submission["state"] == "in_progress"
    assert submission["answers"] == WRONG  # kept so the student can continue
    assert any(e.get("action") == "reopen_submission" for e in fake_db.collection("audit").stream())

    as_student(monkeypatch, student_id="s1")
    client.post(f"/exercises/{exercise_id}/submit", json={"answers": RIGHT}, headers=AUTH)
    become_teacher(monkeypatch)
    client.post(f"/exercises/{exercise_id}/release", headers=AUTH)
    assert client.post(f"/exercises/{exercise_id}/reopen", headers=AUTH).status_code == 409


def test_taxonomy_comes_from_the_shared_list(fake_db, as_teacher):
    codes = [c["code"] for c in client.get("/taxonomy", headers=AUTH).json()]
    assert len(codes) == 14 and "VT" in codes
