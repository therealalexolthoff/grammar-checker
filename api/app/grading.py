"""Deterministic grading of fill_blank and reorder items.

docs/REQUIREMENTS.md FR-16: comparison is strict on characters (case and
punctuation count) after trimming and collapsing repeated whitespace.
short_answer items are not graded here - they go through scrubbing and
evaluation instead (Phase 5).

Answer shapes, as the student screen sends them:
- fill_blank:   {"<blank id>": "typed text", ...}
- reorder:      [chunk index, chunk index, ...] in the order the student
                placed them (indexes, not chunk text, because an item can
                have two identical chunks)
- short_answer: "typed text"
"""

from shared.schemas import FillBlankItem, GrammarExerciseItem, ReorderItem


def normalize(text: str) -> str:
    """Trims and collapses every run of whitespace to one space. Nothing
    else - case and punctuation stay exactly as typed."""
    return " ".join(text.split())


def grade_fill_blank(item: FillBlankItem, answer: object) -> bool:
    """Correct only if every blank matches one of its accepted answers."""
    if not isinstance(answer, dict):
        return False
    for blank in item.blanks:
        typed = answer.get(blank.id)
        if not isinstance(typed, str):
            return False
        if normalize(typed) not in {normalize(a) for a in blank.accepted}:
            return False
    return True


def grade_reorder(item: ReorderItem, answer: object) -> bool:
    """Correct only if the placed chunks, in order, equal an accepted order.
    Each chunk must be used exactly once."""
    if not isinstance(answer, list) or sorted(answer) != list(range(len(item.chunks))):
        return False
    placed = [item.chunks[i] for i in answer]
    return placed in item.accepted_orders


def grade_items(items: list[GrammarExerciseItem], answers: dict) -> dict[str, bool]:
    """Returns {item id: correct?} for every fill_blank and reorder item.
    A missing answer counts as incorrect."""
    results = {}
    for item in items:
        if isinstance(item, FillBlankItem):
            results[item.id] = grade_fill_blank(item, answers.get(item.id))
        elif isinstance(item, ReorderItem):
            results[item.id] = grade_reorder(item, answers.get(item.id))
    return results
