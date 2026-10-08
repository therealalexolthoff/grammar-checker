"""The golden set itself must be valid: every teacher annotation points at
real text and uses a real code, or the runner's comparison means nothing."""

import json
from pathlib import Path

from shared.schemas import Annotation
from shared.validation import resolve_annotations

SET = Path(__file__).resolve().parents[2] / "golden" / "synthetic.json"


def test_synthetic_set_is_valid_and_labelled():
    golden = json.loads(SET.read_text())
    assert golden["label"].startswith("SYNTHETIC")
    for passage in golden["passages"]:
        annotations = [Annotation(**a, correction="", explanation="") for a in passage["annotations"]]
        resolve_annotations(annotations, passage["text"])  # raises if a span is missing or overlapping
