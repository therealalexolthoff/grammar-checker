"""Logs never contain student text (CLAUDE.md): not from an unexpected
error, and not from a failed AI call."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.app.main import app
from shared.logs import catch_unexpected_errors

from .test_exercises import AUTH, harness, student  # noqa: F401 (fixtures)
from .test_review import ORIGINAL, _evaluation, _submitted

SECRET = "My name is Maria Lopez and I live at 12 Oak Street"


def test_unexpected_errors_are_logged_without_their_message(capsys):
    demo = FastAPI()
    catch_unexpected_errors(demo)

    @demo.get("/boom")
    def boom():
        raise ValueError(SECRET)

    response = TestClient(demo).get("/boom")
    assert response.status_code == 500 and SECRET not in response.text
    out = capsys.readouterr()
    assert '"event": "unhandled_error"' in out.out and '"error_type": "ValueError"' in out.out
    assert SECRET not in out.out + out.err


def test_failed_ai_call_logs_only_the_error_type(monkeypatch, fake_db, as_teacher, harness, student, capsys):  # noqa: F811
    client = TestClient(app)
    exercise_id = _submitted(monkeypatch, harness)
    # The AI flags a span that isn't in the text: the API rejects it, and
    # the rejection message would quote the span.
    result = _evaluation(span="my sister Maria")
    harness.result = result
    capsys.readouterr()
    response = client.post(f"/exercises/{exercise_id}/evaluate", json={"note": ""}, headers=AUTH)
    assert response.status_code == 502
    out = capsys.readouterr()
    assert '"event": "harness_call_failed"' in out.out and '"error_type": "SpanError"' in out.out
    assert "Maria" not in out.out + out.err and ORIGINAL not in out.out + out.err
