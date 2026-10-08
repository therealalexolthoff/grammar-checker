// A lesson for the student to read (FR-28, FR-29), with "Mark as read".
import { useEffect, useState } from "react";
import { api } from "../api";
import LessonBody from "../LessonBody";
import type { StudentLesson } from "../types";

export default function ReadLesson({ lessonId, onBack }: { lessonId: string; onBack: () => void }) {
  const [lesson, setLesson] = useState<StudentLesson | null>(null);
  const [error, setError] = useState("");
  const [marking, setMarking] = useState(false);

  useEffect(() => {
    api<StudentLesson>(`/lessons/${lessonId}`)
      .then(setLesson)
      .catch(() => setError("Could not open this lesson. Go back and try again."));
  }, [lessonId]);

  async function markRead() {
    setMarking(true);
    setError("");
    try {
      await api(`/lessons/${lessonId}/read`, "POST");
      setLesson({ ...lesson!, read: true });
    } catch {
      setError("Not saved – check your connection and try again.");
    }
    setMarking(false);
  }

  return (
    <main className="page narrow">
      <button className="link" onClick={onBack}>← My work</button>
      {error && <p className="error">{error}</p>}
      {!lesson && !error && <p>Loading…</p>}
      {lesson && (
        <>
          <h1>{lesson.title}</h1>
          <LessonBody explanation={lesson.explanation} examples={lesson.examples} />
          {lesson.read ? (
            <p className="notice">✓ You've read this lesson.</p>
          ) : (
            <button className="primary big" onClick={markRead} disabled={marking}>
              {marking ? "Saving…" : "Mark as read"}
            </button>
          )}
        </>
      )}
    </main>
  );
}
