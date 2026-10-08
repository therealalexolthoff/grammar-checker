// Short answers, teacher side (FR-18 to FR-20): the original answer
// (read-only, never sent anywhere) next to the editable scrubbed copy;
// send for evaluation; then edit the AI draft - mark, feedback,
// annotations - regenerate with a note, and approve. Every rule is
// enforced by the API (api/app/review.py); this screen only collects input.
import { useEffect, useState } from "react";
import { api } from "../api";
import SpannedText from "../SpannedText";
import type { Annotation, Code, Evaluation, Mark, TeacherExercise } from "../types";

const EDITABLE = ["scrub_review", "draft_ready", "ready_to_release"];
const EVALUATED = ["draft_ready", "ready_to_release", "released"];
const MARKS: Mark[] = ["correct", "partial", "incorrect"];

// The API stores computed offsets on each annotation but doesn't accept
// them back; strip them before sending.
function forSending(evaluation: Evaluation): Evaluation {
  return {
    items: evaluation.items.map((item) => ({
      ...item,
      annotations: item.annotations.map(({ start: _s, end: _e, ...a }) => a),
    })),
  };
}

export default function ShortAnswerReview({
  exercise,
  onChange,
}: {
  exercise: TeacherExercise;
  onChange: (e: TeacherExercise) => void;
}) {
  const [scrubbed, setScrubbed] = useState(exercise.scrubbed_answers);
  const [scrubDirty, setScrubDirty] = useState(false);
  const [draft, setDraft] = useState<Evaluation | null>(exercise.evaluation);
  const [evalDirty, setEvalDirty] = useState(false);
  const [note, setNote] = useState("");
  const [codes, setCodes] = useState<Code[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api<Code[]>("/taxonomy").then(setCodes);
  }, []);

  const id = exercise.exercise_id;
  const editable = EDITABLE.includes(exercise.state);
  const evaluated = EVALUATED.includes(exercise.state) && exercise.evaluation !== null;
  const items = exercise.items.filter((it) => it.type === "short_answer");

  // A fresh copy from the server replaces everything being edited here.
  function load(next: TeacherExercise) {
    setScrubbed(next.scrubbed_answers);
    setScrubDirty(false);
    setDraft(next.evaluation);
    setEvalDirty(false);
    onChange(next);
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

  const saveScrubbed = () =>
    run("Saving…", () => api(`/exercises/${id}/scrubbed`, "PUT", { scrubbed_answers: scrubbed }));
  const evaluate = (withNote: string) =>
    run("Evaluating… this can take a minute or two.", () => api(`/exercises/${id}/evaluate`, "POST", { note: withNote }));
  const saveEvaluation = () =>
    run("Saving…", () => api(`/exercises/${id}/evaluation`, "PUT", forSending(draft!)));
  const approve = () => run("Approving…", () => api(`/exercises/${id}/approve`, "POST"));

  function editItem(itemId: string, patch: { mark?: Mark; feedback?: string; annotations?: Annotation[] }) {
    setDraft({ items: draft!.items.map((it) => (it.item_id === itemId ? { ...it, ...patch } : it)) });
    setEvalDirty(true);
  }

  return (
    <section className="panel stack">
      <h2>Short answers</h2>
      {exercise.state === "scrub_review" && (
        <p className="notice">
          Remove names and personal details from each scrubbed copy, save, then send for evaluation. Only the
          scrubbed copy is sent to the AI.
        </p>
      )}
      {exercise.state === "evaluating" && (
        <p className="notice">An evaluation is running. Come back to this page in a minute or two.</p>
      )}

      <ol className="items">
        {items.map((item) => {
          const saved = exercise.evaluation?.items.find((r) => r.item_id === item.id);
          const edited = draft?.items.find((r) => r.item_id === item.id);
          return (
            <li key={item.id} className="item">
              <p className="instruction">{item.type === "short_answer" && item.prompt}</p>
              <div className="row top">
                <div className="grow">
                  <strong>Original</strong> <span className="muted">(read-only, never sent)</span>
                  <p className="original">{(exercise.answers[item.id] as string) || "(no answer)"}</p>
                </div>
                <label className="grow">
                  Scrubbed copy <span className="muted">(sent to the AI)</span>
                  <textarea
                    rows={4}
                    value={scrubbed[item.id] ?? ""}
                    disabled={!editable || !!busy}
                    onChange={(e) => {
                      setScrubbed({ ...scrubbed, [item.id]: e.target.value });
                      setScrubDirty(true);
                    }}
                  />
                </label>
              </div>

              {evaluated && saved && edited && (
                <div className="evaluation">
                  <SpannedText
                    text={exercise.scrubbed_answers[item.id] ?? ""}
                    spans={saved.annotations.map((a) => ({ start: a.start!, end: a.end!, code: a.code }))}
                  />
                  <div className="row">
                    <label>
                      Mark{" "}
                      <select
                        value={edited.mark}
                        disabled={!editable}
                        onChange={(e) => editItem(item.id, { mark: e.target.value as Mark })}
                      >
                        {MARKS.map((m) => <option key={m} value={m}>{m}</option>)}
                      </select>
                    </label>
                    <label className="grow">
                      Feedback sentence (shown to the student)
                      <input
                        value={edited.feedback}
                        disabled={!editable}
                        onChange={(e) => editItem(item.id, { feedback: e.target.value })}
                      />
                    </label>
                  </div>
                  <AnnotationsEditor
                    annotations={edited.annotations}
                    codes={codes}
                    disabled={!editable}
                    onChange={(annotations) => editItem(item.id, { annotations })}
                  />
                </div>
              )}
            </li>
          );
        })}
      </ol>

      {error && <p className="error pre">{error}</p>}
      {busy && <p className="notice">{busy}</p>}

      {editable && (
        <div className="row">
          <button onClick={saveScrubbed} disabled={!scrubDirty || !!busy}>Save scrubbed text</button>
          {exercise.state === "scrub_review" && (
            <button className="primary" onClick={() => evaluate("")} disabled={scrubDirty || !!busy}>
              Send for evaluation
            </button>
          )}
          {evaluated && (
            <>
              <button onClick={saveEvaluation} disabled={!evalDirty || !!busy}>Save evaluation changes</button>
              {exercise.state === "draft_ready" && (
                <button className="primary" onClick={approve} disabled={evalDirty || scrubDirty || !!busy}>
                  Approve
                </button>
              )}
            </>
          )}
        </div>
      )}
      {scrubDirty && evaluated && (
        <p className="muted">Saving changes to the scrubbed text discards the evaluation; you'll send it again.</p>
      )}
      {exercise.state === "scrub_review" && scrubDirty && <p className="muted">Save the scrubbed text before sending it.</p>}
      {evalDirty && <p className="muted">Save your evaluation changes before approving.</p>}

      {editable && evaluated && (
        <div className="stack">
          <label>
            Regenerate the evaluation with a note (optional)
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. 'park' is not an error" />
          </label>
          <button onClick={() => evaluate(note)} disabled={scrubDirty || !!busy}>Regenerate evaluation</button>
          {evalDirty && <p className="muted">Regenerating replaces your unsaved changes.</p>}
        </div>
      )}
    </section>
  );
}

