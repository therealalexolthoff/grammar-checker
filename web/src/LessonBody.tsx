// A lesson's text and worked examples, as the student reads it (FR-28).
// Used on both sides: the student's lesson screen and the teacher's copy.
import type { LessonExample } from "./types";

export default function LessonBody({ explanation, examples }: { explanation: string; examples: LessonExample[] }) {
  return (
    <>
      <p className="lesson-text">{explanation}</p>
      <h2>Examples</h2>
      <ol className="items">
        {examples.map((ex, i) => (
          <li key={i} className="item">
            <p className="wrong-example">✗ {ex.incorrect}</p>
            <p className="right-example">✓ {ex.correct}</p>
            <p className="explanation">{ex.note}</p>
          </li>
        ))}
      </ol>
    </>
  );
}
