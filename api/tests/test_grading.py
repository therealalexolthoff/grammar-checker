from shared.schemas import Blank, FillBlankItem, ReorderItem, ShortAnswerItem

from api.app.grading import grade_items, normalize

FILL = FillBlankItem(
    id="i1",
    text="She ___ to school yesterday.",
    blanks=[Blank(id="b1", accepted=["went"])],
    concept="VT",
    explanation="x",
)
REORDER = ReorderItem(
    id="i2",
    chunks=["always", "I", "eat", "breakfast"],
    accepted_orders=[["I", "always", "eat", "breakfast"]],
    concept="WO",
    explanation="x",
)
SHORT = ShortAnswerItem(id="i3", prompt="Write a sentence.")


def test_normalize_trims_and_collapses_whitespace_only():
    assert normalize("  New   York\t City \n") == "New York City"
    assert normalize("Went.") == "Went."  # punctuation and case untouched


def test_fill_blank_whitespace_forgiven_but_case_is_strict():
    assert grade_items([FILL], {"i1": {"b1": "  went "}}) == {"i1": True}
    assert grade_items([FILL], {"i1": {"b1": "Went"}}) == {"i1": False}
    assert grade_items([FILL], {"i1": {"b1": "went."}}) == {"i1": False}


def test_missing_answers_are_incorrect():
    assert grade_items([FILL, REORDER], {}) == {"i1": False, "i2": False}


def test_reorder_by_chunk_index():
    assert grade_items([REORDER], {"i2": [1, 0, 2, 3]}) == {"i2": True}
    assert grade_items([REORDER], {"i2": [0, 1, 2, 3]}) == {"i2": False}


def test_reorder_must_use_every_chunk_once():
    assert grade_items([REORDER], {"i2": [1, 0, 2]}) == {"i2": False}
    assert grade_items([REORDER], {"i2": [1, 1, 2, 3]}) == {"i2": False}


def test_reorder_with_duplicate_chunks():
    item = ReorderItem(
        id="i1",
        chunks=["the", "cat", "saw", "the", "dog"],
        accepted_orders=[["the", "cat", "saw", "the", "dog"]],
        concept="WO",
        explanation="x",
    )
    # Either "the" can go in either slot.
    assert grade_items([item], {"i1": [3, 1, 2, 0, 4]}) == {"i1": True}


def test_short_answers_are_not_graded():
    assert grade_items([SHORT], {"i3": "anything"}) == {}
