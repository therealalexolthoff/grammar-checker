# Security review (Phase 8, 2026-10-08)

What was checked before the pilot, how, and what's left. Re-check after any change to auth, storage, logging or prompts.

## Checked and in place

| Area | How it's protected | How it was verified |
|---|---|---|
| No direct client access to Firestore | Deny-all rules (`infra/firestore.rules`, deployed with `infra/deploy_firestore_rules.py`). The API uses a service account, which rules don't apply to. | Before and after deploy: unauthenticated REST reads and writes to `students`/`submissions` return 403. |
| No direct client access to photos | Private bucket: uniform IAM access, public access prevention **enforced** (was "inherited" until this review), not linked to Firebase Storage. Only the API's service account can read it. | Unauthenticated listing returns 401. |
| Photos only via short-lived links | `GET /exercises/{id}/photos` returns V4 signed GET links that expire after 15 minutes: every page to the teacher; to a student, only the pages they uploaded to their own open exercise (none after submit, never the teacher's). Photos never appear in any other student response. | `api/tests/test_writing.py`. |
| Every endpoint checks who is calling | Each route depends on `get_current_user` / `require_teacher`; teacher tokens without TOTP are refused. | `api/tests/test_every_route_needs_login.py` walks every published endpoint and expects 401 with no login. |
| Students see only their own released work | Ownership checks return 404 for other students' ids; student views are serialized through models that have no field for teacher-only data. | `test_exercises.py`, `test_review.py`, `test_writing.py`, `test_profile_lessons.py`. |
| No student text in logs | Only `shared/logs.py` events are logged (ids, counts, error **types**). A middleware in both services turns any unexpected error into a plain 500 and logs only its type and path. **Fixed in this review:** before, an AI result that failed validation twice crashed the harness, and the server logged the full traceback, which can quote student text. | `api/tests/test_safe_logging.py`. |
| Prompt injection | Student text and teacher notes go inside `<data>` blocks that the system prompt says are never instructions. **Added in this review:** any `<data`/`</data` the text contains is defanged, so a student can't close the block early. Output is forced into a JSON schema and validated twice (harness and API), so injected text can at worst produce wrong annotations for the teacher to see. | `harness/tests/test_operations.py`; golden passage `g9-prompt-injection` against the live model. |
| Spend cap | Checked before every AI call (including the golden set runner); alert email at 75% and at the cap; Google billing alerts at $10 / $15. | `test_jobs_spend_settings.py`, `test_review.py`. |
| Alerts | Email to the teacher for failed AI calls, server errors, and spend (`infra/monitoring.sh`). | Policies created 2026-10-08. |
| Backups | Daily Firestore backups, 7-day retention. | `gcloud firestore backups schedules list`. |
| Student deletion | Deletes photos, exercises, submissions, lessons, job records, the login, then the student record; re-runnable if interrupted. The screen requires typing the username and explains backups expire within 7 days. | `api/tests/test_delete_student.py`. |

## Known limits (accepted, or for later)

- A signed photo link works for its full 15 minutes even if the teacher logs out.
- Gemini (the fallback while Claude's quota is pending) may log prompts for Google's abuse monitoring unless an exception is requested (docs/HARNESS_SPEC.md section 8). Prompts contain only scrubbed text and opaque ids.
- Scrubbing is manual: if the teacher leaves a name in the scrubbed copy, it reaches the AI provider.
- The audit log has no screen yet; it can be read in the Firestore console.
- Job records keep the error message of failed AI calls (which can quote scrubbed text) in Firestore; they're deleted with the student.
