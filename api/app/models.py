"""Pydantic request/response schemas for the API."""

from typing import Annotated

from pydantic import BaseModel, Field


class StudentCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8)


class ResetPasswordRequest(BaseModel):
    password: str = Field(min_length=8)


class DeleteStudentRequest(BaseModel):
    confirm_username: str


class StudentPublic(BaseModel):
    student_id: str
    username: str
    active: bool


# ---- exercises (Phase 4) ----

# Generous limits that still stop runaway input from reaching Firestore or
# the harness (the harness bills per token).
_MAX_DESCRIPTION = 2000
_MAX_ANSWER = 5000

AnswerText = Annotated[str, Field(max_length=_MAX_ANSWER)]
# fill_blank: {blank id: text}; reorder: chunk indexes; short_answer: text.
# See api/app/grading.py for what each shape means.
Answer = dict[str, AnswerText] | list[int] | AnswerText


class GenerateExerciseBody(BaseModel):
    student_id: str
    description: str = Field(min_length=1, max_length=_MAX_DESCRIPTION)


class RegenerateBody(BaseModel):
    note: str = Field(default="", max_length=_MAX_DESCRIPTION)


class AssignBody(BaseModel):
    # The approval checklist (docs/REQUIREMENTS.md FR-11): the teacher must
    # confirm they checked every answer key and concept code. The screen
    # only enables Assign once each item is ticked; the API insists too.
    answers_and_concepts_checked: bool


class AnswersBody(BaseModel):
    answers: dict[str, Answer]


class SpanView(BaseModel):
    """An error span as a student sees it: where it is, its code, and what
    the code means - never the correction or explanation (FR-21)."""

    start: int
    end: int
    code: str
    meaning: str


class ScrubbedBody(BaseModel):
    # {short-answer item id: the teacher's scrubbed copy of the answer}
    scrubbed_answers: dict[str, AnswerText]


class EvaluateBody(BaseModel):
    note: str = Field(default="", max_length=_MAX_DESCRIPTION)  # regenerate note (FR-20)


class StudentItemView(BaseModel):
    """One exercise item as a student may see it. Answer keys, concept
    codes and explanations are absent before release. The student view is
    serialized through this model, so a field not listed here can never
    reach a student even if the code building it made a mistake."""

    id: str
    type: str
    text: str | None = None  # fill_blank
    blank_ids: list[str] | None = None  # fill_blank, in marker order
    chunks: list[str] | None = None  # reorder
    prompt: str | None = None  # short_answer
    # Only after release:
    correct: bool | None = None
    correct_answer: dict[str, str] | list[str] | None = None  # only for wrong items
    explanation: str | None = None
    # Short answers, only after release:
    mark: str | None = None  # correct / partial / incorrect
    feedback: str | None = None
    answer_text: str | None = None  # the evaluated (scrubbed) text the spans point into
    spans: list[SpanView] | None = None


class StudentExerciseView(BaseModel):
    exercise_id: str
    title: str
    state: str
    answers: dict[str, Answer]
    items: list[StudentItemView]


class StudentExerciseSummary(BaseModel):
    exercise_id: str
    title: str
    state: str
