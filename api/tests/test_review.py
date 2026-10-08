"""Phase 5 flow: short answer submitted -> scrub -> evaluate -> teacher edits
-> approve -> release -> student view, plus what each side may see."""

from fastapi.testclient import TestClient

from api.app.main import app

from .conftest import as_student, become_teacher
from .test_exercises import AUTH, DRAFT, RIGHT, _assign, _generate, harness, student  # noqa: F401 (fixtures)

client = TestClient(app)

SHORT = {"id": "i3", "type": "short_answer", "prompt": "What did you do last weekend?"}
ORIGINAL = "I go to the park with my friend Maria Lopez."
SCRUBBED = "I go to the park with my friend [name]."


def _evaluation(mark="partial", span="go", feedback="Use the past tense for last weekend."):
    return {
        "items": [
            {
                "item_id": "i3",
                "mark": mark,
                "annotations": [
                    {"code": "VT", "span_text": span, "occurrence": 1, "correction": "went", "explanation": "Past."}
                ],
                "feedback": feedback,
            }
        ]
    }


def _submitted(monkeypatch, harness):  # noqa: F811
    """An exercise with a short answer, submitted by student s1. Leaves the
    test signed in as the teacher."""
    harness.result = {**DRAFT, "items": DRAFT["items"] + [SHORT]}
    exercise_id = _generate()
    _assign(exercise_id)
    as_student(monkeypatch, student_id="s1")
    answers = {**RIGHT, "i3": ORIGINAL}
    assert client.post(f"/exercises/{exercise_id}/submit", json={"answers": answers}, headers=AUTH).status_code == 200
    become_teacher(monkeypatch)
    return exercise_id


def _scrub(exercise_id, text=SCRUBBED):
    return client.put(f"/exercises/{exercise_id}/scrubbed", json={"scrubbed_answers": {"i3": text}}, headers=AUTH)


def _evaluate(exercise_id, harness, note="", result=None):  # noqa: F811
    harness.result = result or _evaluation()
    return client.post(f"/exercises/{exercise_id}/evaluate", json={"note": note}, headers=AUTH)


def _job(fake_db, job_id):
    return fake_db.collection("jobs").document(job_id).get().to_dict()


