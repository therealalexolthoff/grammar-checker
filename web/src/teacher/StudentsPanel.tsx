// Student accounts (FR-1, FR-4): add, reset password, deactivate, and
// delete (with type-the-name confirmation).
import { useState, type FormEvent } from "react";
import { api } from "../api";
import type { Student } from "../types";

export default function StudentsPanel({ students, onChange }: { students: Student[]; onChange: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [deleting, setDeleting] = useState<Student | null>(null);
  const [typed, setTyped] = useState("");

  async function run(action: () => Promise<unknown>, done: string) {
    setMessage("");
    try {
      await action();
      setMessage(done);
      onChange();
    } catch (err) {
      setMessage((err as Error).message);
    }
  }

  function add(e: FormEvent) {
    e.preventDefault();
    run(async () => {
      await api("/students", "POST", { username, password });
      setUsername("");
      setPassword("");
    }, `Added ${username}.`);
  }

  function resetPassword(s: Student) {
    const newPassword = window.prompt(`New password for ${s.username} (at least 8 characters):`);
    if (newPassword) run(() => api(`/students/${s.student_id}/reset-password`, "POST", { password: newPassword }), `Password reset for ${s.username}.`);
  }

  function deactivate(s: Student) {
    if (window.confirm(`Deactivate ${s.username}? They won't be able to sign in.`)) {
      run(() => api(`/students/${s.student_id}/deactivate`, "POST"), `${s.username} deactivated.`);
    }
  }

  function remove(s: Student) {
    run(async () => {
      await api(`/students/${s.student_id}`, "DELETE", { confirm_username: typed });
      setDeleting(null);
      setTyped("");
    }, `${s.username} and all their data were deleted.`);
  }

  return (
    <section className="panel">
      <h2>Students</h2>
      <table>
        <tbody>
          {students.map((s) => (
            <tr key={s.student_id}>
              <td>{s.username}</td>
              <td>{s.active ? "Active" : "Deactivated"}</td>
              <td className="actions">
                {s.active && <button onClick={() => resetPassword(s)}>Reset password</button>}
                {s.active && <button onClick={() => deactivate(s)}>Deactivate</button>}
                <button onClick={() => { setDeleting(s); setTyped(""); setMessage(""); }}>Delete…</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {deleting && (
        <div className="confirm stack">
          <p>
            <strong>Delete {deleting.username} for good?</strong> This deletes their account, all their exercises,
            answers, photos, lessons and your notes. It can't be undone. Copies in the daily backups expire within 7
            days.
          </p>
          <label>
            Type {deleting.username} to confirm
            <input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
          </label>
          <div className="row">
            <button onClick={() => remove(deleting)} disabled={typed !== deleting.username}>Delete permanently</button>
            <button onClick={() => setDeleting(null)}>Cancel</button>
          </div>
        </div>
      )}
      <form onSubmit={add} className="row">
        <input placeholder="Agreed name (e.g. Alex)" value={username} onChange={(e) => setUsername(e.target.value)} required />
        <input placeholder="Password (8+ characters)" value={password} onChange={(e) => setPassword(e.target.value)} minLength={8} required />
        <button>Add student</button>
      </form>
      {message && <p className="notice">{message}</p>}
    </section>
  );
}
