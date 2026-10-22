// One exercise for the student: answer, autosave, submit; or, once
// released, the results (correct/incorrect, right answer, explanation).
// Writing: a response with a word count and, optionally, photos of
// handwritten pages; then the coded results and the one revision round
// (tap a flagged span, retype just those words).
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import { inPageOrder, toCleanJpeg, type PageLink } from "../photos";
import SpannedText from "../SpannedText";
import type { Answer, Answers, Outcome, StudentExercise, StudentItem, StudentSpan } from "../types";
import { wordCount } from "../words";
import { stateLabel } from "./StudentApp";

const AUTOSAVE_DELAY_MS = 1500;
const RETRY_DELAY_MS = 5000;
const RESULTS_STATES = ["released", "revision_open", "revision_submitted", "revision_reviewed"];

type SaveStatus = "saved" | "saving" | "unsaved" | "offline" | "failed";

export default function DoExercise({ exerciseId, onBack }: { exerciseId: string; onBack: () => void }) {
  const [exercise, setExercise] = useState<StudentExercise | null>(null);
  const [loadError, setLoadError] = useState("");

  const load = useCallback(() => {
    api<StudentExercise>(`/exercises/${exerciseId}`)
      .then(setExercise)
      .catch(() => setLoadError("Could not open this exercise. Go back and try again."));
  }, [exerciseId]);
  useEffect(load, [load]);

  if (loadError) return <Shell onBack={onBack}><p className="error">{loadError}</p></Shell>;
  if (!exercise) return <Shell onBack={onBack}><p>Loading…</p></Shell>;

  const open = exercise.state === "assigned" || exercise.state === "in_progress";
  return (
    <Shell onBack={onBack}>
      <h1>{exercise.title}</h1>
      {open ? (
        <AnswerForm exercise={exercise} onSubmitted={onBack} />
      ) : RESULTS_STATES.includes(exercise.state) ? (
        exercise.kind === "writing" ? (
          <WritingResults exercise={exercise} onRevised={load} />
        ) : (
          <Results exercise={exercise} />
        )
      ) : (
        <p className="notice">{stateLabel(exercise.state)}. You'll see your results here once they're ready.</p>
      )}
    </Shell>
  );
}

function Shell({ onBack, children }: { onBack: () => void; children: React.ReactNode }) {
  return (
    <main className="page narrow">
      <button className="link" onClick={onBack}>← My work</button>
      {children}
    </main>
  );
}

// ---- autosave and submit, shared by answers and revisions ----

// Keeps `value` saved to `path` (FR-13): a short pause after each change,
// straight away when the phone is locked or the app switched, and retried
// while there's no signal. The body is {[field]: value}.
function useAutosave<T>(path: string, field: string, initial: T) {
  const [value, setValue] = useState(initial);
  const [status, setStatus] = useState<SaveStatus>("saved");
  const [saveError, setSaveError] = useState("");
  const latest = useRef(initial);
  // Bumped on every change, so a save that finishes after newer typing
  // doesn't claim everything is saved.
  const version = useRef(0);
  const timer = useRef<number | undefined>(undefined);

  const save = useCallback(async () => {
    window.clearTimeout(timer.current);
    const savingVersion = version.current;
    setStatus("saving");
    try {
      await api(path, "PUT", { [field]: latest.current });
      if (version.current === savingVersion) setStatus("saved");
    } catch (err) {
      if (err instanceof ApiError && err.status < 500) {
        // The server refused (e.g. already submitted): retrying won't help.
        setStatus("failed");
        setSaveError(err.message);
      } else {
        // Lost signal: keep the work on screen and keep retrying.
        setStatus("offline");
        timer.current = window.setTimeout(save, RETRY_DELAY_MS);
      }
    }
  }, [path, field]);

  function change(next: T) {
    latest.current = next;
    version.current += 1;
    setValue(next);
    setStatus("unsaved");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(save, AUTOSAVE_DELAY_MS);
  }

  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden" && status !== "saved") save();
    };
    document.addEventListener("visibilitychange", onHide);
    return () => document.removeEventListener("visibilitychange", onHide);
  }, [save, status]);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  // Before submitting: no autosave may land after the submit.
  const stop = () => window.clearTimeout(timer.current);

  return { value, latest, change, stop, status, saveError };
}

