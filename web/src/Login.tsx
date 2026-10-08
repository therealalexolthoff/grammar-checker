import { useState, type FormEvent } from "react";
import type { MultiFactorResolver } from "firebase/auth";
import { studentSignIn, teacherCodeStep, teacherPasswordStep } from "./firebase";

export default function Login() {
  const [mode, setMode] = useState<"student" | "teacher">("student");
  return (
    <main className="page narrow">
      <h1>English Practice</h1>
      {mode === "student" ? <StudentLogin /> : <TeacherLogin />}
      <button className="link" onClick={() => setMode(mode === "student" ? "teacher" : "student")}>
        {mode === "student" ? "Teacher sign-in" : "Student sign-in"}
      </button>
    </main>
  );
}

function StudentLogin() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await studentSignIn(username, password);
    } catch {
      setError("That name or password didn't work. Check them and try again.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="stack">
      <label>
        Your name
        <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoCapitalize="words" required />
      </label>
      <label>
        Password
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
      </label>
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
    </form>
  );
}

function TeacherLogin() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [resolver, setResolver] = useState<MultiFactorResolver | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (resolver) {
        await teacherCodeStep(resolver, code);
      } else {
        setResolver(await teacherPasswordStep(email, password));
        setBusy(false);
      }
    } catch {
      setError(resolver ? "That code didn't work. Try the current one." : "Email or password is incorrect.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="stack">
      {!resolver ? (
        <>
          <label>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" required />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
          </label>
        </>
      ) : (
        <label>
          Authenticator code
          <input inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} required autoFocus />
        </label>
      )}
      {error && <p className="error">{error}</p>}
      <button className="primary" disabled={busy}>{busy ? "Checking…" : resolver ? "Verify" : "Next"}</button>
    </form>
  );
}
