// Teacher home (laptop-first): the class overview, or one student's
// exercises, lessons, and profile & notes. Also manages student accounts.
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import type { ExerciseSummary, LessonSummary, Student, TeacherExercise, TeacherLesson } from "../types";
import ExerciseScreen, { stateLabel } from "./ExerciseScreen";
import LessonScreen from "./LessonScreen";
import Overview from "./Overview";
import ProfilePanel from "./ProfilePanel";
import StudentsPanel from "./StudentsPanel";
import WritingForStudents from "./WritingForStudents";

type Tab = "exercises" | "lessons" | "profile";
const TABS: { tab: Tab; label: string }[] = [
  { tab: "exercises", label: "Exercises" },
  { tab: "lessons", label: "Lessons" },
  { tab: "profile", label: "Profile & notes" },
];

export default function TeacherApp() {
  const [students, setStudents] = useState<Student[]>([]);
  const [studentId, setStudentId] = useState(""); // "" = class overview
  const [tab, setTab] = useState<Tab>("exercises");
  const [openExercise, setOpenExercise] = useState<string | null>(null);
  const [openLesson, setOpenLesson] = useState<string | null>(null);
  const [showStudents, setShowStudents] = useState(false);
  const [showWriting, setShowWriting] = useState(false);
  const [message, setMessage] = useState("");
  // Bumped after assigning to several students, so the overview reloads.
  const [overviewKey, setOverviewKey] = useState(0);

  const loadStudents = () => api<Student[]>("/students").then(setStudents);
  useEffect(() => {
    loadStudents();
  }, []);

  if (openExercise) return <ExerciseScreen exerciseId={openExercise} onBack={() => setOpenExercise(null)} />;
  if (openLesson) return <LessonScreen lessonId={openLesson} onBack={() => setOpenLesson(null)} />;

  const active = students.filter((s) => s.active);
  const student = active.find((s) => s.student_id === studentId);
  return (
    <main className="page wide">
      <div className="row spread">
        <h1>{student ? student.username : "Class overview"}</h1>
        <div className="row">
          <button onClick={() => { setShowWriting(!showWriting); setMessage(""); }}>
            {showWriting ? "Close writing form" : "Writing for several students"}
          </button>
          <button onClick={() => setShowStudents(!showStudents)}>{showStudents ? "Hide students" : "Manage students"}</button>
        </div>
      </div>
      {showStudents && <StudentsPanel students={students} onChange={loadStudents} />}
      {showWriting && (
        <WritingForStudents
          students={active}
          onDone={(done) => {
            setShowWriting(false);
            setMessage(done);
            setOverviewKey((k) => k + 1);
          }}
        />
      )}
      {message && <p className="notice">{message}</p>}
      <label>
        Show{" "}
        <select value={studentId} onChange={(e) => setStudentId(e.target.value)}>
          <option value="">Class overview</option>
          {active.map((s) => (
            <option key={s.student_id} value={s.student_id}>{s.username}</option>
          ))}
        </select>
      </label>

      {!student ? (
        <Overview key={overviewKey} onOpenExercise={setOpenExercise} onOpenStudent={setStudentId} />
      ) : (
        <>
          <div className="tabs" role="tablist">
            {TABS.map((t) => (
              <button key={t.tab} role="tab" aria-selected={tab === t.tab} className={tab === t.tab ? "active" : ""} onClick={() => setTab(t.tab)}>
                {t.label}
              </button>
            ))}
          </div>
          {tab === "exercises" && <StudentExercises key={studentId} studentId={studentId} onOpen={setOpenExercise} />}
          {tab === "lessons" && <StudentLessons key={studentId} studentId={studentId} onOpen={setOpenLesson} />}
          {tab === "profile" && <ProfilePanel key={studentId} studentId={studentId} />}
        </>
      )}
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
        <p className="muted">The AI also gets this student's recent error profile, your notes, and recent titles.</p>
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

function StudentLessons({ studentId, onOpen }: { studentId: string; onOpen: (id: string) => void }) {
  const [list, setList] = useState<LessonSummary[] | null>(null);
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api<LessonSummary[]>(`/lessons?student_id=${encodeURIComponent(studentId)}`).then(setList);
  }, [studentId]);

  async function generate(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const lesson = await api<TeacherLesson>("/lessons/generate", "POST", { student_id: studentId, description });
      onOpen(lesson.lesson_id);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  const status = (l: LessonSummary) => (l.status === "draft" ? "Draft" : l.read_at ? "Read" : "Assigned – not read yet");
  return (
    <>
      <form onSubmit={generate} className="stack panel">
        <label>
          New lesson – describe it
          <textarea
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="e.g. when to use 'the' with places, using examples from their writing"
            required
          />
        </label>
        <p className="muted">200–400 words: an explanation and a few examples with answers. The AI also gets the profile and your notes.</p>
        {error && <p className="error">{error}</p>}
        <button className="primary" disabled={busy}>{busy ? "Generating… (up to a minute)" : "Generate"}</button>
      </form>
      <table>
        <thead>
          <tr><th>Title</th><th>Status</th></tr>
        </thead>
        <tbody>
          {list?.map((l) => (
            <tr key={l.lesson_id} className="clickable" onClick={() => onOpen(l.lesson_id)}>
              <td>{l.title}</td>
              <td>{status(l)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {list?.length === 0 && <p>No lessons for this student yet.</p>}
    </>
  );
}