def test_full_flow_to_released_student_view(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    exercise_id = _submitted(monkeypatch, harness)
    view = client.get(f"/exercises/{exercise_id}", headers=AUTH).json()
    assert view["state"] == "scrub_review"
    assert view["scrubbed_answers"] == {"i3": ORIGINAL}  # the editable copy starts as the original

    assert _scrub(exercise_id).status_code == 200
    response = _evaluate(exercise_id, harness)
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["state"] == "draft_ready"
    annotation = view["evaluation"]["items"][0]["annotations"][0]
    assert (annotation["start"], annotation["end"]) == (2, 4)  # offsets computed by the API

    # Only the scrubbed text reached the harness: no original, no username.
    sent = str(harness.calls[-1])
    assert "Maria" not in sent and "Alex" not in sent and SCRUBBED in sent

    # Original answers are untouched.
    submission = fake_db.collection("submissions").document(exercise_id).get().to_dict()
    assert submission["answers"]["i3"] == ORIGINAL

    # Nothing visible to the student before release.
    as_student(monkeypatch, student_id="s1")
    item = client.get(f"/exercises/{exercise_id}", headers=AUTH).json()["items"][2]
    assert "mark" not in item and "feedback" not in item and "spans" not in item

    become_teacher(monkeypatch)
    assert client.post(f"/exercises/{exercise_id}/release", headers=AUTH).status_code == 409  # not approved yet
    assert client.post(f"/exercises/{exercise_id}/approve", headers=AUTH).status_code == 200
    assert _job(fake_db, submission["evaluation_job_id"])["teacher_action"] == "accepted"
    assert client.post(f"/exercises/{exercise_id}/release", headers=AUTH).status_code == 200

    as_student(monkeypatch, student_id="s1")
    item = client.get(f"/exercises/{exercise_id}", headers=AUTH).json()["items"][2]
    assert item["mark"] == "partial"
    assert item["feedback"] == "Use the past tense for last weekend."
    assert item["answer_text"] == SCRUBBED
    assert item["spans"] == [{"start": 2, "end": 4, "code": "VT", "meaning": "Verb tense"}]
    # Corrections and explanations on annotations are teacher-only (FR-21).
    assert "went" not in str(item) and "Past." not in str(item)


def test_editing_scrubbed_text_invalidates_the_evaluation(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    exercise_id = _submitted(monkeypatch, harness)
    _scrub(exercise_id)
    _evaluate(exercise_id, harness)

    view = _scrub(exercise_id, "I go to the park with a friend.").json()
    assert view["state"] == "scrub_review"
    assert view["evaluation"] is None and view["evaluation_valid"] is False
    assert client.post(f"/exercises/{exercise_id}/approve", headers=AUTH).status_code == 409

    # Saving the same text again does not throw an evaluation away.
    _evaluate(exercise_id, harness)
    assert _scrub(exercise_id, "I go to the park with a friend.").json()["state"] == "draft_ready"


def test_scrubbed_copy_must_cover_exactly_the_short_answers(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    exercise_id = _submitted(monkeypatch, harness)
    bad = {"scrubbed_answers": {"i3": "x", "i1": "y"}}
    assert client.put(f"/exercises/{exercise_id}/scrubbed", json=bad, headers=AUTH).status_code == 422


def test_teacher_edits_are_validated_and_overrides_audited(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    exercise_id = _submitted(monkeypatch, harness)
    _scrub(exercise_id)
    _evaluate(exercise_id, harness)

    # A span that isn't in the scrubbed text is refused.
    response = client.put(f"/exercises/{exercise_id}/evaluation", json=_evaluation(span="goes"), headers=AUTH)
    assert response.status_code == 422
    # An unknown code is refused by the shared schema.
    bad_code = _evaluation()
    bad_code["items"][0]["annotations"][0]["code"] = "ZZ"
    assert client.put(f"/exercises/{exercise_id}/evaluation", json=bad_code, headers=AUTH).status_code == 422

    # Changing the mark is an override: audit-logged once, even if saved twice.
    for _ in range(2):
        response = client.put(f"/exercises/{exercise_id}/evaluation", json=_evaluation(mark="incorrect"), headers=AUTH)
        assert response.status_code == 200
    audit = [a.to_dict() for a in fake_db.collection("audit").stream()]
    assert [a["action"] for a in audit].count("override_mark") == 1

    client.post(f"/exercises/{exercise_id}/approve", headers=AUTH)
    job_id = fake_db.collection("submissions").document(exercise_id).get().get("evaluation_job_id")
    assert _job(fake_db, job_id)["teacher_action"] == "overridden"


def test_editing_feedback_only_counts_as_edited(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    exercise_id = _submitted(monkeypatch, harness)
    _scrub(exercise_id)
    _evaluate(exercise_id, harness)
    client.put(f"/exercises/{exercise_id}/evaluation", json=_evaluation(feedback="Try 'went'."), headers=AUTH)
    client.post(f"/exercises/{exercise_id}/approve", headers=AUTH)
    job_id = fake_db.collection("submissions").document(exercise_id).get().get("evaluation_job_id")
    assert _job(fake_db, job_id)["teacher_action"] == "edited"


def test_regenerate_with_note(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    exercise_id = _submitted(monkeypatch, harness)
    _scrub(exercise_id)
    _evaluate(exercise_id, harness)
    first_job = fake_db.collection("submissions").document(exercise_id).get().get("evaluation_job_id")

    response = _evaluate(exercise_id, harness, note="'park' is fine", result=_evaluation(mark="incorrect"))
    assert response.status_code == 200
    assert response.json()["evaluation"]["items"][0]["mark"] == "incorrect"
    assert harness.calls[-1]["regenerate_note"] == "'park' is fine"
    assert _job(fake_db, first_job)["teacher_action"] == "regenerated"


def test_failed_evaluation_loses_nothing(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    exercise_id = _submitted(monkeypatch, harness)
    _scrub(exercise_id)
    _evaluate(exercise_id, harness)

    # The AI evaluates the wrong item: rejected by the API's own check.
    wrong_item = _evaluation()
    wrong_item["items"][0]["item_id"] = "i9"
    assert _evaluate(exercise_id, harness, result=wrong_item).status_code == 502

    view = client.get(f"/exercises/{exercise_id}", headers=AUTH).json()
    assert view["state"] == "draft_ready"  # back where it was
    assert view["evaluation"]["items"][0]["item_id"] == "i3"  # previous draft kept


def test_spend_cap_blocks_evaluation(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    exercise_id = _submitted(monkeypatch, harness)
    fake_db.collection("settings").document("global").set({"monthly_cap_usd": 0.0})
    assert _evaluate(exercise_id, harness).status_code == 409
    assert client.get(f"/exercises/{exercise_id}", headers=AUTH).json()["state"] == "scrub_review"


def test_students_cannot_use_review_endpoints(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    exercise_id = _submitted(monkeypatch, harness)
    as_student(monkeypatch, student_id="s1")
    assert _scrub(exercise_id).status_code == 403
    assert _evaluate(exercise_id, harness).status_code == 403
    assert client.put(f"/exercises/{exercise_id}/evaluation", json=_evaluation(), headers=AUTH).status_code == 403
    assert client.post(f"/exercises/{exercise_id}/approve", headers=AUTH).status_code == 403


def test_reopen_clears_scrub_and_evaluation(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    exercise_id = _submitted(monkeypatch, harness)
    _scrub(exercise_id)
    _evaluate(exercise_id, harness)
    assert client.post(f"/exercises/{exercise_id}/reopen", headers=AUTH).status_code == 200
    view = client.get(f"/exercises/{exercise_id}", headers=AUTH).json()
    assert view["state"] == "in_progress"
    assert view["scrubbed_answers"] == {} and view["evaluation"] is None
    assert view["answers"]["i3"] == ORIGINAL  # the student's answer is kept
