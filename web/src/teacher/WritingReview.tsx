// A writing exercise, teacher side, once assigned (FR-18 to FR-27):
// handwriting photos and their transcription, choosing the final source,
// scrub and evaluation, and marking the student's revision. Every rule is
// enforced by the API (api/app/writing.py and review.py); this screen only
// collects input.
import { useEffect, useState } from "react";
import { api } from "../api";
import { inPageOrder, toCleanJpeg, type PageLink } from "../photos";
import SpannedText from "../SpannedText";
import type { Annotation, Code, Outcome, TeacherExercise, WritingEvaluation } from "../types";
import { wordCount } from "../words";
import { AnnotationsEditor, withoutOffsets } from "./ShortAnswerReview";

// Mirrors the state lists in api/app/writing.py and review.py.
const PHOTO_STATES = ["assigned", "in_progress", "transcript_review", "scrub_review"];
const REVIEW_STATES = ["scrub_review", "draft_ready", "ready_to_release"];
const AFTER_SCRUB = [...REVIEW_STATES, "evaluating", "released", "revision_open", "revision_submitted"];

type Run = (label: string, call: () => Promise<TeacherExercise>) => Promise<boolean>;

export default function WritingReview({
  exercise,
  onChange,
}: {
  exercise: TeacherExercise;
  onChange: (e: TeacherExercise) => void;
}) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  // Runs one API call; a fresh copy of the exercise replaces the old one.
  const run: Run = async (label, call) => {
    setBusy(label);
    setError("");
    try {
      onChange(await call());
      return true;
    } catch (err) {
      setError((err as Error).message);
      return false;
    } finally {
      setBusy("");
    }
  };

  const typed = (exercise.answers.text as string | undefined) ?? "";
  const limits = [exercise.min_words && `at least ${exercise.min_words}`, exercise.max_words && `at most ${exercise.max_words}`]
    .filter(Boolean)
    .join(", ");

  return (
    <>
      <section className="panel">
        <h2>Prompt</h2>
        <p>{exercise.prompt}</p>
        {limits && <p className="muted">Words: {limits}</p>}
      </section>

      <section className="panel">
        <h2>Typed answer</h2>
        <p className="original">{typed || "(nothing typed)"}</p>
        {typed && <p className="muted">{wordCount(typed)} words</p>}
      </section>

      {(PHOTO_STATES.includes(exercise.state) || !!exercise.photo_count) && (
        <Handwriting exercise={exercise} run={run} busy={busy} />
      )}
      {exercise.state === "transcribing" && (
        <p className="notice">The photos are being transcribed. Come back to this page in a minute or two.</p>
      )}
      {exercise.state === "transcript_review" && <TranscriptReview exercise={exercise} run={run} busy={busy} />}
      {AFTER_SCRUB.includes(exercise.state) && <ScrubAndEvaluate exercise={exercise} run={run} busy={busy} />}
      {exercise.state === "revision_open" && (
        <p className="notice">Released. The student can now revise the flagged words; you'll mark their changes here.</p>
      )}
      {exercise.state === "revision_submitted" && <RevisionReview exercise={exercise} run={run} busy={busy} />}

      {error && <p className="error pre">{error}</p>}
      {busy && <p className="notice">{busy}</p>}
    </>
  );
}

// ---- handwriting: upload, view, transcribe ----

