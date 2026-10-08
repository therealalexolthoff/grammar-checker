// Sign-in through Identity Platform via the Firebase SDK. The browser
// config comes from the API's GET /config, so nothing is baked into the build.
import { initializeApp } from "firebase/app";
import {
  getAuth,
  getMultiFactorResolver,
  signInWithEmailAndPassword,
  signOut,
  TotpMultiFactorGenerator,
  type Auth,
  type MultiFactorError,
  type MultiFactorResolver,
} from "firebase/auth";

// Must match STUDENT_EMAIL_DOMAIN in api/app/identity.py.
const STUDENT_EMAIL_DOMAIN = "students.internal";

let auth: Auth | null = null;

export async function initAuth(): Promise<Auth> {
  if (!auth) {
    const config = await (await fetch("/config")).json();
    auth = getAuth(initializeApp(config.firebase));
  }
  return auth;
}

export function currentAuth(): Auth {
  if (!auth) throw new Error("auth not initialised");
  return auth;
}

export async function studentSignIn(username: string, password: string): Promise<void> {
  await signInWithEmailAndPassword(currentAuth(), `${username.trim()}@${STUDENT_EMAIL_DOMAIN}`, password);
}

// Step 1 of teacher sign-in. Returns the resolver for step 2 (the
// authenticator code). The teacher account always has TOTP enrolled, so
// a password-only success should never happen; if it does, the API
// refuses the token anyway (api/app/auth.py).
export async function teacherPasswordStep(email: string, password: string): Promise<MultiFactorResolver | null> {
  try {
    await signInWithEmailAndPassword(currentAuth(), email, password);
    return null;
  } catch (err) {
    if ((err as { code?: string }).code === "auth/multi-factor-auth-required") {
      return getMultiFactorResolver(currentAuth(), err as MultiFactorError);
    }
    throw err;
  }
}

export async function teacherCodeStep(resolver: MultiFactorResolver, code: string): Promise<void> {
  const hint = resolver.hints.find((h) => h.factorId === TotpMultiFactorGenerator.FACTOR_ID);
  if (!hint) throw new Error("No authenticator app is set up for this account.");
  const assertion = TotpMultiFactorGenerator.assertionForSignIn(hint.uid, code.trim());
  await resolver.resolveSignIn(assertion);
}

export function logOut(): Promise<void> {
  return signOut(currentAuth());
}
