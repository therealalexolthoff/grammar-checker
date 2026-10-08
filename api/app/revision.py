"""The student's one revision round on a writing exercise (FR-26, FR-27).

Plain functions on stored data, no database access - the endpoints that
use them are in writing.py.

After release, each flagged span can be retyped by the student. Edits are
kept separately from the evaluated text and its annotations, keyed by the
span's position in the annotation list ("0", "1", ... - Firestore map
keys must be strings). The evaluation is frozen once released, so those
positions never change. The revised text is worked out from the three
whenever it's needed, never stored.
"""

from fastapi import HTTPException

from .models import WRITING_KEY


def check_edit_keys(edits: dict[str, str], annotation_count: int) -> None:
    """Every edit must point at a real flagged span."""
    valid = {str(i) for i in range(annotation_count)}
    unknown = sorted(set(edits) - valid)
    if unknown:
        raise HTTPException(status_code=422, detail=f"no flagged span {unknown[0]!r}")


def changed_edits(edits: dict[str, str], text: str, annotations: list[dict]) -> dict[str, str]:
    """Drops edits that leave a span exactly as it was - the student
    opened that span but didn't change it, so it wasn't attempted.
    (Clearing a span is a real change: deleting the words can be the fix.)"""
    return {
        key: new
        for key, new in edits.items()
        if new != text[annotations[int(key)]["start"] : annotations[int(key)]["end"]]
    }


def apply_revision(text: str, annotations: list[dict], edits: dict[str, str]) -> tuple[str, list[dict]]:
    """Returns the revised text - `text` with each edited span replaced by
    the student's new words - and where each replacement ended up in it,
    as [{"index": "2", "start": 10, "end": 14}, ...], so the changes can
    be highlighted."""
    revised = ""
    changed = []
    at = 0  # how far through the original text has been copied
    for index, annotation in sorted(enumerate(annotations), key=lambda pair: pair[1]["start"]):
        new = edits.get(str(index))
        if new is None:
            continue
        revised += text[at : annotation["start"]]
        changed.append({"index": str(index), "start": len(revised), "end": len(revised) + len(new)})
        revised += new
        at = annotation["end"]
    revised += text[at:]
    return revised, changed


def revision_view(submission: dict) -> dict | None:
    """The revision as the screens need it, or None if the student hasn't
    started one."""
    revision = submission.get("revision")
    if not revision:
        return None
    text = submission["scrubbed_answers"][WRITING_KEY]
    revised_text, changed = apply_revision(text, submission["evaluation"]["annotations"], revision["edits"])
    return {
        "edits": revision["edits"],
        "submitted_at": revision.get("submitted_at"),
        "outcomes": revision.get("outcomes", {}),
        "revised_text": revised_text,
        "changed": changed,
    }
