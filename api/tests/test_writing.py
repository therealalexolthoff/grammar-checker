"""Phase 6 flow: writing exercises, typed and handwritten, through scrub,
evaluation, release and the one revision round - plus what each side may
see along the way."""

import pytest
from fastapi.testclient import TestClient

from api.app.main import app
from api.app.photos import strip_jpeg_metadata
from api.app.revision import apply_revision

from .conftest import as_student, become_teacher
from .test_exercises import AUTH, harness, student  # noqa: F401 (fixtures)

client = TestClient(app)

WRITING = {"kind": "writing", "title": "My weekend", "prompt": "Describe your weekend.", "min_words": 50, "max_words": 150}
TYPED = "On saturday I go to the market with my sister Maria."
SCRUBBED = "On saturday I go to the market with my sister [name]."
TRANSCRIBED = "Yesterday I visit my freind [?] in the city."

# The smallest JPEG-shaped file the metadata stripper accepts: the start
# marker, a JFIF header (kept), an EXIF segment with "GPS" in it
# (removed), a comment (removed), then the start of the image data.
JFIF = b"\xff\xe0\x00\x06JFIF"
EXIF = b"\xff\xe1\x00\x0aExif GPS"
COMMENT = b"\xff\xfe\x00\x06note"
SCAN = b"\xff\xda\x00\x04\x01\x02image-bytes\xff\xd9"
PHOTO = b"\xff\xd8" + JFIF + EXIF + COMMENT + SCAN


def _evaluation(span="go", comment="Watch your past tense."):
    return {
        "annotations": [
            {"code": "VT", "span_text": span, "occurrence": 1, "correction": "went", "explanation": "Past."},
        ],
        "comment": comment,
    }


@pytest.fixture
def bucket(monkeypatch):
    """Stands in for the private photo bucket: {path: bytes}."""
    store: dict[str, bytes] = {}
    monkeypatch.setattr("api.app.photos.upload", lambda path, data: store.__setitem__(path, data))
    monkeypatch.setattr("api.app.photos.download", lambda path: store[path])
    monkeypatch.setattr("api.app.photos.delete", lambda path: store.pop(path))
    monkeypatch.setattr("api.app.photos.signed_url", lambda path: f"https://signed.example/{path}")
    return store


def _assigned(harness):  # noqa: F811
    """A writing exercise assigned to student s1, as the teacher."""
    harness.result = WRITING
    response = client.post(
        "/exercises/generate", json={"student_id": "s1", "kind": "writing", "description": "weekend"}, headers=AUTH
    )
    assert response.status_code == 200, response.text
    exercise_id = response.json()["exercise_id"]
    response = client.post(f"/exercises/{exercise_id}/assign", json={"answers_and_concepts_checked": True}, headers=AUTH)
    assert response.status_code == 200, response.text
    return exercise_id


def _typed_and_submitted(monkeypatch, harness):  # noqa: F811
    exercise_id = _assigned(harness)
    as_student(monkeypatch, student_id="s1")
    response = client.post(f"/exercises/{exercise_id}/submit", json={"answers": {"text": TYPED}}, headers=AUTH)
    assert response.status_code == 200, response.text
    become_teacher(monkeypatch)
    return exercise_id


def _evaluate(exercise_id, harness, result=None, note=""):  # noqa: F811
    harness.result = result or _evaluation()
    return client.post(f"/exercises/{exercise_id}/evaluate", json={"note": note}, headers=AUTH)


def _released(monkeypatch, harness):  # noqa: F811
    exercise_id = _typed_and_submitted(monkeypatch, harness)
    client.put(f"/exercises/{exercise_id}/scrubbed", json={"scrubbed_answers": {"text": SCRUBBED}}, headers=AUTH)
    assert _evaluate(exercise_id, harness).status_code == 200
    assert client.post(f"/exercises/{exercise_id}/approve", headers=AUTH).status_code == 200
    assert client.post(f"/exercises/{exercise_id}/release", headers=AUTH).json()["state"] == "revision_open"
    return exercise_id


def _submission(fake_db, exercise_id):
    return fake_db.collection("submissions").document(exercise_id).get().to_dict()


# ---- generation and editing ----


