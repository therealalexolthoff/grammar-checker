import pytest

from api.app import harness_ops, spend
from shared.schemas import EvaluateExerciseRequest, GenerateExerciseRequest, ScrubbedShortAnswer

GENERATE_REQ = dict(
    student_id="s1", request_id="r1", prompt_version="v1", kind="grammar", description="x"
)


def _envelope(result):
    return {
        "model": "mock",
        "tokens_in": 10,
        "tokens_out": 20,
        "tokens_cached": 0,
        "latency_ms": 1.0,
        "result": result,
    }


def test_call_harness_happy_path(monkeypatch, fake_db):
    result_payload = {
        "kind": "grammar",
        "title": "t",
        "items": [{"id": "i1", "type": "short_answer", "prompt": "write something"}],
    }
    monkeypatch.setattr(
        "api.app.harness_ops.post_to_harness", lambda op, body: _envelope(result_payload)
    )

    req = GenerateExerciseRequest(**GENERATE_REQ)
    result = harness_ops.call_harness("generate_exercise", req)

    assert result.kind == "grammar"
    assert spend.current_month_spend() == 0.0  # mock model is free


def test_call_harness_records_job(monkeypatch, fake_db):
    result_payload = {"kind": "writing", "title": "t", "prompt": "p"}
    monkeypatch.setattr(
        "api.app.harness_ops.post_to_harness", lambda op, body: _envelope(result_payload)
    )

    req = GenerateExerciseRequest(**{**GENERATE_REQ, "kind": "writing"})
    harness_ops.call_harness("generate_exercise", req)

    job_docs = fake_db.collection("jobs").stream()
    assert any(
        d.get("status") == "done" and d.get("operation") == "generate_exercise" for d in job_docs
    )


def test_call_harness_rejects_invalid_annotation_span(monkeypatch, fake_db):
    req = EvaluateExerciseRequest(
        student_id="s1",
        request_id="r1",
        prompt_version="v1",
        items=[ScrubbedShortAnswer(item_id="i1", prompt="p", response="I go park.")],
    )
    bad_result = {
        "items": [
            {
                "item_id": "i1",
                "mark": "partial",
                # "went" never appears in "I go park." - an unresolvable span.
                "annotations": [
                    {
                        "code": "VT",
                        "span_text": "went",
                        "occurrence": 1,
                        "correction": "went",
                        "explanation": "",
                    }
                ],
                "feedback": "f",
            }
        ]
    }
    monkeypatch.setattr(
        "api.app.harness_ops.post_to_harness", lambda op, body: _envelope(bad_result)
    )

    with pytest.raises(harness_ops.HarnessValidationFailed):
        harness_ops.call_harness("evaluate_exercise", req)

    job_docs = fake_db.collection("jobs").stream()
    assert any(d.get("status") == "error" for d in job_docs)


def test_call_harness_respects_spend_cap(monkeypatch, fake_db):
    fake_db.collection("settings").document("global").set(
        {"monthly_cap_usd": 0.01, "estimated_cost_per_call_usd": 0.05}
    )

    called = []
    monkeypatch.setattr(
        "api.app.harness_ops.post_to_harness", lambda op, body: called.append(1)
    )

    req = GenerateExerciseRequest(**GENERATE_REQ)
    with pytest.raises(harness_ops.SpendCapReached):
        harness_ops.call_harness("generate_exercise", req)

    assert called == []  # never actually called the harness
