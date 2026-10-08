"""Phase 7: learner profile, teacher notes, context assembler, lessons,
and the class overview."""

from fastapi.testclient import TestClient

from api.app.context import MAX_EXCERPTS, MAX_NOTES_CHARS, cap_notes, choose_excerpts, excerpt, profile_summary
from api.app.main import app
from api.app.profile import compute_profile

from .conftest import as_student, become_teacher
from .test_exercises import AUTH, DRAFT, WRONG, _assign, _generate, harness, student  # noqa: F401 (fixtures)
from .test_writing import _released

client = TestClient(app)

LESSON = {
    "title": "Past tense with time words",
    "explanation": "word " * 220,
    "examples": [{"incorrect": "Yesterday I go.", "correct": "Yesterday I went.", "note": "Past time, past tense."}],
    "word_count": 230,
}


# ---- profile: plain counting over approved data ----


def _writing_pair(codes, outcomes=None, text="aa bb cc dd ee"):
    annotations = [{"code": c, "start": 3 * i, "end": 3 * i + 2} for i, c in enumerate(codes)]
    submission = {
        "state": "revision_submitted",
        "scrubbed_answers": {"text": text},
        "evaluation": {"annotations": annotations, "comment": ""},
        "revision": {"edits": {k: "x" for k in (outcomes or {})}, "outcomes": outcomes or {}},
    }
    return {"kind": "writing"}, submission


def test_profile_counts_annotations_wrong_items_and_outcomes():
    grammar = (
        {"kind": "grammar", "items": [{"id": "i1", "concept": "VT"}, {"id": "i2", "concept": "WO"}]},
        {"state": "released", "grades": {"i1": False, "i2": True}},
    )
    writing = _writing_pair(["VT", "ART", "VT"], outcomes={"0": "fixed", "2": "changed_wrongly"})
    rows = {row["code"]: row for row in compute_profile([grammar, writing])}
    assert rows["VT"]["errors"] == 3  # one wrong item + two annotations
    assert (rows["VT"]["fixed"], rows["VT"]["changed_wrongly"], rows["VT"]["unfixed"]) == (1, 1, 0)
    assert rows["ART"]["errors"] == 1
    assert "WO" not in rows  # answered correctly
    assert [row["code"] for row in compute_profile([grammar, writing])][0] == "VT"  # most frequent first


def test_profile_summary_and_notes_cap():
    rows = compute_profile([_writing_pair(["VT", "VT"], outcomes={"0": "unfixed"})])
    summary = profile_summary(rows, 1)
    assert "VT (Verb tense): 2 error(s); revisions: 1 not fixed" in summary
    assert profile_summary([], 0) == ""
    assert cap_notes("  short  ") == "short"
    long = "newest note. " + "x" * MAX_NOTES_CHARS
    assert cap_notes(long).startswith("newest note.") and len(cap_notes(long)) <= MAX_NOTES_CHARS + 2


def test_excerpts_are_the_sentence_around_the_error():
    text = "I like Mondays. Yesterday I go to the park. It was fun."
    start = text.index("go")
    assert excerpt(text, start, start + 2) == "Yesterday I «go» to the park."
    long_text = "word " * 200
    assert len(excerpt(long_text, 500, 504)) <= 310 and "«word»" in excerpt(long_text, 500, 504)


def test_excerpts_take_codes_in_turn_and_cap_at_five():
    text = "aa bb cc dd ee"
    pairs = [_writing_pair(["VT", "VT", "VT", "ART", "SP"], text=text)] * 2
    chosen = choose_excerpts(pairs, ["VT", "ART", "SP"])
    assert len(chosen) == MAX_EXCERPTS
    assert [c.split("]")[0] + "]" for c in chosen[:3]] == ["[VT]", "[ART]", "[SP]"]


