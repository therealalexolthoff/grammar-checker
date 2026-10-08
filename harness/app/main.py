"""Harness service entry point.

The five operations (generate_exercise, transcribe, evaluate_exercise,
evaluate_writing, generate_lesson) - see docs/HARNESS_SPEC.md and
app/operations.py.

Reminder for every future change to this service: no database or storage
access, ever, and never log student text or images.
"""

from fastapi import FastAPI

from shared.schemas import (
    EvaluateExerciseRequest,
    EvaluateExerciseResponse,
    EvaluateWritingRequest,
    EvaluateWritingResponse,
    GenerateExerciseRequest,
    GenerateExerciseResponse,
    GenerateLessonRequest,
    GenerateLessonResponse,
    TranscribeRequest,
    TranscribeResponse,
)

from . import operations

app = FastAPI(title="ESL Tool Harness")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/generate_exercise", response_model=GenerateExerciseResponse)
def generate_exercise(req: GenerateExerciseRequest) -> GenerateExerciseResponse:
    return operations.generate_exercise(req)


@app.post("/transcribe", response_model=TranscribeResponse)
def transcribe(req: TranscribeRequest) -> TranscribeResponse:
    return operations.transcribe(req)


@app.post("/evaluate_exercise", response_model=EvaluateExerciseResponse)
def evaluate_exercise(req: EvaluateExerciseRequest) -> EvaluateExerciseResponse:
    return operations.evaluate_exercise(req)


@app.post("/evaluate_writing", response_model=EvaluateWritingResponse)
def evaluate_writing(req: EvaluateWritingRequest) -> EvaluateWritingResponse:
    return operations.evaluate_writing(req)


@app.post("/generate_lesson", response_model=GenerateLessonResponse)
def generate_lesson(req: GenerateLessonRequest) -> GenerateLessonResponse:
    return operations.generate_lesson(req)
