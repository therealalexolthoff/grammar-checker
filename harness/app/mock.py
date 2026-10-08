"""Canned, schema-valid mock responses for all five operations.

Used when HARNESS_MOCK_MODE is on (see app/main.py), so the rest of the
app can be built and tested without calling Claude - docs/HARNESS_SPEC.md
section 8. Still built from the real request where it's easy to (e.g.
annotation spans reference actual substrings of the input text), so the
validation pipeline is genuinely exercised rather than trivially passed.
"""

from shared.schemas import (
    Annotation,
    Blank,
    EvaluateExerciseItemResult,
    EvaluateExerciseRequest,
    EvaluateExerciseResult,
    EvaluateWritingRequest,
    EvaluateWritingResult,
    FillBlankItem,
    GenerateExerciseRequest,
    GenerateLessonRequest,
    GrammarExerciseDraft,
    LessonDraft,
    LessonExample,
    ReorderItem,
    ShortAnswerItem,
    TranscribeRequest,
    TranscribeResult,
    TranscriptionPage,
    WritingExerciseDraft,
)

MOCK_MODEL = "mock"

_ITEM_BUILDERS = {
    "fill_blank": lambda n: FillBlankItem(
        id=f"i{n}",
        text="She ___ to school yesterday.",
        blanks=[Blank(id=f"i{n}-b1", accepted=["went"])],
        concept="VT",
        explanation="Past tense of 'go' is 'went'.",
    ),
    "reorder": lambda n: ReorderItem(
        id=f"i{n}",
        chunks=["always", "I", "eat", "breakfast"],
        accepted_orders=[["I", "always", "eat", "breakfast"]],
        concept="WO",
        explanation="Adverbs of frequency go after the subject.",
    ),
    "short_answer": lambda n: ShortAnswerItem(
        id=f"i{n}", prompt="Write two sentences about last weekend."
    ),
}


def mock_generate_exercise(req: GenerateExerciseRequest) -> GrammarExerciseDraft | WritingExerciseDraft:
    if req.kind == "writing":
        return WritingExerciseDraft(
            title="Mock writing exercise",
            prompt=f"(mock draft for: {req.description[:60]})",
            min_words=50,
            max_words=150,
        )

    types = req.item_types or ["fill_blank", "reorder"]
    items = [_ITEM_BUILDERS[t](n) for n, t in enumerate(types, start=1)]
    return GrammarExerciseDraft(title="Mock grammar exercise", items=items)


def mock_transcribe(req: TranscribeRequest) -> TranscribeResult:
    pages = [
        TranscriptionPage(page=i, text=f"(mock transcription of page {i})")
        for i in range(1, len(req.pages) + 1)
    ]
    return TranscribeResult(pages=pages)


def mock_evaluate_exercise(req: EvaluateExerciseRequest) -> EvaluateExerciseResult:
    results = []
    for item in req.items:
        words = item.response.split()
        if len(words) >= 2:
            annotations = [
                Annotation(
                    code="VT", span_text=words[0], occurrence=1,
                    correction=words[0], explanation="(mock annotation)",
                )
            ]
        else:
            annotations = []
        results.append(
            EvaluateExerciseItemResult(
                item_id=item.item_id,
                mark="partial",
                annotations=annotations,
                feedback="(mock feedback)",
            )
        )
    return EvaluateExerciseResult(items=results)


def mock_evaluate_writing(req: EvaluateWritingRequest) -> EvaluateWritingResult:
    words = req.text.split()
    annotations = (
        [Annotation(code="SP", span_text=words[0], occurrence=1, correction=words[0], explanation="(mock)")]
        if words
        else []
    )
    return EvaluateWritingResult(annotations=annotations, comment="(mock overall comment)")


def mock_generate_lesson(req: GenerateLessonRequest) -> LessonDraft:
    # "(mock lesson explanation)" is 3 words; x70 = 210, inside the 200-400
    # word_count range the schema requires.
    explanation = ("(mock lesson explanation) " * 70).strip()
    return LessonDraft(
        title="Mock lesson",
        explanation=explanation,
        examples=[LessonExample(incorrect="She go.", correct="She goes.", note="(mock)")],
        word_count=len(explanation.split()),
    )