def test_generate_and_edit_a_writing_exercise(fake_db, as_teacher, harness, student):  # noqa: F811
    harness.result = WRITING
    response = client.post(
        "/exercises/generate", json={"student_id": "s1", "kind": "writing", "description": "weekend"}, headers=AUTH
    )
    view = response.json()
    assert view["kind"] == "writing" and view["prompt"] == WRITING["prompt"]
    assert harness.calls[0]["kind"] == "writing"
    exercise_id = view["exercise_id"]

    edited = {**WRITING, "prompt": "Describe last Sunday.", "min_words": None}
    view = client.put(f"/exercises/{exercise_id}", json=edited, headers=AUTH).json()
    assert view["prompt"] == "Describe last Sunday." and view["min_words"] is None

    too_few = {**WRITING, "min_words": 200, "max_words": 100}
    assert client.put(f"/exercises/{exercise_id}", json=too_few, headers=AUTH).status_code == 422
    # A writing exercise can't be turned into a grammar one by editing.
    grammar = {"kind": "grammar", "title": "x", "items": [{"id": "i1", "type": "short_answer", "prompt": "Why?"}]}
    assert client.put(f"/exercises/{exercise_id}", json=grammar, headers=AUTH).status_code == 422


def test_wrong_kind_from_the_ai_is_rejected(fake_db, as_teacher, harness, student):  # noqa: F811
    harness.result = WRITING  # but grammar was asked for
    response = client.post("/exercises/generate", json={"student_id": "s1", "description": "x"}, headers=AUTH)
    assert response.status_code == 502
    assert fake_db.collection("exercises").stream() == []


# ---- typed path through to revision ----


