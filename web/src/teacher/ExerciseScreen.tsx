// One exercise, teacher side. Draft: edit, regenerate with a note, tick
// the approval checklist, assign. Assigned: the student's answers and
// grades, short-answer scrub and evaluation (ShortAnswerReview), release
// results, reopen.
import { useEffect, useState } from "react";
import { api } from "../api";
import type { Code, TeacherExercise, TeacherItem } from "../types";
import ShortAnswerReview from "./ShortAnswerReview";

export function stateLabel(state: string): string {
  const labels: Record<string, string> = {
    draft: "Draft",
    assigned: "Assigned",
    in_progress: "In progress",
    scrub_review: "Submitted – awaiting scrub",
    evaluating: "Evaluating",
    draft_ready: "Draft evaluation ready",
    ready_to_release: "Ready to release",
    released: "Released",
  };
  return labels[state] ?? state;
}

export default function ExerciseScreen({ exerciseId, onBack }: { exerciseId: string; onBack: () => void }) {
  const [exercise, setExercise] = useState<TeacherExercise | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api<TeacherExercise>(`/exercises/${exerciseId}`).then(setExercise, (err) => setError(err.message));
  }, [exerciseId]);

  return (
    <main className="page wide">
      <button className="link" onClick={onBack}>← All exercises</button>
      {error && <p className="error">{error}</p>}
      {exercise &&
        (exercise.status === "draft" ? (
          <Editor exercise={exercise} onChange={setExercise} />
        ) : (
          <Review exercise={exercise} onChange={setExercise} />
        ))}
    </main>
  );
}

// ---- draft editing ----

// Items as the editor's text fields hold them: lists become one-per-line
// text so typing isn't disrupted, and are parsed back on save.
type EditItem =
  | { id: string; type: "fill_blank"; text: string; blanks: { id: string; accepted: string }[]; concept: string; explanation: string }
  | { id: string; type: "reorder"; chunks: string; orders: string; concept: string; explanation: string }
  | { id: string; type: "short_answer"; prompt: string };

const ORDER_SEPARATOR = " / ";
const lines = (text: string) => text.split("\n").map((l) => l.trim()).filter(Boolean);

function toEdit(item: TeacherItem): EditItem {
  if (item.type === "fill_blank") {
    return { ...item, blanks: item.blanks.map((b) => ({ id: b.id, accepted: b.accepted.join("\n") })) };
  }
  if (item.type === "reorder") {
    const { chunks, accepted_orders, ...rest } = item;
    return { ...rest, chunks: chunks.join("\n"), orders: accepted_orders.map((o) => o.join(ORDER_SEPARATOR)).join("\n") };
  }
  return item;
}

function fromEdit(item: EditItem): TeacherItem {
  if (item.type === "fill_blank") {
    return { ...item, blanks: item.blanks.map((b) => ({ id: b.id, accepted: lines(b.accepted) })) };
  }
  if (item.type === "reorder") {
    const { chunks, orders, ...rest } = item;
    return {
      ...rest,
      chunks: lines(chunks),
      accepted_orders: lines(orders).map((o) => o.split(ORDER_SEPARATOR.trim()).map((c) => c.trim())),
    };
  }
  return item;
}

