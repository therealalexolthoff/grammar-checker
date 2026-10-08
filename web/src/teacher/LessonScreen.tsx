// One lesson, teacher side (FR-28, FR-29). Draft: edit the title,
// explanation and examples, regenerate with a note, assign. Assigned:
// read-only, with whether the student has read it.
import { useEffect, useState } from "react";
import { api } from "../api";
import LessonBody from "../LessonBody";
import type { LessonExample, TeacherLesson } from "../types";
import { wordCount } from "../words";

export default function LessonScreen({ lessonId, onBack }: { lessonId: string; onBack: () => void }) {
  const [lesson, setLesson] = useState<TeacherLesson | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<TeacherLesson>(`/lessons/${lessonId}`).then(setLesson, (err) => setError(err.message));
  }, [lessonId]);

  return (
    <main className="page wide">
      <button className="link" onClick={onBack}>← Back</button>
      {error && <p className="error">{error}</p>}
      {lesson && (lesson.status === "draft" ? <LessonEditor lesson={lesson} onChange={setLesson} /> : <AssignedLesson lesson={lesson} />)}
    </main>
  );
}

function AssignedLesson({ lesson }: { lesson: TeacherLesson }) {
  return (
    <>
      <h1>{lesson.title}</h1>
      <p>
        <strong>{lesson.read_at ? `Read on ${new Date(lesson.read_at).toLocaleDateString()}` : "Assigned – not read yet"}</strong>
      </p>
      <LessonBody explanation={lesson.explanation} examples={lesson.examples} />
    </>
  );
}

function LessonEditor({ lesson, onChange }: { lesson: TeacherLesson; onChange: (l: TeacherLesson) => void }) {
  const [title, setTitle] = useState(lesson.title);
  const [explanation, setExplanation] = useState(lesson.explanation);
  const [examples, setExamples] = useState(lesson.examples);
  const [dirty, setDirty] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  function load(next: TeacherLesson) {
    setTitle(next.title);
    setExplanation(next.explanation);
    setExamples(next.examples);
    setDirty(false);
    onChange(next);
  }

  async function run(label: string, call: () => Promise<TeacherLesson>) {
    setBusy(label);
    setError("");
    try {
      load(await call());
    } catch (err) {
      setError((err as Error).message);
    }
    setBusy("");
  }

  const editExample = (i: number, patch: Partial<LessonExample>) => {
    setExamples(examples.map((ex, j) => (j === i ? { ...ex, ...patch } : ex)));
    setDirty(true);
  };
  const id = lesson.lesson_id;
  const words = wordCount([explanation, ...examples.map((e) => `${e.incorrect} ${e.correct} ${e.note}`)].join(" "));

  return (
    <>
      <p className="muted">Request: {lesson.request}</p>
      <label>
        Title
        <input value={title} onChange={(e) => { setTitle(e.target.value); setDirty(true); }} />
      </label>
      <label>
        Explanation
        <textarea rows={12} value={explanation} onChange={(e) => { setExplanation(e.target.value); setDirty(true); }} />
      </label>
      <h2>Examples</h2>
      <table className="annotations">
        <thead>
          <tr><th>Incorrect</th><th>Correct</th><th>Note</th><th></th></tr>
        </thead>
        <tbody>
          {examples.map((ex, i) => (
            <tr key={i}>
              <td><input value={ex.incorrect} onChange={(e) => editExample(i, { incorrect: e.target.value })} /></td>
              <td><input value={ex.correct} onChange={(e) => editExample(i, { correct: e.target.value })} /></td>
              <td><input value={ex.note} onChange={(e) => editExample(i, { note: e.target.value })} /></td>
              <td>
                {examples.length > 1 && (
                  <button onClick={() => { setExamples(examples.filter((_, j) => j !== i)); setDirty(true); }}>Remove</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button onClick={() => { setExamples([...examples, { incorrect: "", correct: "", note: "" }]); setDirty(true); }}>
        Add example
      </button>
      <p className="muted">{words} words (the AI aims for 200–400).</p>

      {error && <p className="error pre">{error}</p>}
      {busy && <p className="notice">{busy}</p>}
      <div className="row">
        <button onClick={() => run("Saving…", () => api(`/lessons/${id}`, "PUT", { title, explanation, examples }))} disabled={!dirty || !!busy}>
          Save changes
        </button>
        <button className="primary" onClick={() => run("Assigning…", () => api(`/lessons/${id}/assign`, "POST"))} disabled={dirty || !!busy}>
          Assign to student
        </button>
      </div>
      {dirty && <p className="muted">Save your changes before assigning.</p>}

      <div className="panel stack">
        <label>
          Regenerate with a note (optional)
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. use examples about cooking" />
        </label>
        <button onClick={() => run("Regenerating… (up to a minute)", () => api(`/lessons/${id}/regenerate`, "POST", { note }))} disabled={!!busy}>
          Regenerate
        </button>
        {dirty && <p className="muted">Regenerating replaces your unsaved edits.</p>}
      </div>
    </>
  );
}