def test_typed_writing_full_flow(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    exercise_id = _assigned(harness)

    as_student(monkeypatch, student_id="s1")
    view = client.get(f"/exercises/{exercise_id}", headers=AUTH).json()
    assert view["kind"] == "writing" and view["prompt"] == WRITING["prompt"] and view["max_words"] == 150
    assert client.put(f"/exercises/{exercise_id}/answers", json={"answers": {"text": "On"}}, headers=AUTH).status_code == 200
    bad_shape = {"answers": {"i1": "x"}}
    assert client.put(f"/exercises/{exercise_id}/answers", json=bad_shape, headers=AUTH).status_code == 422
    assert client.post(f"/exercises/{exercise_id}/submit", json={"answers": {"text": TYPED}}, headers=AUTH).status_code == 200

    become_teacher(monkeypatch)
    view = client.get(f"/exercises/{exercise_id}", headers=AUTH).json()
    assert view["state"] == "scrub_review" and view["final_source"] == "typed"
    assert view["scrubbed_answers"] == {"text": TYPED}

    client.put(f"/exercises/{exercise_id}/scrubbed", json={"scrubbed_answers": {"text": SCRUBBED}}, headers=AUTH)
    response = _evaluate(exercise_id, harness)
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["state"] == "draft_ready"
    assert (view["evaluation"]["annotations"][0]["start"], view["evaluation"]["annotations"][0]["end"]) == (14, 16)
    # Only the scrubbed text reached the harness.
    sent = harness.calls[-1]
    assert sent["text"] == SCRUBBED and sent["prompt"] == WRITING["prompt"]
    assert "Maria" not in str(sent) and "Alex" not in str(sent)

    # The teacher recodes the annotation and edits the comment.
    edited = _evaluation(comment="Good work; check your verbs.")
    edited["annotations"][0]["code"] = "VF"
    response = client.put(f"/exercises/{exercise_id}/evaluation", json=edited, headers=AUTH)
    assert response.status_code == 200, response.text
    # A grammar-shaped evaluation doesn't fit a writing exercise.
    grammar = {"items": [{"item_id": "text", "mark": "correct", "annotations": [], "feedback": "x"}]}
    assert client.put(f"/exercises/{exercise_id}/evaluation", json=grammar, headers=AUTH).status_code == 422

    assert client.post(f"/exercises/{exercise_id}/approve", headers=AUTH).status_code == 200
    job = fake_db.collection("jobs").document(_submission(fake_db, exercise_id)["evaluation_job_id"]).get().to_dict()
    assert job["teacher_action"] == "edited"  # no marks in writing, so never "overridden"

    assert client.post(f"/exercises/{exercise_id}/release", headers=AUTH).json()["state"] == "revision_open"

    # The student sees their evaluated text, codes and the comment only.
    as_student(monkeypatch, student_id="s1")
    view = client.get(f"/exercises/{exercise_id}", headers=AUTH).json()
    assert view["state"] == "revision_open"
    assert view["answer_text"] == SCRUBBED
    assert view["spans"] == [{"start": 14, "end": 16, "code": "VF", "meaning": view["spans"][0]["meaning"]}]
    assert view["comment"] == "Good work; check your verbs."
    for hidden in ("went", "Past.", "correction", "explanation", "photo", "transcription"):
        assert hidden not in str(view)


def test_writing_with_no_errors_has_nothing_to_revise(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    exercise_id = _typed_and_submitted(monkeypatch, harness)
    _evaluate(exercise_id, harness, result={"annotations": [], "comment": "No errors."})
    client.post(f"/exercises/{exercise_id}/approve", headers=AUTH)
    assert client.post(f"/exercises/{exercise_id}/release", headers=AUTH).json()["state"] == "released"


def test_revision_round(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    exercise_id = _released(monkeypatch, harness)

    as_student(monkeypatch, student_id="s1")
    url = f"/exercises/{exercise_id}/revision"
    assert client.put(url, json={"edits": {"0": "wen"}}, headers=AUTH).status_code == 200
    assert client.put(url, json={"edits": {"5": "x"}}, headers=AUTH).status_code == 422  # no such span
    view = client.get(f"/exercises/{exercise_id}", headers=AUTH).json()
    assert view["revision_edits"] == {"0": "wen"}  # autosaved, resumes

    assert client.post(f"{url}/submit", json={"edits": {"0": "went"}}, headers=AUTH).status_code == 200
    # One round only: locked after submit.
    assert client.put(url, json={"edits": {"0": "goes"}}, headers=AUTH).status_code == 409
    assert client.post(f"{url}/submit", json={"edits": {"0": "goes"}}, headers=AUTH).status_code == 409
    view = client.get(f"/exercises/{exercise_id}", headers=AUTH).json()
    assert view["state"] == "revision_submitted"
    assert view["revised_text"] == SCRUBBED.replace(" go ", " went ")
    assert "outcomes" not in str(view)

    # Students can't mark outcomes, and other students can't revise.
    assert client.put(f"{url}/outcomes", json={"outcomes": {"0": "fixed"}}, headers=AUTH).status_code == 403
    as_student(monkeypatch, student_id="s2", uid="u2")
    assert client.put(url, json={"edits": {"0": "x"}}, headers=AUTH).status_code == 404

    become_teacher(monkeypatch)
    revision = client.get(f"/exercises/{exercise_id}", headers=AUTH).json()["revision"]
    assert revision["edits"] == {"0": "went"}
    assert revision["changed"] == [{"index": "0", "start": 14, "end": 18}]
    assert client.put(f"{url}/outcomes", json={"outcomes": {"1": "fixed"}}, headers=AUTH).status_code == 422
    response = client.put(f"{url}/outcomes", json={"outcomes": {"0": "fixed"}}, headers=AUTH)
    assert response.json()["revision"]["outcomes"] == {"0": "fixed"}
    # The original and the annotations are untouched.
    submission = _submission(fake_db, exercise_id)
    assert submission["answers"]["text"] == TYPED
    assert submission["scrubbed_answers"]["text"] == SCRUBBED


def test_unchanged_spans_are_not_attempts(monkeypatch, fake_db, as_teacher, harness, student):  # noqa: F811
    exercise_id = _released(monkeypatch, harness)
    as_student(monkeypatch, student_id="s1")
    client.post(f"/exercises/{exercise_id}/revision/submit", json={"edits": {"0": "go"}}, headers=AUTH)
    assert _submission(fake_db, exercise_id)["revision"]["edits"] == {}


def test_apply_revision_handles_spans_in_any_order():
    text = "I go to scool."
    annotations = [{"start": 8, "end": 13}, {"start": 2, "end": 4}]  # "scool", "go"
    revised, changed = apply_revision(text, annotations, {"0": "school", "1": "went"})
    assert revised == "I went to school."
    assert changed == [{"index": "1", "start": 2, "end": 6}, {"index": "0", "start": 10, "end": 16}]
    # Clearing a span (deleting unnecessary words) is a change too.
    assert apply_revision(text, annotations, {"1": ""})[0] == "I  to scool."


# ---- handwriting ----


def test_metadata_is_stripped_from_photos():
    clean = strip_jpeg_metadata(PHOTO)
    assert clean == b"\xff\xd8" + JFIF + SCAN
    assert b"GPS" not in clean and b"note" not in clean
    for not_a_jpeg in (b"GIF89a....", b"\xff\xd8\xff\xe1\x00\xff"):
        with pytest.raises(ValueError):
            strip_jpeg_metadata(not_a_jpeg)


def test_handwritten_path(monkeypatch, fake_db, as_teacher, harness, student, bucket):  # noqa: F811
    exercise_id = _assigned(harness)
    # The student starts typing but writes on paper instead.
    as_student(monkeypatch, student_id="s1")
    client.put(f"/exercises/{exercise_id}/answers", json={"answers": {"text": "On sat"}}, headers=AUTH)

    become_teacher(monkeypatch)
    url = f"/exercises/{exercise_id}/photos"
    jpeg = {"Content-Type": "image/jpeg", **AUTH}
    assert client.post(url, content=b"not a photo", headers=jpeg).status_code == 422
    for count in (1, 2):
        assert client.post(url, content=PHOTO, headers=jpeg).json()["photo_count"] == count
    assert len(bucket) == 2
    assert all(b"GPS" not in data for data in bucket.values())  # stored without metadata
    assert all(path.startswith(f"s1/{exercise_id}/") for path in bucket)
    links = client.get(url, headers=AUTH).json()
    assert [link["page"] for link in links] == [1, 2] and links[0]["url"].startswith("https://signed.example/")

    harness.result = {"pages": [{"page": 1, "text": TRANSCRIBED}, {"page": 2, "text": "The end."}]}
    response = client.post(f"/exercises/{exercise_id}/transcribe", headers=AUTH)
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["state"] == "transcript_review"
    assert view["transcription"] == TRANSCRIBED + "\n\nThe end."
    assert len(harness.calls[-1]["pages"]) == 2 and "Alex" not in str(harness.calls[-1])

    # Transcribing locked the student's typed answer.
    as_student(monkeypatch, student_id="s1")
    assert client.put(f"/exercises/{exercise_id}/answers", json={"answers": {"text": "x"}}, headers=AUTH).status_code == 409
    # Students never get the teacher's photos or the transcription, and
    # can't add photos once it's locked.
    assert client.get(url, headers=AUTH).json() == []
    assert client.post(url, content=PHOTO, headers=jpeg).status_code == 409
    assert len(bucket) == 2
    assert TRANSCRIBED not in str(client.get(f"/exercises/{exercise_id}", headers=AUTH).json())

    become_teacher(monkeypatch)
    corrected = TRANSCRIBED.replace("[?]", "Tom")
    client.put(f"/exercises/{exercise_id}/transcription", json={"text": corrected}, headers=AUTH)
    view = client.post(f"/exercises/{exercise_id}/final-source", json={"source": "photo"}, headers=AUTH).json()
    assert view["state"] == "scrub_review" and view["final_source"] == "photo"
    assert view["scrubbed_answers"] == {"text": corrected}
    job_id = _submission(fake_db, exercise_id)["transcription_job_id"]
    assert fake_db.collection("jobs").document(job_id).get().to_dict()["teacher_action"] == "edited"

    # Evaluation gets the scrubbed transcription; the typed draft is kept.
    assert _evaluate(exercise_id, harness, result=_evaluation(span="visit")).status_code == 200
    assert harness.calls[-1]["text"] == corrected
    assert _submission(fake_db, exercise_id)["answers"]["text"] == "On sat"

    # Switching back to the typed version discards that evaluation.
    view = client.post(f"/exercises/{exercise_id}/final-source", json={"source": "typed"}, headers=AUTH).json()
    assert view["state"] == "scrub_review" and view["evaluation"] is None
    assert view["scrubbed_answers"] == {"text": "On sat"}


def test_student_photos(monkeypatch, fake_db, as_teacher, harness, student, bucket):  # noqa: F811
    exercise_id = _assigned(harness)
    url = f"/exercises/{exercise_id}/photos"
    jpeg = {"Content-Type": "image/jpeg", **AUTH}
    client.post(url, content=PHOTO, headers=jpeg)  # the teacher adds a page first

    as_student(monkeypatch, student_id="s1")
    assert client.post(url, content=b"not a photo", headers=jpeg).status_code == 422
    links = client.post(url, content=PHOTO, headers=jpeg).json()
    links = client.post(url, content=PHOTO, headers=jpeg).json()
    # Only their own two pages, numbered from 1 - never the teacher's.
    assert [link["page"] for link in links] == [1, 2]
    teachers_path = _submission(fake_db, exercise_id)["photos"][0]["path"]
    assert teachers_path not in str(links)
    assert len(bucket) == 3 and all(b"GPS" not in data for data in bucket.values())
    assert _submission(fake_db, exercise_id)["state"] == "in_progress"

    # Starting again removes only the student's pages.
    assert client.delete(url, headers=AUTH).json() == []
    assert list(bucket) == [teachers_path]
    client.post(url, content=PHOTO, headers=jpeg)

    # Another student can't see or touch them.
    as_student(monkeypatch, student_id="s2", uid="student-uid-2")
    assert client.get(url, headers=AUTH).status_code == 404
    assert client.post(url, content=PHOTO, headers=jpeg).status_code == 404
    assert client.delete(url, headers=AUTH).status_code == 404

    # Submitting locks the photos: hidden from the student, no changes.
    as_student(monkeypatch, student_id="s1")
    assert client.post(f"/exercises/{exercise_id}/submit", json={"answers": {"text": ""}}, headers=AUTH).status_code == 200
    assert client.get(url, headers=AUTH).json() == []
    assert client.post(url, content=PHOTO, headers=jpeg).status_code == 409
    assert client.delete(url, headers=AUTH).status_code == 409
    assert len(bucket) == 2  # the refused upload wasn't kept

    # The teacher sees both pages and transcribes as usual.
    become_teacher(monkeypatch)
    assert len(client.get(url, headers=AUTH).json()) == 2
    harness.result = {"pages": [{"page": 1, "text": "a"}, {"page": 2, "text": TRANSCRIBED}]}
    assert client.post(f"/exercises/{exercise_id}/transcribe", headers=AUTH).json()["state"] == "transcript_review"


def test_student_photos_only_on_writing(monkeypatch, fake_db, as_teacher, harness, student, bucket):  # noqa: F811
    harness.result = {"kind": "grammar", "title": "x", "items": [{"id": "i1", "type": "short_answer", "prompt": "Why?"}]}
    exercise_id = client.post("/exercises/generate", json={"student_id": "s1", "description": "x"}, headers=AUTH).json()["exercise_id"]
    client.post(f"/exercises/{exercise_id}/assign", json={"answers_and_concepts_checked": True}, headers=AUTH)
    as_student(monkeypatch, student_id="s1")
    jpeg = {"Content-Type": "image/jpeg", **AUTH}
    assert client.post(f"/exercises/{exercise_id}/photos", content=PHOTO, headers=jpeg).status_code == 409
    assert bucket == {}


def test_failed_transcription_loses_nothing(monkeypatch, fake_db, as_teacher, harness, student, bucket):  # noqa: F811
    exercise_id = _assigned(harness)
    client.post(f"/exercises/{exercise_id}/photos", content=PHOTO, headers={"Content-Type": "image/jpeg", **AUTH})
    harness.result = {"pages": [{"page": 1, "text": "a"}, {"page": 2, "text": "b"}]}  # 2 pages for 1 photo
    assert client.post(f"/exercises/{exercise_id}/transcribe", headers=AUTH).status_code == 502
    assert _submission(fake_db, exercise_id)["state"] == "assigned"  # the student can still type


def test_photos_need_a_writing_exercise_before_evaluation(monkeypatch, fake_db, as_teacher, harness, student, bucket):  # noqa: F811
    exercise_id = _released(monkeypatch, harness)
    jpeg = {"Content-Type": "image/jpeg", **AUTH}
    assert client.post(f"/exercises/{exercise_id}/photos", content=PHOTO, headers=jpeg).status_code == 409
    assert client.post(f"/exercises/{exercise_id}/transcribe", headers=AUTH).status_code == 409

    fresh = _assigned(harness)
    assert client.post(f"/exercises/{fresh}/transcribe", headers=AUTH).status_code == 409  # no photos yet
    client.post(f"/exercises/{fresh}/photos", content=PHOTO, headers=jpeg)
    assert client.delete(f"/exercises/{fresh}/photos", headers=AUTH).json()["photo_count"] == 0
    assert bucket == {}
