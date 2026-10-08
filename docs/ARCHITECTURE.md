# Architecture (v1)

## 1. Overview
```
Student phone / Teacher laptop
        |  HTTPS (React SPA, session via Identity Platform ID token)
        v
  API service (Cloud Run, Python/FastAPI)  ----> Firestore (all data)
        |                |                 \--> Cloud Storage (private; handwriting photos)
        |                \--> Identity Platform (auth)
        v  (private, service-account-only invoke)
  Harness service (Cloud Run, Python) ----> Claude on Vertex AI
```
All business logic and authorization live in the API. The harness has **no** database or storage access; it receives a payload and returns validated JSON.

## 2. Stack
- Frontend: React SPA (responsive; student screens phone-first, teacher screens laptop-first). No native app, no PWA.
- API and harness: Python 3.12, FastAPI, Pydantic v2. Two separate Cloud Run services.
- Database: Firestore (native mode). Auth: Google Identity Platform. Files: Cloud Storage. Model access: Vertex AI (Claude; Gemini 3.8 Flash as automatic fallback when Claude is unavailable — see HARNESS_SPEC section 8), authenticated by service account (no API keys).
- Region: **confirmed** — `us-east4`/`us-east5` do not support current Claude models as fixed regional Vertex endpoints (only `us-east5` serves Sonnet 4.6 and earlier, now stale). Use the **`us` multi-region endpoint** instead: keeps data in the US, works with current models, 10% price premium over the region-free `global` endpoint.
- Frontend hosting: serve the built SPA from the API service (simplest), or Firebase Hosting / Cloud Storage; agent picks the simplest that works.

## 3. Key decisions
1. **Clients never touch Firestore or Storage directly.** Firestore/Storage rules deny all client access. Autosave is a debounced API call. No realtime features.
2. **Harness is a separate private service** with five operations and no data access. Swappable model/provider.
3. **Learner profile is computed by plain code** from approved data; the harness only reads a compact summary.
4. **Harness calls are synchronous** with a persisted job record (no queue). Failure leaves a retryable job. Revisit Cloud Tasks only if latency becomes a problem.
5. **Identity Platform kept** (not custom auth): hardened password handling, brute-force protection, built-in TOTP. Students use a synthetic email `<username>@students.internal` created and hidden inside one function (confirmed: Identity Platform does not validate the domain, only that the string is a syntactically unique email); the teacher uses a real, **verified** email + TOTP — confirmed verified email is a hard prerequisite for MFA enrollment, which only applies to the teacher since students never enroll in MFA.
6. **Original vs scrubbed text are separate fields.** Only scrubbed text leaves the API.
7. **Strict validation** of all harness output; the API never trusts the harness.
8. **Hard spend cap in the app** (Google budgets only alert).
9. **Opaque IDs**: each student has a random ID (not derived from username). Usernames and notes-with-names never go to the harness.

## 4. Data model (Firestore)
| Collection | Contents |
|---|---|
| `students` | id (opaque), username, auth uid, active, teacher_notes, created_at. **Build decision (Phase 7):** the profile is not stored; it is computed on demand from approved submissions (`api/app/profile.py`), so it can never drift from its data. teacher_notes is one free-text field; the notes screen asks for newest notes at the top, and the context assembler keeps the first 1,500 characters. |
| `exercises` | id, student_id, kind (`grammar`/`writing`), status (`draft`/`assigned`), title, items or prompt, teacher_request, generation_history (versions, notes), settings (min/max words) |
| `submissions` | id, exercise_id, student_id, state, original_answers, scrubbed_answers, final_source (`typed`/`photo`), transcription, photos[] (path, page order, uploaded_at), marks, annotations (with computed offsets), feedback, release_at, revision {edits, submitted_at, outcomes}, evaluation_valid flag |
| `lessons` | id, student_id, status (`draft`/`assigned`), request, passage, examples, read_at |
| `jobs` | id, operation, prompt_version, model, context_version, input_hash, status, latency, retries, tokens_in/out, cost, validation_outcome (`passed`/`repaired`/`rejected`), teacher_action (`accepted`/`edited`/`overridden`/`regenerated`), error |
| `spend` | month key, totals |
| `settings` | single doc: monthly_cap, per-operation model names, alert thresholds, profile_window (default 5), token budgets |
| `audit` | actor, action, target, timestamp |

