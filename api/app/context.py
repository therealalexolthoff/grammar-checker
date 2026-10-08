"""The context assembler (docs/ARCHITECTURE.md section 7): what the
harness is told about a student when it generates an exercise or a lesson.

Deterministic and kept to a fixed size. The bundle holds:
- a profile summary: the most frequent recent error codes, and how the
  student's revisions of them went;
- the teacher's notes, cut to a maximum length (the notes screen asks for
  the newest notes at the top, so the oldest are what gets cut);
- recent exercise and lesson titles, so the harness avoids repeats;
- a few scrubbed, approved excerpts showing the student's errors of the
  most frequent codes.
Never included: the username, original (unscrubbed) text, or anything
about other students. The student is known to the harness only by the
opaque id on the request.
"""

import re

from google.cloud.firestore_v1.base_query import FieldFilter

from shared.schemas import ContextBundle

from .firestore_client import get_db
from .profile import annotated_spans, compute_profile, recent_approved

TOP_CODES = 5
MAX_NOTES_CHARS = 1500
MAX_TITLES = 10
MAX_EXCERPTS = 5
MAX_EXCERPT_CHARS = 300

# Where a sentence ends: . ! or ? followed by a space, or a line break.
_SENTENCE_END = re.compile(r"[.!?](?=\s)|\n")


def profile_summary(codes: list[dict], submissions_counted: int) -> str:
    """One line per frequent code, e.g.
    "VT (Verb tense): 4 errors; revisions: 1 fixed, 1 not fixed"."""
    if not codes:
        return ""
    lines = [f"Most frequent errors in the last {submissions_counted} approved submission(s):"]
    for row in codes[:TOP_CODES]:
        line = f"- {row['code']} ({row['meaning']}): {row['errors']} error(s)"
        outcomes = [
            f"{row[key]} {label}"
            for key, label in (("fixed", "fixed"), ("unfixed", "not fixed"), ("changed_wrongly", "changed wrongly"))
            if row[key]
        ]
        if outcomes:
            line += "; revisions: " + ", ".join(outcomes)
        lines.append(line)
    return "\n".join(lines)


def cap_notes(notes: str) -> str:
    """The teacher's notes, at most MAX_NOTES_CHARS, keeping the start."""
    notes = notes.strip()
    if len(notes) <= MAX_NOTES_CHARS:
        return notes
    return notes[:MAX_NOTES_CHARS].rstrip() + " …"


def excerpt(text: str, start: int, end: int) -> str:
    """The sentence holding text[start:end], with the error marked like
    «this», at most MAX_EXCERPT_CHARS long."""
    sentence_start = 0
    for match in _SENTENCE_END.finditer(text, 0, start):
        sentence_start = match.end()
    match = _SENTENCE_END.search(text, end)
    sentence_end = match.end() if match else len(text)
    before = text[sentence_start:start].lstrip()
    after = text[end:sentence_end].rstrip()
    marked = f"{before}«{text[start:end]}»{after}"
    if len(marked) > MAX_EXCERPT_CHARS:
        # Keep the marked error in view: trim around it instead.
        room = max(0, (MAX_EXCERPT_CHARS - (end - start) - 2) // 2)
        marked = f"…{before[-room:]}«{text[start:end]}»{after[:room]}…"
    return marked


def choose_excerpts(pairs: list[tuple[dict, dict]], codes: list[str]) -> list[str]:
    """Up to MAX_EXCERPTS excerpts, taking the codes in order (most
    frequent first) and the newest work first, one excerpt per code per
    round so several codes are represented."""
    by_code: dict[str, list[str]] = {code: [] for code in codes}
    for _, submission in pairs:  # newest first
        for span in annotated_spans(submission):
            if span["code"] in by_code:
                by_code[span["code"]].append(f"[{span['code']}] " + excerpt(span["text"], span["start"], span["end"]))
    chosen: list[str] = []
    while len(chosen) < MAX_EXCERPTS and any(by_code.values()):
        for code in codes:
            if by_code[code] and len(chosen) < MAX_EXCERPTS:
                chosen.append(by_code[code].pop(0))
    return chosen


def recent_titles(student_id: str) -> list[str]:
    """The newest exercise and lesson titles, with each grammar exercise's
    concept codes, e.g. "Past tense practice (VT, WO)"."""
    db = get_db()
    entries = []
    for collection in ("exercises", "lessons"):
        for doc in db.collection(collection).where(filter=FieldFilter("student_id", "==", student_id)).stream():
            data = doc.to_dict()
            concepts = sorted({item["concept"] for item in data.get("items", []) if "concept" in item})
            title = data["title"] + (f" ({', '.join(concepts)})" if concepts else "")
            entries.append((data["created_at"], title))
    entries.sort(reverse=True)
    return [title for _, title in entries[:MAX_TITLES]]


def build_context(student_id: str) -> ContextBundle:
    """The bundle for generate_exercise and generate_lesson."""
    student = get_db().collection("students").document(student_id).get().to_dict()
    pairs = recent_approved(student_id)
    codes = compute_profile(pairs)
    top = [row["code"] for row in codes[:TOP_CODES]]
    return ContextBundle(
        profile_summary=profile_summary(codes, len(pairs)),
        teacher_notes=cap_notes(student.get("teacher_notes", "")),
        recent_titles=recent_titles(student_id),
        excerpts=choose_excerpts(pairs, top),
    )
