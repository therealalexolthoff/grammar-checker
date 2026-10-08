// One student's learner profile (FR-30) and the teacher's private notes
// (FR-31). The profile is counted by the API (api/app/profile.py) from
// approved work only.
import { useEffect, useState } from "react";
import { api } from "../api";
import type { StudentProfile } from "../types";

export default function ProfilePanel({ studentId }: { studentId: string }) {
  const [data, setData] = useState<StudentProfile | null>(null);
  const [notes, setNotes] = useState("");
  const [dirty, setDirty] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    api<StudentProfile>(`/students/${studentId}/profile`).then((d) => {
      setData(d);
      setNotes(d.teacher_notes);
    });
  }, [studentId]);

  async function save() {
    setMessage("");
    try {
      await api(`/students/${studentId}/notes`, "PUT", { teacher_notes: notes });
      setDirty(false);
      setMessage("Notes saved.");
    } catch (err) {
      setMessage((err as Error).message);
    }
  }

  if (!data) return <p>Loading…</p>;
  const { profile } = data;
  return (
    <>
      <section className="panel">
        <h2>Recent errors</h2>
        <p className="muted">
          From the last {profile.submissions_counted} approved submission(s) (the window is {profile.window}). Counts
          approved annotations, wrong fill-in and word-order items, and revision outcomes you marked.
        </p>
        {profile.codes.length === 0 ? (
          <p>Nothing recorded yet.</p>
        ) : (
          <table>
            <thead>
              <tr><th>Code</th><th>Meaning</th><th>Errors</th><th>Fixed</th><th>Not fixed</th><th>Changed wrongly</th></tr>
            </thead>
            <tbody>
              {profile.codes.map((row) => (
                <tr key={row.code}>
                  <td><span className="code">{row.code}</span></td>
                  <td>{row.meaning}</td>
                  <td>{row.errors}</td>
                  <td>{row.fixed || ""}</td>
                  <td>{row.unfixed || ""}</td>
                  <td>{row.changed_wrongly || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel stack">
        <h2>Your notes</h2>
        <p className="notice">Sent to the AI provider. No surnames or personal details.</p>
        <p className="muted">Put the newest notes at the top: only the first 1,500 characters are sent.</p>
        <textarea
          rows={8}
          value={notes}
          onChange={(e) => {
            setNotes(e.target.value);
            setDirty(true);
            setMessage("");
          }}
        />
        <div className="row">
          <button className="primary" onClick={save} disabled={!dirty}>Save notes</button>
          {message && <span className="muted">{message}</span>}
        </div>
      </section>
    </>
  );
}