function Editor({ exercise, onChange }: { exercise: TeacherExercise; onChange: (e: TeacherExercise) => void }) {
  const [title, setTitle] = useState(exercise.title);
  const [items, setItems] = useState(exercise.items.map(toEdit));
  const [dirty, setDirty] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [codes, setCodes] = useState<Code[]>([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<Code[]>("/taxonomy").then(setCodes);
  }, []);

  // A new version from the server (save or regenerate) resets the editor
  // and the checklist: ticks only count for the version they were made on.
  function load(next: TeacherExercise) {
    setTitle(next.title);
    setItems(next.items.map(toEdit));
    setDirty(false);
    setChecked(new Set());
    onChange(next);
  }

  function edit(index: number, patch: Partial<EditItem>) {
    setItems(items.map((it, i) => (i === index ? ({ ...it, ...patch } as EditItem) : it)));
    setDirty(true);
    setChecked(new Set());
  }

  async function run(label: string, call: () => Promise<TeacherExercise>) {
    setBusy(label);
    setError("");
    try {
      load(await call());
    } catch (err) {
      setError((err as Error).message);
    }
    setBusy("");
  }

  const save = () =>
    run("Saving…", () =>
      api(`/exercises/${exercise.exercise_id}`, "PUT", { kind: "grammar", title, items: items.map(fromEdit) }),
    );
  const regenerate = () =>
    run("Regenerating… (up to a minute)", () => api(`/exercises/${exercise.exercise_id}/regenerate`, "POST", { note }));
  const assign = () =>
    run("Assigning…", () =>
      api(`/exercises/${exercise.exercise_id}/assign`, "POST", { answers_and_concepts_checked: true }),
    );

  const needsCheck = items.filter((it) => it.type !== "short_answer").map((it) => it.id);
  const allChecked = needsCheck.every((id) => checked.has(id));

  return (
    <>
      <p className="muted">Request: {exercise.teacher_request}</p>
      <label>
        Title
        <input value={title} onChange={(e) => { setTitle(e.target.value); setDirty(true); }} />
      </label>

      <ol className="items">
        {items.map((item, i) => (
          <li key={item.id} className="item">
            <ItemEditor item={item} codes={codes} onEdit={(patch) => edit(i, patch)} />
            {item.type !== "short_answer" && (
              <label className="check">
                <input
                  type="checkbox"
                  checked={checked.has(item.id)}
                  disabled={dirty}
                  onChange={(e) => {
                    const next = new Set(checked);
                    if (e.target.checked) next.add(item.id);
                    else next.delete(item.id);
                    setChecked(next);
                  }}
                />
                I checked the accepted answers and the concept code
              </label>
            )}
          </li>
        ))}
      </ol>

      {error && <p className="error pre">{error}</p>}
      {busy && <p className="notice">{busy}</p>}

      <div className="row">
        <button onClick={save} disabled={!dirty || !!busy}>Save changes</button>
        <button className="primary" onClick={assign} disabled={dirty || !allChecked || !!busy}>
          Assign to student
        </button>
      </div>
      {dirty && <p className="muted">Save your changes before ticking the checklist and assigning.</p>}
      {!dirty && !allChecked && <p className="muted">Tick every item's checklist box to enable Assign.</p>}

      <div className="panel stack">
        <label>
          Regenerate with a note (optional)
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. make the sentences about work" />
        </label>
        <button onClick={regenerate} disabled={!!busy}>Regenerate</button>
        {dirty && <p className="muted">Regenerating replaces your unsaved edits.</p>}
      </div>
    </>
  );
}

function ItemEditor({ item, codes, onEdit }: { item: EditItem; codes: Code[]; onEdit: (p: Partial<EditItem>) => void }) {
  if (item.type === "short_answer") {
    return (
      <label>
        Short answer prompt
        <textarea rows={2} value={item.prompt} onChange={(e) => onEdit({ prompt: e.target.value })} />
      </label>
    );
  }

  const conceptAndExplanation = (
    <div className="row">
      <label>
        Concept{" "}
        <select value={item.concept} onChange={(e) => onEdit({ concept: e.target.value })}>
          {codes.map((c) => (
            <option key={c.code} value={c.code}>{c.code} – {c.description}</option>
          ))}
        </select>
      </label>
      <label className="grow">
        Explanation (shown to the student after release)
        <input value={item.explanation} onChange={(e) => onEdit({ explanation: e.target.value })} />
      </label>
    </div>
  );

  if (item.type === "fill_blank") {
    return (
      <>
        <label>
          Fill in the blank – sentence (mark each blank with ___)
          <input value={item.text} onChange={(e) => onEdit({ text: e.target.value })} />
        </label>
        {item.blanks.map((b, bi) => (
          <label key={b.id}>
            Blank {bi + 1} – accepted answers, one per line (exact: case and punctuation count)
            <textarea
              rows={2}
              value={b.accepted}
              onChange={(e) =>
                onEdit({ blanks: item.blanks.map((x, xi) => (xi === bi ? { ...x, accepted: e.target.value } : x)) })
              }
            />
          </label>
        ))}
        {conceptAndExplanation}
      </>
    );
  }

  return (
    <>
      <div className="row">
        <label className="grow">
          Word order – chunks, one per line
          <textarea rows={4} value={item.chunks} onChange={(e) => onEdit({ chunks: e.target.value })} />
        </label>
        <label className="grow">
          Accepted orders, one per line, chunks separated by “/”
          <textarea rows={4} value={item.orders} onChange={(e) => onEdit({ orders: e.target.value })} />
        </label>
      </div>
      {conceptAndExplanation}
    </>
  );
}

// ---- assigned: answers, grades, release, reopen ----

function Review({ exercise, onChange }: { exercise: TeacherExercise; onChange: (e: TeacherExercise) => void }) {
  const [confirmReopen, setConfirmReopen] = useState(false);
  const [error, setError] = useState("");
  const submitted = !["assigned", "in_progress"].includes(exercise.state);
  const hasShortAnswers = exercise.items.some((it) => it.type === "short_answer");
  // Once submitted, short answers are handled by the review panel below.
  const listed = submitted ? exercise.items.filter((it) => it.type !== "short_answer") : exercise.items;

  async function act(path: string) {
    setError("");
    try {
      onChange(await api(`/exercises/${exercise.exercise_id}/${path}`, "POST"));
      setConfirmReopen(false);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <>
      <h1>{exercise.title}</h1>
      <p>
        Stage: <strong>{stateLabel(exercise.state)}</strong>
      </p>
      <ol className="items">
        {listed.map((item) => (
          <li key={item.id} className="item">
            <TeacherItemResult item={item} answer={exercise.answers[item.id]} grade={submitted ? exercise.grades[item.id] : undefined} />
          </li>
        ))}
      </ol>

      {submitted && hasShortAnswers && <ShortAnswerReview exercise={exercise} onChange={onChange} />}

      {error && <p className="error">{error}</p>}
      <div className="row">
        {exercise.state === "ready_to_release" && (
          <button className="primary" onClick={() => act("release")}>Release results to student</button>
        )}
        {["scrub_review", "draft_ready", "ready_to_release"].includes(exercise.state) &&
          (confirmReopen ? (
            <>
              <span>Send this back to the student to keep working? (This is recorded in the audit log.)</span>
              <button onClick={() => act("reopen")}>Yes, reopen</button>
              <button onClick={() => setConfirmReopen(false)}>Cancel</button>
            </>
          ) : (
            <button onClick={() => setConfirmReopen(true)}>Reopen…</button>
          ))}
      </div>
    </>
  );
}

function TeacherItemResult({ item, answer, grade }: { item: TeacherItem; answer: unknown; grade?: boolean }) {
  const mark = grade === undefined ? "" : grade ? "✓ " : "✗ ";
  if (item.type === "fill_blank") {
    const filled = (answer as Record<string, string>) ?? {};
    return (
      <>
        <p>{mark}{item.text}</p>
        <p className="muted">
          Answers:{" "}
          {item.blanks.map((b) => `“${filled[b.id] ?? ""}” (accepted: ${b.accepted.join(" | ")})`).join("; ")}
        </p>
      </>
    );
  }
  if (item.type === "reorder") {
    const placed = ((answer as number[]) ?? []).map((i) => item.chunks[i]).join(" ");
    return (
      <>
        <p>{mark}{item.chunks.join(" · ")}</p>
        <p className="muted">
          Answer: “{placed}” (accepted: {item.accepted_orders.map((o) => o.join(" ")).join(" | ")})
        </p>
      </>
    );
  }
  return (
    <>
      <p>{item.prompt}</p>
      <p className="muted">Answer: {(answer as string) || "(none yet)"}</p>
    </>
  );
}