function AnnotationsEditor({
  annotations,
  codes,
  disabled,
  onChange,
}: {
  annotations: Annotation[];
  codes: Code[];
  disabled: boolean;
  onChange: (a: Annotation[]) => void;
}) {
  const edit = (i: number, patch: Partial<Annotation>) =>
    onChange(annotations.map((a, j) => (j === i ? { ...a, ...patch } : a)));
  const blank: Annotation = { code: codes[0]?.code ?? "SP", span_text: "", occurrence: 1, correction: "", explanation: "" };

  return (
    <>
      <table className="annotations">
        <thead>
          <tr>
            <th>Code</th>
            <th>Exact words</th>
            <th title="If the same words appear more than once: which one (1 = first)">Which</th>
            <th>Correction</th>
            <th>Explanation</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {annotations.map((a, i) => (
            <tr key={i}>
              <td>
                <select value={a.code} disabled={disabled} onChange={(e) => edit(i, { code: e.target.value })}>
                  {codes.map((c) => <option key={c.code} value={c.code} title={c.description}>{c.code}</option>)}
                </select>
              </td>
              <td><input value={a.span_text} disabled={disabled} onChange={(e) => edit(i, { span_text: e.target.value })} /></td>
              <td>
                <input
                  type="number"
                  min={1}
                  className="narrow-input"
                  value={a.occurrence}
                  disabled={disabled}
                  onChange={(e) => edit(i, { occurrence: Number(e.target.value) || 1 })}
                />
              </td>
              <td><input value={a.correction} disabled={disabled} onChange={(e) => edit(i, { correction: e.target.value })} /></td>
              <td><input value={a.explanation} disabled={disabled} onChange={(e) => edit(i, { explanation: e.target.value })} /></td>
              <td>
                {!disabled && (
                  <button onClick={() => onChange(annotations.filter((_, j) => j !== i))} aria-label="Remove annotation">
                    Remove
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {annotations.length === 0 && <p className="muted">No errors flagged.</p>}
      {!disabled && <button onClick={() => onChange([...annotations, blank])}>Add annotation</button>}
    </>
  );
}