function Handwriting({ exercise, run, busy }: { exercise: TeacherExercise; run: Run; busy: string }) {
  const [confirmRemove, setConfirmRemove] = useState(false);
  const id = exercise.exercise_id;
  const editable = PHOTO_STATES.includes(exercise.state);
  const count = exercise.photo_count ?? 0;
  const studentCanStillType = ["assigned", "in_progress"].includes(exercise.state);

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    const pages = inPageOrder(files);
    for (const [i, file] of pages.entries()) {
      const ok = await run(`Uploading page ${count + i + 1}…`, async () => {
        let photo: Blob;
        try {
          photo = await toCleanJpeg(file);
        } catch {
          throw new Error(`“${file.name}” couldn't be opened. Try a JPEG photo, or set the camera to “Most compatible”.`);
        }
        return api(`/exercises/${id}/photos`, "POST", photo);
      });
      if (!ok) return;
    }
  }

  return (
    <section className="panel stack">
      <h2>Handwritten work</h2>
      {editable && (
        <>
          <p className="muted">
            Add photos of the pages. If you choose several at once they're added in file-name order, after any pages
            already here, including any the student added. Pages you add are never shown to the student.
          </p>
          <label>
            Add pages
            <input
              type="file"
              accept="image/*"
              multiple
              disabled={!!busy}
              onChange={(e) => {
                upload(e.target.files);
                e.target.value = "";
              }}
            />
          </label>
        </>
      )}
      {count > 0 && exercise.state !== "transcript_review" && <PhotoPages exercise={exercise} />}
      {editable && count > 0 && (
        <div className="row">
          <button className="primary" disabled={!!busy} onClick={() => run("Transcribing… this can take a minute or two.", () => api(`/exercises/${id}/transcribe`, "POST"))}>
            {exercise.transcription == null ? "Transcribe photos" : "Transcribe again"}
          </button>
          {confirmRemove ? (
            <>
              <span>Remove all {count} pages?</span>
              <button onClick={() => run("Removing…", () => api(`/exercises/${id}/photos`, "DELETE")).then(() => setConfirmRemove(false))}>
                Yes, remove
              </button>
              <button onClick={() => setConfirmRemove(false)}>Cancel</button>
            </>
          ) : (
            <button onClick={() => setConfirmRemove(true)} disabled={!!busy}>Remove all pages…</button>
          )}
        </div>
      )}
      {editable && count > 0 && studentCanStillType && (
        <p className="muted">Transcribing locks the student's typed answer, as if they had submitted.</p>
      )}
      {editable && exercise.transcription != null && exercise.state !== "transcript_review" && (
        <p className="muted">Transcribing again replaces the current transcription and your corrections to it.</p>
      )}
    </section>
  );
}

// The pages, through short-lived links from the API (they stop working
// after 15 minutes; reopen the exercise to get fresh ones).
function PhotoPages({ exercise }: { exercise: TeacherExercise }) {
  const [pages, setPages] = useState<PageLink[]>([]);
  useEffect(() => {
    api<PageLink[]>(`/exercises/${exercise.exercise_id}/photos`).then(setPages, () => setPages([]));
  }, [exercise.exercise_id, exercise.photo_count]);

  return (
    <div className="photos">
      {pages.map((p) => (
        <figure key={p.page}>
          <a href={p.url} target="_blank" rel="noreferrer">
            <img src={p.url} alt={`Page ${p.page}`} />
          </a>
          <figcaption>Page {p.page}</figcaption>
        </figure>
      ))}
    </div>
  );
}

function TranscriptReview({ exercise, run, busy }: { exercise: TeacherExercise; run: Run; busy: string }) {
  const [text, setText] = useState(exercise.transcription ?? "");
  const [dirty, setDirty] = useState(false);
  const id = exercise.exercise_id;
  const typed = (exercise.answers.text as string | undefined) ?? "";

  useEffect(() => {
    setText(exercise.transcription ?? "");
    setDirty(false);
  }, [exercise.transcription]);

  const choose = (source: "typed" | "photo") =>
    run("Saving…", () => api(`/exercises/${id}/final-source`, "POST", { source }));

  return (
    <section className="panel stack">
      <h2>Check the transcription</h2>
      <p className="notice">
        Correct the text so it matches exactly what the student wrote – keep their mistakes. “[?]” marks words the AI
        couldn't read. Then choose which version to evaluate.
      </p>
      <div className="row top">
        <div className="grow">
          <PhotoPages exercise={exercise} />
        </div>
        <label className="grow">
          Transcription
          <textarea
            rows={20}
            value={text}
            disabled={!!busy}
            onChange={(e) => {
              setText(e.target.value);
              setDirty(true);
            }}
          />
        </label>
      </div>
      <div className="row">
        <button
          onClick={() => run("Saving…", () => api(`/exercises/${id}/transcription`, "PUT", { text }))}
          disabled={!dirty || !!busy}
        >
          Save transcription
        </button>
        <button className="primary" onClick={() => choose("photo")} disabled={dirty || !!busy}>
          Evaluate the handwritten version
        </button>
        <button onClick={() => choose("typed")} disabled={dirty || !typed.trim() || !!busy}>
          Evaluate the typed version instead
        </button>
      </div>
      {dirty && <p className="muted">Save the transcription before choosing.</p>}
    </section>
  );
}

// ---- scrub and evaluation ----

