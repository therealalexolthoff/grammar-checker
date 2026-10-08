"""Pydantic schemas for the five harness operations.

Single source of truth for both services - the harness builds these, the
API re-validates them independently (docs/HARNESS_SPEC.md: "the API
re-validates independently"). Most of the structural rules from
HARNESS_SPEC.md section 4 are enforced right here as field/model
validators; the one check that needs text living outside the annotation
itself (span resolution) is in shared/validation.py instead.
"""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .taxonomy import ErrorCode

# The prompt template version, recorded on every job (docs/HARNESS_SPEC.md
# section 8). Lives here, not in the harness, because the API sends it on
# every request - one definition means the two services can't disagree.
# Bump it whenever any prompt in harness/app/prompts.py changes.
PROMPT_VERSION = "v3"

# How a fill_blank item's text marks each blank: three or more underscores.
# The student screen puts one input box at each marker, in order.
BLANK_MARKER = re.compile(r"_{3,}")


class StrictModel(BaseModel):
    """No extra properties, anywhere - part of forcing Claude's output into
    the schema exactly (docs/HARNESS_SPEC.md section 8: "Output is forced
    into a JSON schema ... for format only")."""

    model_config = ConfigDict(extra="forbid")


class ContextBundle(StrictModel):
    """See docs/ARCHITECTURE.md section 7 (the context assembler)."""

    profile_summary: str = ""
    teacher_notes: str = ""
    recent_titles: list[str] = Field(default_factory=list)
    excerpts: list[str] = Field(default_factory=list)


class BaseHarnessRequest(StrictModel):
    student_id: str
    request_id: str
    prompt_version: str


# ---- generate_exercise ----


class Blank(StrictModel):
    id: str
    accepted: list[str] = Field(min_length=1)


class FillBlankItem(StrictModel):
    id: str
    type: Literal["fill_blank"] = "fill_blank"
    text: str
    blanks: list[Blank] = Field(min_length=1)
    concept: ErrorCode
    explanation: str

    @model_validator(mode="after")
    def check_blank_markers(self) -> "FillBlankItem":
        markers = len(BLANK_MARKER.findall(self.text))
        if markers != len(self.blanks):
            raise ValueError(
                f"text has {markers} blank marker(s) (___) but {len(self.blanks)} blank(s) are defined"
            )
        return self


class ReorderItem(StrictModel):
    id: str
    type: Literal["reorder"] = "reorder"
    chunks: list[str] = Field(min_length=2)
    accepted_orders: list[list[str]] = Field(min_length=1)
    concept: ErrorCode
    explanation: str

    @model_validator(mode="after")
    def check_permutations(self) -> "ReorderItem":
        chunk_multiset = sorted(self.chunks)
        for order in self.accepted_orders:
            if sorted(order) != chunk_multiset:
                raise ValueError(
                    f"accepted_orders entry {order} is not a permutation of chunks {self.chunks}"
                )
        return self


class ShortAnswerItem(StrictModel):
    id: str
    type: Literal["short_answer"] = "short_answer"
    prompt: str


GrammarExerciseItem = FillBlankItem | ReorderItem | ShortAnswerItem


class GrammarExerciseDraft(StrictModel):
    kind: Literal["grammar"] = "grammar"
    title: str
    items: list[GrammarExerciseItem] = Field(min_length=1)

    @model_validator(mode="after")
    def check_unique_ids(self) -> "GrammarExerciseDraft":
        ids = [item.id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError(f"item ids must be unique, got {ids}")
        return self


class WritingExerciseDraft(StrictModel):
    kind: Literal["writing"] = "writing"
    title: str
    prompt: str
    min_words: int | None = None
    max_words: int | None = None


class GenerateExerciseRequest(BaseHarnessRequest):
    kind: Literal["grammar", "writing"]
    description: str
    context: ContextBundle = Field(default_factory=ContextBundle)
    regenerate_note: str | None = None
    item_types: list[Literal["fill_blank", "reorder", "short_answer"]] | None = None


# ---- transcribe ----


class TranscriptionPage(StrictModel):
    page: int = Field(ge=1)
    text: str


class TranscribeResult(StrictModel):
    pages: list[TranscriptionPage] = Field(min_length=1)


class TranscribeRequest(BaseHarnessRequest):
    pages: list[str] = Field(min_length=1)  # base64 image data, in page order


# ---- evaluate_exercise / evaluate_writing ----


class Annotation(StrictModel):
    code: ErrorCode
    span_text: str
    occurrence: int = Field(ge=1)
    correction: str
    explanation: str


class ScrubbedShortAnswer(StrictModel):
    item_id: str
    prompt: str
    response: str


class EvaluateExerciseRequest(BaseHarnessRequest):
    items: list[ScrubbedShortAnswer] = Field(min_length=1)
    # The teacher's optional note when regenerating an evaluation (FR-20).
    regenerate_note: str | None = None


class EvaluateExerciseItemResult(StrictModel):
    item_id: str
    mark: Literal["correct", "partial", "incorrect"]
    annotations: list[Annotation] = Field(default_factory=list)
    feedback: str


class EvaluateExerciseResult(StrictModel):
    items: list[EvaluateExerciseItemResult] = Field(min_length=1)


class EvaluateWritingRequest(BaseHarnessRequest):
    prompt: str
    text: str


class EvaluateWritingResult(StrictModel):
    annotations: list[Annotation] = Field(default_factory=list)
    comment: str


# ---- generate_lesson ----


class LessonExample(StrictModel):
    incorrect: str
    correct: str
    note: str


class LessonDraft(StrictModel):
    title: str
    explanation: str
    examples: list[LessonExample] = Field(min_length=1)
    word_count: int = Field(ge=200, le=400)


class GenerateLessonRequest(BaseHarnessRequest):
    description: str
    context: ContextBundle = Field(default_factory=ContextBundle)


# ---- response envelope ----


class HarnessMeta(StrictModel):
    """Every harness response carries these - docs/HARNESS_SPEC.md section 1."""

    model: str
    tokens_in: int = Field(ge=0)
    tokens_out: int = Field(ge=0)
    tokens_cached: int = Field(ge=0, default=0)
    latency_ms: float = Field(ge=0)


class GenerateExerciseResponse(HarnessMeta):
    result: GrammarExerciseDraft | WritingExerciseDraft = Field(discriminator="kind")


class TranscribeResponse(HarnessMeta):
    result: TranscribeResult


class EvaluateExerciseResponse(HarnessMeta):
    result: EvaluateExerciseResult


class EvaluateWritingResponse(HarnessMeta):
    result: EvaluateWritingResult


class GenerateLessonResponse(HarnessMeta):
    result: LessonDraft
