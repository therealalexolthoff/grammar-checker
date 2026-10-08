import pytest

from api.app import jobs, spend
from api.app.settings import get_settings


def test_create_and_complete_job(fake_db):
    job_id = jobs.create_job("generate_exercise", "s1", "v1")
    jobs.complete_job(
        job_id,
        model="mock",
        tokens_in=10,
        tokens_out=20,
        tokens_cached=0,
        latency_ms=5.0,
        cost_usd=0.001,
        validation_outcome="passed",
    )
    doc = fake_db.collection("jobs").document(job_id).get()
    assert doc.get("status") == "done"
    assert doc.get("cost_usd") == 0.001


def test_fail_job(fake_db):
    job_id = jobs.create_job("transcribe", "s1", "v1")
    jobs.fail_job(job_id, "boom")
    doc = fake_db.collection("jobs").document(job_id).get()
    assert doc.get("status") == "error"
    assert doc.get("validation_outcome") == "rejected"


def test_spend_accumulates(fake_db):
    assert spend.current_month_spend() == 0.0
    spend.record_spend(0.01)
    spend.record_spend(0.02)
    assert spend.current_month_spend() == pytest.approx(0.03)


def test_settings_defaults_when_doc_missing(fake_db):
    s = get_settings()
    assert s.monthly_cap_usd == 20.0
    assert s.estimated_cost_per_call_usd == 0.05
