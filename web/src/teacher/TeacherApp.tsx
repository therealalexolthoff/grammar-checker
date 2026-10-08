// Teacher home (laptop-first): pick a student, see their exercises,
// generate a new one, manage student accounts.
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import type { ExerciseSummary, Student, TeacherExercise } from "../types";
import ExerciseScreen, { stateLabel } from "./ExerciseScreen";
import StudentsPanel from "./StudentsPanel";

export default function TeacherApp() {
  const [students, setStudents] = useState<Student[]>([]);
  const [studentId, setStudentId] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [showStudents, setShowStudents] = useState(false);

  const loadStudents = () => api<Student[]>("/students").then(setStudents);
  useEffect(() => {
    loadStudents();
  }, []);

  if (openId) return <ExerciseScreen exerciseId={openId} onBack={() => setOpenId(null)} />;

  const active = students.filter((s) => s.active);
  return (
    <main className="page wide">
      <div className="row spread">
        <h1>Exercises</h1>
        <button onClick={() => setShowStudents(!showStudents)}>{showStudents ? "Hide students" : "Manage students"}</button>
      </div>
      {showStudents && <StudentsPanel students={students} onChange={loadStudents} />}
      <label>
        Student{" "}
        <select value={studentId} onChange={(e) => setStudentId(e.target.value)}>
          <option value="">Choose a student…</option>
          {active.map((s) => (
            <option key={s.student_id} value={s.student_id}>{s.username}</option>
          ))}
        </select>
      </label>
      {studentId && <StudentExercises key={studentId} studentId={studentId} onOpen={setOpenId} />}
    </main>
  );
}

function StudentExercises({ studentId, onOpen }: { studentId: string; onOpen: (id: string) => void }) {
  const [list, setList] = useState<ExerciseSummary[] | null>(null);
  const [kind, setKind] = useState<"grammar" | "writing">("grammar");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api<ExerciseSummary[]>(`/exercises?student_id=${encodeURIComponent(studentId)}`).then(setList);
  }, [studentId]);

  async function generate(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const ex = await api<TeacherExercise>("/exercises/generate", "POST", { student_id: studentId, kind, description });
      onOpen(ex.exercise_id);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <>
      <form onSubmit={generate} className="stack panel">
        <div className="row">
          <strong>New exercise:</strong>
          <label className="check">
            <input type="radio" checked={kind === "grammar"} onChange={() => setKind("grammar")} /> Grammar
          </label>
          <label className="check">
            <input type="radio" checked={kind === "writing"} onChange={() => setKind("writing")} /> Writing
          </label>
        </div>
        <label>
          Describe it
          <textarea
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={
              kind === "grammar"
                ? "e.g. 4 fill-in-the-blank items on past simple vs present perfect, and 2 word-order items"
                : "e.g. a short email to a landlord about a broken heater, 80 to 150 words"
            }
            required
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="primary" disabled={busy}>{busy ? "Generating… (up to a minute)" : "Generate"}</button>
      </form>
      <table>
        <thead>
          <tr><th>Title</th><th>Stage</th></tr>
        </thead>
        <tbody>
          {list?.map((ex) => (
            <tr key={ex.exercise_id} className="clickable" onClick={() => onOpen(ex.exercise_id)}>
              <td>{ex.title}</td>
              <td>{stateLabel(ex.state)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {list?.length === 0 && <p>No exercises for this student yet.</p>}
    </>
  );
}