function SaveStatusLine({ status, saveError }: { status: SaveStatus; saveError: string }) {
  return (
    <p className={`save-status ${status}`} aria-live="polite">
      {status === "saved" && "All changes saved"}
      {status === "saving" && "Saving…"}
      {status === "unsaved" && "Saving soon…"}
      {status === "offline" && "Not saved yet – no connection. We'll keep trying."}
      {status === "failed" && `Not saved. ${saveError}`}
    </p>
  );
}

// Submit with a confirmation step (FR-15).
function SubmitButton({ question, onSubmit }: { question: string; onSubmit: () => Promise<void> }) {
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setSubmitting(true);
    setError("");
    try {
      await onSubmit();
    } catch (err) {
      setError(`Not submitted. ${(err as Error).message}`);
      setSubmitting(false);
    }
  }

  if (!confirming) return <button className="primary big" onClick={() => setConfirming(true)}>Submit</button>;
  return (
    <div className="confirm">
      <p><strong>Submit now?</strong> {question}</p>
      <div className="row">
        <button className="primary big" onClick={submit} disabled={submitting}>
          {submitting ? "Submitting…" : "Yes, submit"}
        </button>
        <button className="big" onClick={() => setConfirming(false)} disabled={submitting}>Not yet</button>
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  );
}

// ---- answering ----

function AnswerForm({ exercise, onSubmitted }: { exercise: StudentExercise; onSubmitted: () => void }) {
  const path = `/exercises/${exercise.exercise_id}`;
  const answers = useAutosave<Answers>(`${path}/answers`, "answers", exercise.answers);
  const update = (itemId: string, answer: Answer) => answers.change({ ...answers.latest.current, [itemId]: answer });

  async function submit() {
    answers.stop();
    await api(`${path}/submit`, "POST", { answers: answers.latest.current });
    onSubmitted();
  }

  return (
    <>
      <SaveStatusLine status={answers.status} saveError={answers.saveError} />
      {exercise.kind === "writing" ? (
        <>
          <WritingInput exercise={exercise} text={(answers.value.text as string) ?? ""} onChange={(t) => update("text", t)} />
          <HandwrittenPages exerciseId={exercise.exercise_id} />
        </>
      ) : (
        <ol className="items">
          {exercise.items.map((item) => (
            <li key={item.id} className="item">
              <ItemInput item={item} answer={answers.value[item.id]} onChange={(a) => update(item.id, a)} />
            </li>
          ))}
        </ol>
      )}
      <SubmitButton question="You can't change your answers after this." onSubmit={submit} />
    </>
  );
}

function WritingInput({
  exercise,
  text,
  onChange,
}: {
  exercise: StudentExercise;
  text: string;
  onChange: (text: string) => void;
}) {
  const count = wordCount(text);
  const { min_words: min, max_words: max } = exercise;
  // A gentle reminder only: the student can still submit (teacher decision).
  let hint = "";
  if (min && count < min) hint = `Try to write at least ${min} words.`;
  else if (max && count > max) hint = `Try to keep it to ${max} words or fewer.`;
  const limits = min && max ? `${min}–${max} words` : min ? `at least ${min} words` : max ? `up to ${max} words` : "";

  return (
    <div className="item">
      <p className="instruction">{exercise.prompt}</p>
      {limits && <p className="muted">Length: {limits}</p>}
      <textarea rows={12} value={text} onChange={(e) => onChange(e.target.value)} aria-label="Your writing" />
      <p className={`word-count${hint ? " outside" : ""}`} aria-live="polite">
        {count} {count === 1 ? "word" : "words"}
        {hint && ` – ${hint}`}
      </p>
    </div>
  );
}

