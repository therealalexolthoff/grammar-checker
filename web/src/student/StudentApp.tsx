import { useEffect, useState } from "react";
import { api } from "../api";
import type { ExerciseSummary } from "../types";
import DoExercise from "./DoExercise";

// Plain-English labels for the submission states (FR-35: no jargon).
export function stateLabel(state: string): string {
  if (state === "assigned") return "New";
  if (state === "in_progress") return "In progress";
  if (state === "released") return "Results ready";
  if (state === "revision_open") return "Results ready – you can make corrections";
  if (state === "revision_submitted") return "Corrections sent";
  return "Submitted – waiting for your teacher";
}

export default function StudentApp() {
  const [list, setList] = useState<ExerciseSummary[] | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (openId) return;
    api<ExerciseSummary[]>("/me/exercises")
      .then(setList)
      .catch(() => setError("Could not load your work. Check your connection and try again."));
  }, [openId]);

  if (openId) return <DoExercise exerciseId={openId} onBack={() => setOpenId(null)} />;

  return (
    <main className="page narrow">
      <h1>My work</h1>
      {error && <p className="error">{error}</p>}
      {list === null && !error && <p>Loading…</p>}
      {list?.length === 0 && <p>Nothing here yet. Your teacher will tell you when there's new work.</p>}
      <ul className="cards">
        {list?.map((ex) => (
          <li key={ex.exercise_id}>
            <button className="card" onClick={() => setOpenId(ex.exercise_id)}>
              <strong>{ex.title}</strong>
              <span className={`badge ${ex.state}`}>{stateLabel(ex.state)}</span>
            </button>
          </li>
        ))}
      </ul>
    </main>
  );
}