def test_profile_endpoint_uses_only_approved_work(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    _released(monkeypatch, harness)  # writing: one VT annotation, approved and released
    harness.result = DRAFT
    unapproved = _generate()  # grammar, assigned and submitted wrong, but...
    _assign(unapproved)
    as_student(monkeypatch, student_id="s1")
    client.post(f"/exercises/{unapproved}/submit", json={"answers": WRONG}, headers=AUTH)
    become_teacher(monkeypatch)
    # ...graded-only grammar goes straight to ready_to_release, which counts.
    data = client.get("/students/s1/profile", headers=AUTH).json()
    rows = {row["code"]: row["errors"] for row in data["profile"]["codes"]}
    assert rows == {"VT": 2, "WO": 1}
    assert data["profile"]["submissions_counted"] == 2

    # The window setting limits how many submissions count.
    fake_db.collection("settings").document("global").set({"profile_window": 1})
    assert client.get("/students/s1/profile", headers=AUTH).json()["profile"]["submissions_counted"] == 1

    as_student(monkeypatch, student_id="s1")
    assert client.get("/students/s1/profile", headers=AUTH).status_code == 403


# ---- notes and the context bundle ----


def test_notes_reach_the_harness_but_never_the_username(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    _released(monkeypatch, harness)
    assert client.put("/students/s1/notes", json={"teacher_notes": "Works as a nurse."}, headers=AUTH).status_code == 200
    as_student(monkeypatch, student_id="s1")
    assert client.put("/students/s1/notes", json={"teacher_notes": "x"}, headers=AUTH).status_code == 403
    become_teacher(monkeypatch)

    harness.result = DRAFT
    _generate()
    context = harness.calls[-1]["context"]
    assert context["teacher_notes"] == "Works as a nurse."
    assert "VT (Verb tense): 1 error(s)" in context["profile_summary"]
    assert context["excerpts"] == ["[VT] On saturday I «go» to the market with my sister [name]."]
    assert context["recent_titles"][0] == "My weekend"
    assert "Alex" not in str(harness.calls[-1])  # the username
    assert "Maria" not in str(harness.calls[-1])  # the original, unscrubbed text


# ---- lessons ----


def _lesson(harness):  # noqa: F811
    harness.result = LESSON
    response = client.post("/lessons/generate", json={"student_id": "s1", "description": "past tense"}, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()["lesson_id"]


def test_lesson_flow(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    lesson_id = _lesson(harness)
    assert "context" in harness.calls[-1] and "Alex" not in str(harness.calls[-1])

    edited = {"title": "Past tense", "explanation": "Short now.", "examples": LESSON["examples"]}
    view = client.put(f"/lessons/{lesson_id}", json=edited, headers=AUTH).json()
    assert view["title"] == "Past tense" and view["word_count"] == 2 + 10

    harness.result = {**LESSON, "title": "Regenerated"}
    view = client.post(f"/lessons/{lesson_id}/regenerate", json={"note": "more examples"}, headers=AUTH).json()
    assert view["title"] == "Regenerated"
    assert harness.calls[-1]["regenerate_note"] == "more examples"

    # Not visible to the student until assigned.
    as_student(monkeypatch, student_id="s1")
    assert client.get("/me/lessons", headers=AUTH).json() == []
    assert client.get(f"/lessons/{lesson_id}", headers=AUTH).status_code == 404

    become_teacher(monkeypatch)
    assert client.post(f"/lessons/{lesson_id}/assign", headers=AUTH).json()["status"] == "assigned"
    assert client.put(f"/lessons/{lesson_id}", json=edited, headers=AUTH).status_code == 409  # frozen

    as_student(monkeypatch, student_id="s1")
    assert client.get("/me/lessons", headers=AUTH).json() == [{"lesson_id": lesson_id, "title": "Regenerated", "read": False}]
    view = client.get(f"/lessons/{lesson_id}", headers=AUTH).json()
    assert set(view) == {"lesson_id", "title", "explanation", "examples", "read"}  # no request, no history
    assert client.post(f"/lessons/{lesson_id}/read", headers=AUTH).status_code == 200
    assert client.get(f"/lessons/{lesson_id}", headers=AUTH).json()["read"] is True

    # Other students can't see or mark it.
    as_student(monkeypatch, student_id="s2", uid="u2")
    assert client.get(f"/lessons/{lesson_id}", headers=AUTH).status_code == 404
    assert client.post(f"/lessons/{lesson_id}/read", headers=AUTH).status_code == 404
    assert client.post("/lessons/generate", json={"student_id": "s2", "description": "x"}, headers=AUTH).status_code == 403


def test_invalid_lesson_is_never_saved(fake_db, as_teacher, harness, student):  # noqa: F811
    harness.result = {**LESSON, "word_count": 900}
    response = client.post("/lessons/generate", json={"student_id": "s1", "description": "x"}, headers=AUTH)
    assert response.status_code == 502
    assert fake_db.collection("lessons").stream() == []


# ---- class overview ----


def test_overview_lists_unfinished_work_and_unread_lessons(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    released_writing = _released(monkeypatch, harness)  # revision open: unfinished
    harness.result = DRAFT
    graded = _generate()
    _assign(graded)  # assigned, not started
    lesson_id = _lesson(harness)
    client.post(f"/lessons/{lesson_id}/assign", headers=AUTH)

    rows = {row["username"]: row for row in client.get("/overview", headers=AUTH).json()}
    assert [(w["exercise_id"], w["state"]) for w in rows["Alex"]["work"]] == [
        (graded, "assigned"),
        (released_writing, "revision_open"),
    ]
    assert rows["Alex"]["unread_lessons"] == [{"lesson_id": lesson_id, "title": LESSON["title"]}]
    assert rows["Sam"] == {"student_id": "s2", "username": "Sam", "work": [], "unread_lessons": []}

    # A revision counts as finished once every changed span is marked.
    as_student(monkeypatch, student_id="s1")
    client.post(f"/exercises/{released_writing}/revision/submit", json={"edits": {"0": "went"}}, headers=AUTH)
    client.post(f"/lessons/{lesson_id}/read", headers=AUTH)
    become_teacher(monkeypatch)
    work = client.get("/overview", headers=AUTH).json()[0]["work"]
    assert [w["state"] for w in work] == ["assigned", "revision_submitted"]
    client.put(f"/exercises/{released_writing}/revision/outcomes", json={"outcomes": {"0": "fixed"}}, headers=AUTH)
    alex = client.get("/overview", headers=AUTH).json()[0]
    assert [w["state"] for w in alex["work"]] == ["assigned"] and alex["unread_lessons"] == []

    as_student(monkeypatch, student_id="s1")
    assert client.get("/overview", headers=AUTH).status_code == 403
