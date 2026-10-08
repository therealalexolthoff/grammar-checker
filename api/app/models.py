"""Pydantic request/response schemas for the API."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from shared.schemas import GrammarExerciseDraft, LessonExample, WritingExerciseDraft


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
_MAX_ANSWER = 10_000  # a long writing response is ~1,500 words
_MAX_SPAN_EDIT = 500

AnswerText = Annotated[str, Field(max_length=_MAX_ANSWER)]

# A writing response is kept like a one-item exercise: its answer, scrubbed
# copy and so on are all stored under this key.
WRITING_KEY = "text"
# fill_blank: {blank id: text}; reorder: chunk indexes; short_answer: text.
# See api/app/grading.py for what each shape means.
Answer = dict[str, AnswerText] | list[int] | AnswerText


class GenerateExerciseBody(BaseModel):
    student_id: str
    kind: Literal["grammar", "writing"] = "grammar"
    description: str = Field(min_length=1, max_length=_MAX_DESCRIPTION)


# The teacher's edited draft: whichever kind the exercise is ("kind" decides).
ExerciseDraft = Annotated[GrammarExerciseDraft | WritingExerciseDraft, Field(discriminator="kind")]


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
    kind: str = "grammar"
    title: str
    state: str
    answers: dict[str, Answer]
    items: list[StudentItemView]  # grammar only
    # Writing only:
    prompt: str | None = None
    min_words: int | None = None
    max_words: int | None = None
    # Writing, only after release:
    answer_text: str | None = None  # the evaluated (scrubbed) text the spans point into
    spans: list[SpanView] | None = None
    comment: str | None = None
    revision_edits: dict[str, str] | None = None  # {span index: the student's new words}
    revised_text: str | None = None


# ---- writing: handwriting and revision (Phase 6) ----


class TranscriptionBody(BaseModel):
    text: str = Field(max_length=_MAX_ANSWER)


class FinalSourceBody(BaseModel):
    # Which version of the response is evaluated (FR-24).
    source: Literal["typed", "photo"]


class RevisionBody(BaseModel):
    # {span index (its position in the annotation list): the new words}
    edits: dict[str, Annotated[str, Field(max_length=_MAX_SPAN_EDIT)]]


Outcome = Literal["fixed", "unfixed", "changed_wrongly"]


class OutcomesBody(BaseModel):
    # {span index: outcome} for every span the student changed (FR-27)
    outcomes: dict[str, Outcome]


class StudentExerciseSummary(BaseModel):
    exercise_id: str
    title: str
    state: str


# ---- learner profile, notes, lessons (Phase 7) ----

_MAX_NOTES = 5000
_MAX_LESSON_TEXT = 5000


class NotesBody(BaseModel):
    teacher_notes: str = Field(max_length=_MAX_NOTES)


class GenerateLessonBody(BaseModel):
    student_id: str
    description: str = Field(min_length=1, max_length=_MAX_DESCRIPTION)


class LessonEditBody(BaseModel):
    """The teacher's edits to a draft lesson. No word-count limit here:
    200-400 words is what the AI must produce, but the teacher may trim
    or add as they see fit."""

    title: str = Field(min_length=1, max_length=200)
    explanation: str = Field(min_length=1, max_length=_MAX_LESSON_TEXT)
    examples: list[LessonExample] = Field(min_length=1, max_length=20)


class StudentLessonView(BaseModel):
    """A lesson as its student sees it. Serialized through this model, so
    the teacher's request and notes can never reach a student."""

    lesson_id: str
    title: str
    explanation: str
    examples: list[LessonExample]
    read: bool


class StudentLessonSummary(BaseModel):
    lesson_id: str
    title: str
    read: bool
