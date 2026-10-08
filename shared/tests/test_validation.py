import pytest

from shared.schemas import Annotation
from shared.validation import SpanError, resolve_annotations, resolve_span


def test_resolve_span_finds_first_occurrence():
    assert resolve_span("She go to school.", "go", 1) == (4, 6)


def test_resolve_span_finds_second_occurrence():
    text = "I go there. Later I go again."
    assert resolve_span(text, "go", 2) == (text.index("go", 5), text.index("go", 5) + 2)


def test_resolve_span_raises_when_occurrence_missing():
    with pytest.raises(SpanError):
        resolve_span("She go to school.", "went", 1)


def test_resolve_annotations_rejects_overlapping_spans():
    text = "She go to school."
    annotations = [
        Annotation(code="VT", span_text="go to", occurrence=1, correction="went to", explanation=""),
        Annotation(code="PREP", span_text="to school", occurrence=1, correction="", explanation=""),
    ]
    with pytest.raises(SpanError):
        resolve_annotations(annotations, text)


def test_resolve_annotations_accepts_non_overlapping_spans():
    text = "She go to school."
    annotations = [
        Annotation(code="VT", span_text="go", occurrence=1, correction="went", explanation=""),
        Annotation(code="M", span_text="school.", occurrence=1, correction="school.'", explanation=""),
    ]
    spans = resolve_annotations(annotations, text)
    assert spans == [(4, 6), (10, 17)]


def test_resolve_annotations_rejects_missing_span():
    text = "She go to school."
    annotations = [
        Annotation(code="CAP", span_text="School", occurrence=1, correction="school", explanation=""),
    ]
    with pytest.raises(SpanError):
        resolve_annotations(annotations, text)
