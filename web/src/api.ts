// Every API call goes through here: adds the signed-in user's ID token and
// turns error responses into readable messages.
import { currentAuth } from "./firebase";

// An error the server sent back (as opposed to no connection at all,
// which fetch reports as a TypeError).
export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

export async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const user = currentAuth().currentUser;
  const headers: Record<string, string> = {};
  if (user) headers.Authorization = `Bearer ${await user.getIdToken()}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const response = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(errorText(data, response.status), response.status);
  return data as T;
}

function errorText(data: unknown, status: number): string {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  // FastAPI validation errors: a list of {loc, msg}.
  if (Array.isArray(detail)) {
    return detail.map((d) => `${(d.loc ?? []).slice(1).join(" > ")}: ${d.msg}`).join("\n");
  }
  return `Something went wrong (error ${status}). Please try again.`;
}