// Photos of handwritten pages, taken by the student (FR-23). They see
// their own pages until they submit; after that only the teacher does.
function HandwrittenPages({ exerciseId }: { exerciseId: string }) {
  const url = `/exercises/${exerciseId}/photos`;
  const [pages, setPages] = useState<PageLink[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [confirmRemove, setConfirmRemove] = useState(false);

  useEffect(() => {
    api<PageLink[]>(url).then(setPages, () => setPages([]));
  }, [url]);

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setError("");
    let count = pages.length;
    for (const file of inPageOrder(files)) {
      setBusy(`Sending page ${count + 1}…`);
      try {
        let photo: Blob;
        try {
          photo = await toCleanJpeg(file);
        } catch {
          throw new Error("That photo couldn't be opened. Please try taking it again.");
        }
        const next = await api<PageLink[]>(url, "POST", photo);
        setPages(next);
        count = next.length;
      } catch (err) {
        setError(`Page not added. ${(err as Error).message}`);
        break;
      }
    }
    setBusy("");
  }

  async function removeAll() {
    setBusy("Removing…");
    setError("");
    try {
      setPages(await api<PageLink[]>(url, "DELETE"));
      setConfirmRemove(false);
    } catch (err) {
      setError((err as Error).message);
    }
    setBusy("");
  }

  const pick = (e: React.ChangeEvent<HTMLInputElement>) => {
    upload(e.target.files);
    e.target.value = "";
  };

  return (
    <div className="item stack">
      <p className="instruction">Wrote it on paper? Add a photo of each page, in order.</p>
      <p className="muted">Write only your first name on the paper. Make sure the whole page is in the photo and easy to read.</p>
      <div className="row">
        <label className="button">
          📷 Take a photo
          <input type="file" accept="image/*" capture="environment" hidden disabled={!!busy} onChange={pick} />
        </label>
        <label className="button">
          Choose photos
          <input type="file" accept="image/*" multiple hidden disabled={!!busy} onChange={pick} />
        </label>
      </div>
      {pages.length > 0 && (
        <>
          <div className="photos">
            {pages.map((p) => (
              <figure key={p.page}>
                <img src={p.url} alt={`Your page ${p.page}`} />
                <figcaption>Page {p.page}</figcaption>
              </figure>
            ))}
          </div>
          {confirmRemove ? (
            <div className="row">
              <span>Remove all your pages and start again?</span>
              <button onClick={removeAll} disabled={!!busy}>Yes, remove</button>
              <button onClick={() => setConfirmRemove(false)} disabled={!!busy}>Cancel</button>
            </div>
          ) : (
            <button onClick={() => setConfirmRemove(true)} disabled={!!busy}>Start the pages again…</button>
          )}
        </>
      )}
      {busy && <p className="notice">{busy}</p>}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

function ItemInput({ item, answer, onChange }: { item: StudentItem; answer?: Answer; onChange: (a: Answer) => void }) {
  if (item.type === "fill_blank") {
    const filled = (answer as Record<string, string>) ?? {};
    const parts = item.text!.split(/_{3,}/);
    return (
      <>
        <p className="instruction">Type the missing word or words.</p>
        <p className="sentence">
          {parts.map((part, i) => (
            <span key={i}>
              {part}
              {i < item.blank_ids!.length && (
                <input
                  className="blank"
                  aria-label={`Blank ${i + 1}`}
                  autoCapitalize="off"
                  autoCorrect="off"
                  spellCheck={false}
                  value={filled[item.blank_ids![i]] ?? ""}
                  onChange={(e) => onChange({ ...filled, [item.blank_ids![i]]: e.target.value })}
                />
              )}
            </span>
          ))}
        </p>
      </>
    );
  }

  if (item.type === "reorder") {
    // Tap-to-place (FR-14): tap a word to add it to your sentence; tap a
    // word in your sentence to take it back out.
    const placed = (answer as number[]) ?? [];
    const chunks = item.chunks!;
    return (
      <>
        <p className="instruction">Tap the words in the right order to make a sentence. Tap a word in your sentence to take it back.</p>
        <div className="placed" aria-label="Your sentence">
          {placed.length === 0 && <span className="hint">Your sentence will appear here.</span>}
          {placed.map((idx, pos) => (
            <button key={pos} className="chip placed-chip" onClick={() => onChange(placed.filter((_, p) => p !== pos))}>
              {chunks[idx]}
            </button>
          ))}
        </div>
        <div className="pool" aria-label="Words to use">
          {chunks.map((chunk, idx) =>
            placed.includes(idx) ? null : (
              <button key={idx} className="chip" onClick={() => onChange([...placed, idx])}>
                {chunk}
              </button>
            ),
          )}
        </div>
      </>
    );
  }

  return (
    <>
      <p className="instruction">{item.prompt}</p>
      <textarea rows={5} value={(answer as string) ?? ""} onChange={(e) => onChange(e.target.value)} />
    </>
  );
}

// ---- grammar results ----

function Results({ exercise }: { exercise: StudentExercise }) {
  return (
    <ol className="items">
      {exercise.items.map((item) => (
        <li key={item.id} className={`item ${resultClass(item)}`}>
          <ResultItem item={item} answer={exercise.answers[item.id]} />
        </li>
      ))}
    </ol>
  );
}

function resultClass(item: StudentItem): string {
  if (item.type === "short_answer") {
    return item.mark === "correct" ? "right" : item.mark === "incorrect" ? "wrong" : item.mark ? "partial" : "";
  }
  return item.correct === undefined ? "" : item.correct ? "right" : "wrong";
}

const MARK_TEXT = { correct: "✓ Correct", partial: "◐ Partly correct", incorrect: "✗ Not quite" };

// What each code on the page means. Tap or hover a code to see it too.
function Legend({ spans }: { spans: StudentSpan[] }) {
  const meanings = [...new Map(spans.map((s) => [s.code, s.meaning])).entries()];
  if (meanings.length === 0) return null;
  return (
    <ul className="legend">
      {meanings.map(([code, meaning]) => (
        <li key={code}><span className="code">{code}</span> {meaning}</li>
      ))}
    </ul>
  );
}

function ResultItem({ item, answer }: { item: StudentItem; answer?: Answer }) {
  if (item.type === "short_answer") {
    // FR-21: the mark, the feedback sentence, and the answer with each
    // error marked by its code.
    if (!item.mark) {
      return (
        <>
          <p className="instruction">{item.prompt}</p>
          <p className="your-answer">{(answer as string) || "(no answer)"}</p>
        </>
      );
    }
    const spans = item.spans ?? [];
    return (
      <>
        <p className="verdict">{MARK_TEXT[item.mark]}</p>
        <p className="instruction">{item.prompt}</p>
        <SpannedText text={item.answer_text ?? ""} spans={spans} />
        <Legend spans={spans} />
        {item.feedback && <p className="explanation">{item.feedback}</p>}
      </>
    );
  }

  let yours: string;
  let right: string | null = null;
  if (item.type === "fill_blank") {
    const filled = (answer as Record<string, string>) ?? {};
    yours = fillSentence(item.text!, item.blank_ids!, filled);
    if (item.correct_answer) right = fillSentence(item.text!, item.blank_ids!, item.correct_answer as Record<string, string>);
  } else {
    yours = ((answer as number[]) ?? []).map((i) => item.chunks![i]).join(" ") || "(no answer)";
    if (item.correct_answer) right = (item.correct_answer as string[]).join(" ");
  }

  return (
    <>
      <p className="verdict">{item.correct ? "✓ Correct" : "✗ Not quite"}</p>
      <p className="your-answer">Your answer: {yours}</p>
      {right && <p className="right-answer">Correct answer: {right}</p>}
      {item.explanation && <p className="explanation">{item.explanation}</p>}
    </>
  );
}

function fillSentence(text: string, blankIds: string[], values: Record<string, string>): string {
  let i = 0;
  return text.replace(/_{3,}/g, () => `[${values[blankIds[i++]] || "…"}]`);
}

// ---- writing results and revision ----

function WritingResults({ exercise, onRevised }: { exercise: StudentExercise; onRevised: () => void }) {
  const spans = exercise.spans ?? [];
  const text = exercise.answer_text ?? "";
  return (
    <>
      <div className="item">
        <p className="instruction">{exercise.prompt}</p>
        {exercise.state === "revision_open" ? (
          <Reviser exercise={exercise} onSubmitted={onRevised} />
        ) : (
          <SpannedText text={text} spans={spans} />
        )}
        <Legend spans={spans} />
        {exercise.comment && <p className="explanation">{exercise.comment}</p>}
      </div>
      {exercise.state === "revision_submitted" && (
        <div className="item">
          <p className="verdict">Your revision (submitted)</p>
          <p className="spanned">{exercise.revised_text}</p>
        </div>
      )}
      {exercise.state === "revision_reviewed" && <CheckedRevision exercise={exercise} />}
    </>
  );
}

const OUTCOME_TEXT: Record<Outcome, string> = {
  fixed: "✓ Fixed",
  unfixed: "✗ Not fixed yet",
  changed_wrongly: "⚠ Changed, but not right",
};
const OUTCOME_CLASS: Record<Outcome, string> = { fixed: "right", unfixed: "wrong", changed_wrongly: "partial" };

// How the revision went, once the teacher has checked it (FR-27): each
// part the student changed, with the teacher's mark, and the suggested
// correction for anything not fixed.
function CheckedRevision({ exercise }: { exercise: StudentExercise }) {
  const text = exercise.answer_text ?? "";
  const spans = exercise.spans ?? [];
  const outcomes = exercise.outcomes ?? {};
  const changed = Object.keys(outcomes).sort((a, b) => spans[Number(a)].start - spans[Number(b)].start);
  return (
    <>
      <div className="item">
        <p className="verdict">Your revision</p>
        <p className="spanned">{exercise.revised_text}</p>
      </div>
      {changed.length === 0 && <p className="muted">You didn't change anything in your revision.</p>}
      {changed.map((index) => {
        const span = spans[Number(index)];
        const outcome = outcomes[index];
        const correction = exercise.corrections?.[index];
        return (
          <div key={index} className={`item ${OUTCOME_CLASS[outcome]}`}>
            <p className="verdict">{OUTCOME_TEXT[outcome]}</p>
            <p>
              {span.code} ({span.meaning}): “{text.slice(span.start, span.end)}” → “{exercise.revision_edits?.[index] || "(deleted)"}”
            </p>
            {correction !== undefined && <p className="right-answer">Suggested correction: {correction || "(delete these words)"}</p>}
          </div>
        );
      })}
    </>
  );
}

// The one revision round (FR-26): the text with each flagged span as a
// button; tap one to retype just those words.
function Reviser({ exercise, onSubmitted }: { exercise: StudentExercise; onSubmitted: () => void }) {
  const path = `/exercises/${exercise.exercise_id}/revision`;
  const edits = useAutosave<Record<string, string>>(path, "edits", exercise.revision_edits ?? {});
  const [selected, setSelected] = useState<number | null>(null);
  const text = exercise.answer_text ?? "";
  const spans = exercise.spans ?? [];
  const original = (i: number) => text.slice(spans[i].start, spans[i].end);
  const current = (i: number) => edits.value[String(i)] ?? original(i);

  function setEdit(i: number, words: string | null) {
    const next = { ...edits.latest.current };
    if (words === null) delete next[String(i)];
    else next[String(i)] = words;
    edits.change(next);
  }

  async function submit() {
    edits.stop();
    await api(`${path}/submit`, "POST", { edits: edits.latest.current });
    onSubmitted();
  }

  // The text in pieces: plain text between spans, and a button per span
  // (in reading order; `i` stays the span's position in the list).
  const order = spans.map((_, i) => i).sort((a, b) => spans[a].start - spans[b].start);
  const pieces: React.ReactNode[] = [];
  let at = 0;
  for (const i of order) {
    pieces.push(text.slice(at, spans[i].start));
    const changed = current(i) !== original(i);
    pieces.push(
      <button
        key={i}
        className={`span-button${changed ? " changed" : ""}${selected === i ? " selected" : ""}`}
        onClick={() => setSelected(selected === i ? null : i)}
      >
        {current(i) || "…"}
        <span className="code">{spans[i].code}</span>
      </button>,
    );
    at = spans[i].end;
  }
  pieces.push(text.slice(at));

  return (
    <>
      <p className="notice">
        You can correct each marked part once. Tap a marked part, then type your correction.
      </p>
      <SaveStatusLine status={edits.status} saveError={edits.saveError} />
      <p className="spanned">{pieces}</p>
      {selected !== null && (
        <div className="span-editor">
          <label>
            Change “{original(selected)}” ({spans[selected].code}: {spans[selected].meaning}) to:
            <input
              autoFocus
              autoCapitalize="off"
              value={current(selected)}
              onChange={(e) => setEdit(selected, e.target.value)}
            />
          </label>
          <div className="row">
            <button onClick={() => setSelected(null)}>Done</button>
            {current(selected) !== original(selected) && (
              <button onClick={() => setEdit(selected, null)}>Undo my change</button>
            )}
          </div>
        </div>
      )}
      <SubmitButton question="You can only revise once." onSubmit={submit} />
    </>
  );
}
