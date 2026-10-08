from fastapi.testclient import TestClient

from harness.app.main import app

client = TestClient(app)

REQUEST_BASE = {"student_id": "s1", "request_id": "r1", "prompt_version": "v1"}


def test_generate_exercise_grammar():
    body = {**REQUEST_BASE, "kind": "grammar", "description": "practice past tense"}
    response = client.post("/generate_exercise", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["result"]["kind"] == "grammar"
    assert len(data["result"]["items"]) >= 1
    assert data["model"] == "mock"
    assert data["tokens_in"] > 0 and data["tokens_out"] > 0


def test_generate_exercise_writing():
    body = {**REQUEST_BASE, "kind": "writing", "description": "describe your weekend"}
    response = client.post("/generate_exercise", json=body)
    assert response.status_code == 200
    assert response.json()["result"]["kind"] == "writing"


def test_generate_exercise_honors_requested_item_types():
    body = {
        **REQUEST_BASE,
        "kind": "grammar",
        "description": "x",
        "item_types": ["short_answer"],
    }
    response = client.post("/generate_exercise", json=body)
    items = response.json()["result"]["items"]
    assert len(items) == 1
    assert items[0]["type"] == "short_answer"


def test_transcribe():
    body = {**REQUEST_BASE, "pages": ["base64page1", "base64page2"]}
    response = client.post("/transcribe", json=body)
    assert response.status_code == 200
    pages = response.json()["result"]["pages"]
    assert [p["page"] for p in pages] == [1, 2]


def test_evaluate_exercise():
    body = {
        **REQUEST_BASE,
        "items": [{"item_id": "i1", "prompt": "Write about your weekend.", "response": "I go park."}],
    }
    response = client.post("/evaluate_exercise", json=body)
    assert response.status_code == 200
    items = response.json()["result"]["items"]
    assert items[0]["item_id"] == "i1"
    assert items[0]["mark"] in ("correct", "partial", "incorrect")


def test_evaluate_writing():
    body = {**REQUEST_BASE, "prompt": "Describe your weekend.", "text": "I go to the park yesterday."}
    response = client.post("/evaluate_writing", json=body)
    assert response.status_code == 200
    assert "comment" in response.json()["result"]


def test_generate_lesson():
    body = {**REQUEST_BASE, "description": "verb tense practice"}
    response = client.post("/generate_lesson", json=body)
    assert response.status_code == 200
    result = response.json()["result"]
    assert 200 <= result["word_count"] <= 400
    assert len(result["examples"]) >= 1


def test_real_mode_calls_claude_ops(monkeypatch):
    """Real mode dispatches to claude_ops.call_claude rather than the
    mock - verified by substituting a fake that returns a canned result,
    without touching the actual Vertex client (see test_claude_ops.py for
    the repair-attempt logic itself)."""
    monkeypatch.setattr("harness.app.operations.settings.mock_mode", False)

    def fake_call_claude(*, system, user_content, output_model, validate=None):
        result = output_model(title="t", prompt="p")  # WritingExerciseDraft
        if validate is not None:
            validate(result)
        return result, {
            "model": "claude-sonnet-5",
            "tokens_in": 123,
            "tokens_out": 45,
            "tokens_cached": 0,
            "latency_ms": 10.0,
        }

    monkeypatch.setattr("harness.app.operations.call_claude", fake_call_claude)

    body = {**REQUEST_BASE, "kind": "writing", "description": "x"}
    response = client.post("/generate_exercise", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "claude-sonnet-5"
    assert data["tokens_in"] == 123
    assert data["result"]["kind"] == "writing"


def test_evaluate_regenerate_note_reaches_the_prompt():
    from harness.app import prompts
    from shared.schemas import EvaluateExerciseRequest

    req = EvaluateExerciseRequest(
        **REQUEST_BASE,
        items=[{"item_id": "i3", "prompt": "Why?", "response": "Because I go."}],
        regenerate_note="'go' is fine here",
    )
    content = prompts.evaluate_exercise_user_content(req)
    assert '<data label="regenerate_note">' in content and "'go' is fine here" in content


def test_writing_regenerate_note_reaches_the_prompt():
    from harness.app import prompts
    from shared.schemas import EvaluateWritingRequest

    req = EvaluateWritingRequest(**REQUEST_BASE, prompt="Describe a trip.", text="I go there.", regenerate_note="keep it")
    content = prompts.evaluate_writing_user_content(req)
    assert '<data label="regenerate_note">' in content and "keep it" in content
    assert "regenerate_note" in prompts.EVALUATE_WRITING_SYSTEM


def test_transcription_must_cover_every_page_in_order():
    import pytest

    from shared.validation import check_page_numbers

    check_page_numbers([1, 2], 2)
    for wrong in ([1], [2, 1], [1, 2, 3]):
        with pytest.raises(ValueError):
            check_page_numbers(wrong, 2)


def test_evaluation_of_the_wrong_items_is_rejected():
    import pytest

    from shared.validation import check_item_ids

    check_item_ids(["i1", "i2"], ["i1", "i2"])
    with pytest.raises(ValueError):
        check_item_ids(["i2", "i1"], ["i1", "i2"])
