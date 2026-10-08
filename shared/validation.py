"""Validates annotation spans against the actual text they refer to.

Separate from shared/schemas.py because this needs the source text, which
isn't part of the Annotation object itself - see docs/HARNESS_SPEC.md
section 3. Used by the harness (before returning a result) and the API
(re-validating independently).
"""

from .schemas import Annotation


class SpanError(ValueError):
    pass


def resolve_span(text: str, span_text: str, occurrence: int) -> tuple[int, int]:
    """Returns the (start, end) character offsets of the `occurrence`-th
    (1-based) occurrence of span_text in text. Raises SpanError if there
    are fewer than `occurrence` occurrences."""
    start = -1
    for _ in range(occurrence):
        start = text.find(span_text, start + 1)
        if start == -1:
            raise SpanError(f"'{span_text}' occurrence {occurrence} not found in text")
    return start, start + len(span_text)


def resolve_annotations(annotations: list[Annotation], text: str) -> list[tuple[int, int]]:
    """Resolves every annotation's span against text and rejects the whole
    set if any span is missing or any two spans overlap - a span not
    found, an unknown code, or overlapping spans means the annotation set
    is rejected (docs/HARNESS_SPEC.md section 3). Unknown codes are
    already rejected at parse time by the Annotation schema itself."""
    spans = [resolve_span(text, a.span_text, a.occurrence) for a in annotations]
    for (s1, e1), (s2, e2) in zip(sorted(spans), sorted(spans)[1:]):
        if s2 < e1:
            raise SpanError(f"overlapping annotation spans: {(s1, e1)} and {(s2, e2)}")
    return spans