function ScrubAndEvaluate({ exercise, run, busy }: { exercise: TeacherExercise; run: Run; busy: string }) {
  const saved = exercise.evaluation as WritingEvaluation | null;
  const [scrubbed, setScrubbed] = useState(exercise.scrubbed_answers.text ?? "");
  const [scrubDirty, setScrubDirty] = useState(false);
  const [draft, setDraft] = useState<WritingEvaluation | null>(saved);
  const [evalDirty, setEvalDirty] = useState(false);
  const [note, setNote] = useState("");
  const [codes, setCodes] = useState<Code[]>([]);
  const [confirmSwitch, setConfirmSwitch] = useState(false);

  useEffect(() => {
    api<Code[]>("/taxonomy").then(setCodes);
  }, []);
  // A fresh copy from the server replaces everything being edited here.
  useEffect(() => {
    setScrubbed(exercise.scrubbed_answers.text ?? "");
    setScrubDirty(false);
    setDraft(exercise.evaluation as WritingEvaluation | null);
    setEvalDirty(false);
  }, [exercise]);

  const id = exercise.exercise_id;
  const editable = REVIEW_STATES.includes(exercise.state);
  const evaluated = saved !== null && exercise.state !== "scrub_review";
  const photo = exercise.final_source === "photo";
  const original = photo ? exercise.transcription ?? "" : (exercise.answers.text as string | undefined) ?? "";
  const other = photo ? "typed" : "photo";
  const canSwitch = editable && (photo ? !!(exercise.answers.text as string | undefined)?.trim() : exercise.transcription != null);

  const editDraft = (patch: Partial<WritingEvaluation>) => {
    setDraft({ ...draft!, ...patch });
    setEvalDirty(true);
  };
  const evaluate = (withNote: string) =>
    run("Evaluating… this can take a minute or two.", () => api(`/exercises/${id}/evaluate`, "POST", { note: withNote }));

  return (
    <section className="panel stack">
      <h2>Scrub and evaluate</h2>
      {exercise.state === "scrub_review" && (
        <p className="notice">
          Remove names and personal details from the scrubbed copy, save, then send for evaluation. Only the scrubbed
          copy is sent to the AI, and it's what the student sees with their results.
        </p>
      )}
      {exercise.state === "evaluating" && (
        <p className="notice">An evaluation is running. Come back to this page in a minute or two.</p>
      )}

      <div className="row top">
        <div className="grow">
          <strong>Original – {photo ? "handwritten (transcription)" : "typed"}</strong>{" "}
          <span className="muted">(read-only, never sent)</span>
          <p className="original">{original}</p>
        </div>
        <label className="grow">
          Scrubbed copy <span className="muted">(sent to the AI)</span>
          <textarea
            rows={12}
            value={scrubbed}
            disabled={!editable || !!busy}
            onChange={(e) => {
              setScrubbed(e.target.value);
              setScrubDirty(true);
            }}
          />
        </label>
      </div>

      {editable && (
        <div className="row">
          <button
            onClick={() => run("Saving…", () => api(`/exercises/${id}/scrubbed`, "PUT", { scrubbed_answers: { text: scrubbed } }))}
            disabled={!scrubDirty || !!busy}
          >
            Save scrubbed text
          </button>
          {exercise.state === "scrub_review" && (
            <button className="primary" onClick={() => evaluate("")} disabled={scrubDirty || !!busy}>
              Send for evaluation
            </button>
          )}
          {canSwitch &&
            (confirmSwitch ? (
              <>
                <span>Start again from the {other} version? This replaces the scrubbed copy and any evaluation.</span>
                <button onClick={() => run("Saving…", () => api(`/exercises/${id}/final-source`, "POST", { source: other })).then(() => setConfirmSwitch(false))}>
                  Yes, switch
                </button>
                <button onClick={() => setConfirmSwitch(false)}>Cancel</button>
              </>
            ) : (
              <button onClick={() => setConfirmSwitch(true)} disabled={!!busy}>
                Use the {other} version instead…
              </button>
            ))}
        </div>
      )}
      {scrubDirty && evaluated && (
        <p className="muted">Saving changes to the scrubbed text discards the evaluation; you'll send it again.</p>
      )}

      {evaluated && draft && (
        <div className="evaluation stack">
          <SpannedText
            text={exercise.scrubbed_answers.text ?? ""}
            spans={saved.annotations.map((a) => ({ start: a.start!, end: a.end!, code: a.code }))}
          />
          <label>
            Overall comment (shown to the student)
            <textarea
              rows={2}
              value={draft.comment}
              disabled={!editable}
              onChange={(e) => editDraft({ comment: e.target.value })}
            />
          </label>
          <AnnotationsEditor
            annotations={draft.annotations}
            codes={codes}
            disabled={!editable}
            onChange={(annotations: Annotation[]) => editDraft({ annotations })}
          />
          {editable && (
            <>
              <div className="row">
                <button
                  onClick={() =>
                    run("Saving…", () =>
                      api(`/exercises/${id}/evaluation`, "PUT", { annotations: withoutOffsets(draft.annotations), comment: draft.comment }),
                    )
                  }
                  disabled={!evalDirty || !!busy}
                >
                  Save evaluation changes
                </button>
                {exercise.state === "draft_ready" && (
                  <button
                    className="primary"
                    onClick={() => run("Approving…", () => api(`/exercises/${id}/approve`, "POST"))}
                    disabled={evalDirty || scrubDirty || !!busy}
                  >
                    Approve
                  </button>
                )}
              </div>
              {evalDirty && <p className="muted">Save your evaluation changes before approving.</p>}
              <label>
                Regenerate the evaluation with a note (optional)
                <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. 'downtown' is not an error" />
              </label>
              <button onClick={() => evaluate(note)} disabled={scrubDirty || !!busy}>Regenerate evaluation</button>
              {evalDirty && <p className="muted">Regenerating replaces your unsaved changes.</p>}
            </>
          )}
        </div>
      )}
    </section>
  );
}