Subcollections are fine where natural (e.g. submissions under students) if it simplifies queries; the agent decides.

## 5. Submission pipeline
```
assigned -> in_progress -> submitted
  grammar, no short answers:      submitted -> ready_to_release
  has photo as final source:      submitted -> transcribing -> transcript_review -> scrub_review
  otherwise:                      submitted -> scrub_review
scrub_review -> evaluating -> draft_ready -> ready_to_release -> released
writing only: released -> revision_open -> revision_submitted
```
- Reopen (teacher only): back to `in_progress`, audit-logged.
- Editing scrubbed text after `draft_ready` sets `evaluation_valid=false` and returns to `scrub_review`.
- Errors in any harness step: job status `error`, submission stays in its prior state, retry available.

## 6. Authorization
- Student: may read/write only their own assigned, unsubmitted answers; read own released results and lessons; mark lessons read; submit revision when open.
- Teacher: everything, except impersonation. Photos only via signed URLs generated for the teacher.
- Every endpoint checks role and ownership server-side. Student endpoints never return teacher-only fields (corrections, explanations on annotations, notes, original-vs-scrubbed, unreleased drafts).

## 7. Context assembler (API, deterministic, unit-tested)
Builds each harness payload within a fixed token budget:
- Profile summary: top N codes by recent count (window from settings), plus revision outcomes.
- Teacher notes (length-capped, newest first).
- Recent exercise titles and concepts (to avoid repeats).
- Up to ~5 scrubbed, approved excerpts chosen by target error code (generation and lessons only).
- Never included: username, original unscrubbed text, other students' data.

## 8. Cost control and observability
- Per call: estimate cost before, enforce cap, record actual after. Show monthly spend to the teacher.
- Job records capture operation, prompt version, model, latency, retries, tokens, cost, validation outcome, and teacher action (accepted/edited/overridden/regenerated). Override rate per operation and prompt version is the main quality signal.
- Structured JSON logs to Cloud Logging with IDs and counts only (never student text/images). Cloud Monitoring alerts: harness error rate, spend thresholds. Billing alerts at $10/$15.
- No third-party LLM tracing tools (they would receive student text).
- Prompt caching for the static prompt prefix — confirmed supported on Vertex for Claude models (in-memory cache, 24-hour TTL).

## 9. Backups and deletion
Firestore scheduled backups with 7-day retention. Student deletion removes Firestore documents, Storage photos, and the Identity Platform user; deleted data may persist in backups up to 7 days, stated on the confirmation screen.

## 10. Environments and deployment
Single production GCP project. Local development uses the Firestore emulator and the harness in mock mode. Deploy with `gcloud run deploy` scripts (or a small Cloud Build config); infrastructure setup documented in a script/README so it is repeatable.

Confirmed setup requirements for the project setup script:
- Request Vertex AI Model Garden access for the Claude model early (no fixed approval SLA observed) — do this before anything else depends on it.
- Grant the API service's Cloud Run runtime service account the `roles/iam.serviceAccountTokenCreator` role **on itself** (self-impersonation) — required for signed URL generation via IAM `signBlob`; easy to miss since it's self-referential rather than a grant on another resource.
- Firestore native backup schedules: `gcloud firestore backups schedules create --database=DATABASE_ID --recurrence=daily --retention=7d` (confirmed supported, up to 14 weeks max retention).

## 11. Estimated monthly cost (confirmed)
Cloud Run, Firestore, Identity Platform, Storage: within free tiers at this scale (Identity Platform free up to 50k MAU; TOTP MFA has no per-verification cost). Claude usage (model: `claude-sonnet-5` for all operations, `us` multi-region endpoint), modeling ~1 exercise generated + ~0.7 evaluations + ~0.5 lessons + ~0.25 photo transcriptions per student per week:
- 8 students: ~$1-4/month
- 30 students: ~$5-15/month (padded for regenerations/retries)

Both stay under the $20 total cap with margin; the app's hard cap plus $10/$15 billing alerts remain the safety net for heavier-than-modeled use. Re-check this estimate once real usage data exists.
