// One writing exercise the teacher writes, assigned at once to the
// students they pick (teacher decision 2026-10-14). No AI draft. Each
// student gets their own copy, which then works like any other writing
// exercise. The API checks everything again (api/app/exercises.py).
import { useState, type FormEvent } from "react";
import { api } from "../api";
import type { Student } from "../types";

export default function WritingForStudents({ students, onDone }: { students: Student[]; onDone: (message: string) => void }) {
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [minWords, setMinWords] = useState("");
  const [maxWords, setMaxWords] = useState("");
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const toggle = (id: string) => {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChosen(next);
  };
  const allChosen = students.length > 0 && chosen.size === students.length;

  function review(e: FormEvent) {
    e.preventDefault();
    setError(chosen.size === 0 ? "Pick at least one student." : "");
    if (chosen.size > 0) setConfirming(true);
  }

  async function assign() {
    setBusy(true);
    setError("");
    try {
      const draft = {
        kind: "writing",
        title,
        prompt,
        min_words: minWords ? Number(minWords) : null,
        max_words: maxWords ? Number(maxWords) : null,
      };
      // Keep the order of the class list.
      const student_ids = students.filter((s) => chosen.has(s.student_id)).map((s) => s.student_id);
      await api("/exercises/writing-for-students", "POST", { draft, student_ids });
      onDone(`“${title}” was assigned to ${chosen.size} student${chosen.size > 1 ? "s" : ""}.`);
    } catch (err) {
      setError((err as Error).message);
      setConfirming(false);
      setBusy(false);
    }
  }

  return (
    <form onSubmit={review} className="panel stack">
      <h2>Writing for several students</h2>
      <p className="muted">
        Write the prompt yourself. Each student you pick gets their own copy straight away. It can't be edited after
        assigning.
      </p>
      <label>
        Title
        <input value={title} onChange={(e) => setTitle(e.target.value)} required disabled={confirming} />
      </label>
      <label>
        Prompt
        <textarea rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)} required disabled={confirming} />
      </label>
      <div className="row">
        <label>
          Min words (optional)
          <input type="number" min={1} value={minWords} onChange={(e) => setMinWords(e.target.value)} disabled={confirming} />
        </label>
        <label>
          Max words (optional)
          <input type="number" min={1} value={maxWords} onChange={(e) => setMaxWords(e.target.value)} disabled={confirming} />
        </label>
      </div>

      <fieldset disabled={confirming}>
        <legend>Students</legend>
        <label className="check">
          <input
            type="checkbox"
            checked={allChosen}
            onChange={() => setChosen(allChosen ? new Set() : new Set(students.map((s) => s.student_id)))}
          />
          <strong>All students</strong>
        </label>
        {students.map((s) => (
          <label key={s.student_id} className="check">
            <input type="checkbox" checked={chosen.has(s.student_id)} onChange={() => toggle(s.student_id)} />
            {s.username}
          </label>
        ))}
      </fieldset>

      {confirming ? (
        <div className="confirm">
          <p>
            <strong>Assign “{title}” to {chosen.size} student{chosen.size > 1 ? "s" : ""} now?</strong> They'll see
            it straight away, and it can't be changed after this.
          </p>
          <div className="row">
            <button type="button" className="primary" onClick={assign} disabled={busy}>
              {busy ? "Assigning…" : "Yes, assign"}
            </button>
            <button type="button" onClick={() => setConfirming(false)} disabled={busy}>Not yet</button>
          </div>
        </div>
      ) : (
        <button className="primary">Assign…</button>
      )}
      {error && <p className="error pre">{error}</p>}
    </form>
  );
}
