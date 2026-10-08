// The class overview (FR-32): each student's unfinished work with its
// stage, and lessons they haven't read yet. Built by api/app/overview.py.
import { useEffect, useState } from "react";
import { api } from "../api";
import type { OverviewRow } from "../types";
import { stateLabel } from "./ExerciseScreen";

// Stages where the next step is the teacher's, highlighted in the list.
const TEACHER_TURN = ["transcript_review", "scrub_review", "draft_ready", "ready_to_release", "revision_submitted"];

export default function Overview({
  onOpenExercise,
  onOpenStudent,
}: {
  onOpenExercise: (id: string) => void;
  onOpenStudent: (id: string) => void;
}) {
  const [rows, setRows] = useState<OverviewRow[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<OverviewRow[]>("/overview").then(setRows, (err) => setError(err.message));
  }, []);

  if (error) return <p className="error">{error}</p>;
  if (!rows) return <p>Loading…</p>;
  if (rows.length === 0) return <p>No active students yet. Use “Manage students” to add them.</p>;

  return (
    <table className="overview">
      <thead>
        <tr><th>Student</th><th>Work in progress</th><th>Unread lessons</th></tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.student_id}>
            <td>
              <button className="link" onClick={() => onOpenStudent(row.student_id)}>{row.username}</button>
            </td>
            <td>
              {row.work.length === 0 && <span className="muted">Nothing pending</span>}
              <ul className="plain">
                {row.work.map((w) => (
                  <li key={w.exercise_id}>
                    <button className="link" onClick={() => onOpenExercise(w.exercise_id)}>{w.title}</button>{" "}
                    <span className={TEACHER_TURN.includes(w.state) ? "stage yours" : "stage"}>{stateLabel(w.state)}</span>
                  </li>
                ))}
              </ul>
            </td>
            <td>
              {row.unread_lessons.length === 0 ? (
                <span className="muted">—</span>
              ) : (
                <ul className="plain">
                  {row.unread_lessons.map((l) => <li key={l.lesson_id}>{l.title}</li>)}
                </ul>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
