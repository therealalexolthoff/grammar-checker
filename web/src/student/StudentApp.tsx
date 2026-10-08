import { useEffect, useState } from "react";
import { api } from "../api";
import type { ExerciseSummary, StudentLessonSummary } from "../types";
import DoExercise from "./DoExercise";
import ReadLesson from "./ReadLesson";

// Plain-English labels for the submission states (FR-35: no jargon).
export function stateLabel(state: string): string {
  if (state === "assigned") return "New";
  if (state === "in_progress") return "In progress";
  if (state === "released") return "Results ready";
  if (state === "revision_open") return "Results ready – you can make corrections";
  if (state === "revision_submitted") return "Corrections sent";
  return "Submitted – waiting for your teacher";
}

type Open = { kind: "exercise" | "lesson"; id: string } | null;

export default function StudentApp() {
  const [exercises, setExercises] = useState<ExerciseSummary[] | null>(null);
  const [lessons, setLessons] = useState<StudentLessonSummary[] | null>(null);
  const [open, setOpen] = useState<Open>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) return;
    const failed = () => setError("Could not load your work. Check your connection and try again.");
    api<ExerciseSummary[]>("/me/exercises").then(setExercises).catch(failed);
    api<StudentLessonSummary[]>("/me/lessons").then(setLessons).catch(failed);
  }, [open]);

  const back = () => setOpen(null);
  if (open?.kind === "exercise") return <DoExercise exerciseId={open.id} onBack={back} />;
  if (open?.kind === "lesson") return <ReadLesson lessonId={open.id} onBack={back} />;

  return (
    <main className="page narrow">
      <h1>My work</h1>
      {error && <p className="error">{error}</p>}
      {exercises === null && !error && <p>Loading…</p>}
      {exercises?.length === 0 && <p>Nothing here yet. Your teacher will tell you when there's new work.</p>}
      <ul className="cards">
        {exercises?.map((ex) => (
          <li key={ex.exercise_id}>
            <button className="card" onClick={() => setOpen({ kind: "exercise", id: ex.exercise_id })}>
              <strong>{ex.title}</strong>
              <span className={`badge ${ex.state}`}>{stateLabel(ex.state)}</span>
            </button>
          </li>
        ))}
      </ul>

      {!!lessons?.length && (
        <>
          <h2 className="section">Lessons</h2>
          <ul className="cards">
            {lessons.map((l) => (
              <li key={l.lesson_id}>
                <button className="card" onClick={() => setOpen({ kind: "lesson", id: l.lesson_id })}>
                  <strong>{l.title}</strong>
                  <span className={`badge ${l.read ? "" : "released"}`}>{l.read ? "Read" : "New – tap to read"}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </main>
  );
}
