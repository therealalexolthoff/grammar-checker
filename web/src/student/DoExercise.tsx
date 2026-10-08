// One exercise for the student: answer, autosave, submit; or, once
// released, the results (correct/incorrect, right answer, explanation).
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import SpannedText from "../SpannedText";
import type { Answer, Answers, StudentExercise, StudentItem } from "../types";
import { stateLabel } from "./StudentApp";

const AUTOSAVE_DELAY_MS = 1500;
const RETRY_DELAY_MS = 5000;

type SaveStatus = "saved" | "saving" | "unsaved" | "offline" | "failed";

export default function DoExercise({ exerciseId, onBack }: { exerciseId: string; onBack: () => void }) {
  const [exercise, setExercise] = useState<StudentExercise | null>(null);
  const [answers, setAnswers] = useState<Answers>({});
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    api<StudentExercise>(`/exercises/${exerciseId}`)
      .then((ex) => {
        setExercise(ex);
        setAnswers(ex.answers);
      })
      .catch(() => setLoadError("Could not open this exercise. Go back and try again."));
  }, [exerciseId]);

  if (loadError) return <Shell onBack={onBack}><p className="error">{loadError}</p></Shell>;
  if (!exercise) return <Shell onBack={onBack}><p>Loading…</p></Shell>;

  const open = exercise.state === "assigned" || exercise.state === "in_progress";
  return (
    <Shell onBack={onBack}>
      <h1>{exercise.title}</h1>
      {open ? (
        <AnswerForm exercise={exercise} answers={answers} setAnswers={setAnswers} onSubmitted={onBack} />
      ) : exercise.state === "released" ? (
        <Results exercise={exercise} />
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

function AnswerForm({
  exercise,
  answers,
  setAnswers,
  onSubmitted,
}: {
  exercise: StudentExercise;
  answers: Answers;
  setAnswers: (a: Answers) => void;
  onSubmitted: () => void;
}) {
  const [status, setStatus] = useState<SaveStatus>("saved");
  const [confirming, setConfirming] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [saveError, setSaveError] = useState("");
  const latest = useRef(answers);
  // Bumped on every change, so a save that finishes after newer typing
  // doesn't claim everything is saved.
  const version = useRef(0);
  const timer = useRef<number | undefined>(undefined);

  const save = useCallback(async () => {
    window.clearTimeout(timer.current);
    const savingVersion = version.current;
    setStatus("saving");
    try {
      await api(`/exercises/${exercise.exercise_id}/answers`, "PUT", { answers: latest.current });
      if (version.current === savingVersion) setStatus("saved");
    } catch (err) {
      if (err instanceof ApiError && err.status < 500) {
        // The server refused (e.g. already submitted): retrying won't help.
        setStatus("failed");
        setSaveError(err.message);
      } else {
        // Lost signal: keep the answers on screen and keep retrying.
        setStatus("offline");
        timer.current = window.setTimeout(save, RETRY_DELAY_MS);
      }
    }
  }, [exercise.exercise_id]);

  function update(itemId: string, answer: Answer) {
    const next = { ...latest.current, [itemId]: answer };
    latest.current = next;
    version.current += 1;
    setAnswers(next);
    setStatus("unsaved");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(save, AUTOSAVE_DELAY_MS);
  }

  // Save straight away when the student switches apps or locks the phone.
  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden" && status !== "saved") save();
    };
    document.addEventListener("visibilitychange", onHide);
    return () => document.removeEventListener("visibilitychange", onHide);
  }, [save, status]);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function submit() {
    window.clearTimeout(timer.current);
    setSubmitting(true);
    setSubmitError("");
    try {
      await api(`/exercises/${exercise.exercise_id}/submit`, "POST", { answers: latest.current });
      onSubmitted();
    } catch (err) {
      setSubmitError(`Not submitted. ${(err as Error).message}`);
      setSubmitting(false);
    }
  }

  return (
    <>
      <p className={`save-status ${status}`} aria-live="polite">
        {status === "saved" && "All answers saved"}
        {status === "saving" && "Saving…"}
        {status === "unsaved" && "Saving soon…"}
        {status === "offline" && "Not saved yet – no connection. We'll keep trying."}
        {status === "failed" && `Not saved. ${saveError}`}
      </p>
      <ol className="items">
        {exercise.items.map((item) => (
          <li key={item.id} className="item">
            <ItemInput item={item} answer={answers[item.id]} onChange={(a) => update(item.id, a)} />
          </li>
        ))}
      </ol>
      {!confirming ? (
        <button className="primary big" onClick={() => setConfirming(true)}>Submit</button>
      ) : (
        <div className="confirm">
          <p><strong>Submit now?</strong> You can't change your answers after this.</p>
          <div className="row">
            <button className="primary big" onClick={submit} disabled={submitting}>
              {submitting ? "Submitting…" : "Yes, submit"}
            </button>
            <button className="big" onClick={() => setConfirming(false)} disabled={submitting}>Not yet</button>
          </div>
          {submitError && <p className="error">{submitError}</p>}
        </div>
      )}
    </>
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

function ResultItem({ item, answer }: { item: StudentItem; answer?: Answer }) {
  if (item.type === "short_answer") {
    // FR-21: the mark, the feedback sentence, and the answer with each
    // error marked by its code. Tap or hover a code to see what it means.
    if (!item.mark) {
      return (
        <>
          <p className="instruction">{item.prompt}</p>
          <p className="your-answer">{(answer as string) || "(no answer)"}</p>
        </>
      );
    }
    const spans = item.spans ?? [];
    const meanings = [...new Map(spans.map((s) => [s.code, s.meaning])).entries()];
    return (
      <>
        <p className="verdict">{MARK_TEXT[item.mark]}</p>
        <p className="instruction">{item.prompt}</p>
        <SpannedText text={item.answer_text ?? ""} spans={spans} />
        {meanings.length > 0 && (
          <ul className="legend">
            {meanings.map(([code, meaning]) => (
              <li key={code}><span className="code">{code}</span> {meaning}</li>
            ))}
          </ul>
        )}
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