// ---- revision ----

const OUTCOMES: { value: Outcome; label: string }[] = [
  { value: "fixed", label: "Fixed" },
  { value: "unfixed", label: "Not fixed" },
  { value: "changed_wrongly", label: "Changed wrongly" },
];

function RevisionReview({ exercise, run, busy }: { exercise: TeacherExercise; run: Run; busy: string }) {
  const revision = exercise.revision!;
  const evaluation = exercise.evaluation as WritingEvaluation;
  const text = exercise.scrubbed_answers.text ?? "";
  const [outcomes, setOutcomes] = useState(revision.outcomes);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    setOutcomes(revision.outcomes);
    setDirty(false);
  }, [revision]);

  const codeOf = (index: string) => evaluation.annotations[Number(index)].code;
  const unmarked = revision.changed.filter((c) => !outcomes[c.index]).length;

  return (
    <section className="panel stack">
      <h2>Revision</h2>
      {revision.changed.length === 0 ? (
        <p>The student submitted their revision without changing anything.</p>
      ) : (
        <>
          <div className="row top">
            <div className="grow">
              <strong>Before</strong>
              <SpannedText text={text} spans={evaluation.annotations.map((a) => ({ start: a.start!, end: a.end!, code: a.code }))} />
            </div>
            <div className="grow">
              <strong>After</strong> <span className="muted">(changed words highlighted)</span>
              <SpannedText text={revision.revised_text} spans={revision.changed.map((c) => ({ ...c, code: codeOf(c.index) }))} />
            </div>
          </div>
          <table className="annotations">
            <thead>
              <tr><th>Code</th><th>Was</th><th>Student changed it to</th><th>Suggested correction</th><th>Outcome</th></tr>
            </thead>
            <tbody>
              {revision.changed.map((c) => {
                const a = evaluation.annotations[Number(c.index)];
                return (
                  <tr key={c.index}>
                    <td>{a.code}</td>
                    <td>{text.slice(a.start, a.end)}</td>
                    <td>{revision.edits[c.index] || <em className="muted">(deleted)</em>}</td>
                    <td className="muted">{a.correction}</td>
                    <td>
                      <select
                        value={outcomes[c.index] ?? ""}
                        disabled={!!busy}
                        onChange={(e) => {
                          setOutcomes({ ...outcomes, [c.index]: e.target.value as Outcome });
                          setDirty(true);
                        }}
                      >
                        <option value="" disabled>Choose…</option>
                        {OUTCOMES.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                      </select>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="row">
            <button
              className="primary"
              onClick={() => run("Saving…", () => api(`/exercises/${exercise.exercise_id}/revision/outcomes`, "PUT", { outcomes }))}
              disabled={!dirty || !!busy}
            >
              Save outcomes
            </button>
            {unmarked > 0 && <span className="muted">{unmarked} change(s) not marked yet.</span>}
          </div>
        </>
      )}
    </section>
  );
}
