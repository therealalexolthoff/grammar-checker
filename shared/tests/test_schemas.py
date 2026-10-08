import pytest
from pydantic import ValidationError

from shared.schemas import (
    FillBlankItem,
    Blank,
    ReorderItem,
    GrammarExerciseDraft,
    ShortAnswerItem,
)


def test_reorder_item_accepts_valid_permutation():
    item = ReorderItem(
        id="i1",
        chunks=["always", "I", "eat", "breakfast"],
        accepted_orders=[["I", "always", "eat", "breakfast"]],
        concept="WO",
        explanation="word order",
    )
    assert item.type == "reorder"


def test_reorder_item_rejects_non_permutation():
    with pytest.raises(ValidationError):
        ReorderItem(
            id="i1",
            chunks=["always", "I", "eat", "breakfast"],
            accepted_orders=[["I", "always", "eat", "lunch"]],  # "lunch" not in chunks
            concept="WO",
            explanation="word order",
        )


def test_reorder_item_rejects_unknown_concept_code():
    with pytest.raises(ValidationError):
        ReorderItem(
            id="i1",
            chunks=["a", "b"],
            accepted_orders=[["a", "b"]],
            concept="NOT_A_CODE",
            explanation="x",
        )


def test_grammar_draft_rejects_duplicate_item_ids():
    item1 = ShortAnswerItem(id="i1", prompt="Write about your weekend.")
    item2 = FillBlankItem(
        id="i1",  # duplicate
        text="She ___ to school.",
        blanks=[Blank(id="b1", accepted=["went"])],
        concept="VT",
        explanation="past tense",
    )
    with pytest.raises(ValidationError):
        GrammarExerciseDraft(title="Test", items=[item1, item2])


def test_grammar_draft_requires_at_least_one_item():
    with pytest.raises(ValidationError):
        GrammarExerciseDraft(title="Test", items=[])
