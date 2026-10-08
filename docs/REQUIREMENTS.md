# ESL Grammar & Writing Tool: Requirements (v1)

Status: planning complete, ready for build. Items marked **[VERIFY]** must be confirmed by the coding agent before relying on them.

## 1. Purpose and context
A web app for one ESL teacher and their class (8 students now, must work for 30+). Non-commercial. The teacher generates personalized grammar/punctuation and writing exercises with an AI "harness" (Claude), students complete them on phones, the teacher reviews and releases AI-drafted feedback, and the app builds a per-student learner profile that personalizes future work and short teaching lessons.

Users:
- **Teacher**: exactly one, ever. Laptop-first UI.
- **Students**: adults, advanced level, English-only UI, phone-first UI. Identified only by an agreed pseudonym ("American name"), never real names.

## 2. Scope of v1
In scope: grammar and punctuation errors, including spelling and capitalization. Out of scope for v1: cohesion, structure, style, word choice, scores of any kind, groups/shared content, notifications, retakes, multiple teachers, native/PWA apps, multiple languages, student password change, self-signup.

## 3. Glossary
- **Harness**: separate backend service that calls Claude via Vertex AI. Has no database access.
- **Grammar exercise**: scored per item; items of type `fill_blank`, `reorder`, `short_answer`, mixable in one exercise.
- **Writing exercise**: one prompt, free-form response, evaluated with coded annotations, never marked or scored.
- **Writing lesson**: read-only teaching passage personalized to a student. Not an exercise.
- **Scrubbed text**: a teacher-edited copy of student text with personal data removed. The only student text ever sent to the harness (exception: handwriting photos for transcription).
- **Annotation**: a coded error span (see the 14-code taxonomy in HARNESS_SPEC.md).

## 4. Functional requirements

### 4.1 Accounts and access
- FR-1. Only the teacher creates student accounts: username (the agreed pseudonym) plus a teacher-set password. No email, no self-signup. Students cannot change their own password; only the teacher resets it.
- FR-2. The teacher account uses email + password + TOTP MFA (any RFC 6238 authenticator app, e.g. Google Authenticator, Authy). **Confirmed:** Identity Platform requires the teacher's email be verified before TOTP enrollment (anti-lockout measure); this only affects the teacher account, since students never enroll in MFA.
- FR-3. Students can access only their own released content. The teacher can view and manage all student data but cannot log in as a student.
- FR-4. The teacher can deactivate a student, and delete a student with all their data (including photos). Deletion requires typing the username to confirm and explains that backups expire within 7 days.
- FR-5. Overrides, reopens, deletions, and password resets are recorded in an audit log. **Extended (teacher decision):** student account creation and deactivation are audit-logged too, for the same reason - they're account-lifecycle actions in the same risk category.

### 4.2 Exercise generation (teacher)
- FR-6. Teacher picks a student and an exercise kind (grammar or writing), describes the exercise in free text, and presses Generate.
- FR-7. The app sends the harness the description plus an assembled context bundle (learner profile summary, teacher notes, recent exercise titles/concepts), keyed only by the opaque student ID.
- FR-8. The harness returns a structured draft (schemas in HARNESS_SPEC.md). Validation failures are never shown to the teacher.
- FR-9. Teacher can edit any item directly, regenerate with an optional note, or approve and assign. Drafts are editable; assigned exercises are frozen.
- FR-10. Every exercise is assigned to exactly one student. No due dates. The teacher tells students in class; the student sees an "assigned to me" list.
- FR-11. Fill-in-blank and reorder items are generated with accepted-answer lists, a one-line explanation, and a concept code. The teacher checks answers and concept codes at approval time (an explicit checklist on the approval screen).
- FR-12. Writing exercises: one prompt, optional min/max word counts, set by the teacher. Typed response is always available to the student; the teacher may additionally upload photos of handwritten work (see 4.5).

### 4.3 Doing an exercise (student, phone-first)
- FR-13. Student sees assigned work and opens it. Answers autosave (debounced) and resume after app switching or signal loss.
- FR-14. Reorder items use tap-to-place, not drag-and-drop. Large tap targets, plain-English instructions.
- FR-15. Student presses Submit with a confirmation step. After submitting, no edits. No retakes. Only the teacher can reopen a submission (audit-logged), returning it to in-progress.

### 4.4 Grading, scrubbing, evaluation, release
- FR-16. On submit, `fill_blank` and `reorder` items are graded deterministically against accepted answers. Comparison is strict on characters (case and punctuation count) after trimming and collapsing repeated whitespace. Students see nothing until release.
- FR-17. Grammar exercises with no `short_answer` items skip scrubbing and the harness and go straight to ready-to-release.
- FR-18. Otherwise, the teacher opens a laptop review screen showing the original text and an editable scrubbed copy. The original is never modified or sent anywhere. Editing the scrubbed text after evaluation invalidates the draft evaluation and requires re-running it.
- FR-19. "Send for evaluation" sends only the scrubbed text. The harness returns, grammar short answers: a mark (`correct`, `partial`, `incorrect`), annotations, one feedback sentence per item; writing exercises: annotations and one overall comment.
- FR-20. Teacher can accept, edit, or override every mark, annotation (add, remove, recode), and feedback text, and can regenerate with an optional note. All output is a draft until released.
- FR-21. Teacher releases results. Student view after release:
  - Grammar exercises: per-item correct/incorrect (short answers: correct/partial/incorrect), the correct answer shown for wrong fill/reorder items, the explanation/feedback sentence, and codes on annotated spans for short answers. No numeric score or percentage.
  - Writing exercises: their text with coded spans highlighted (code only; corrections and explanations stay teacher-only), plus the overall comment.
- FR-22. Students see their history of released work and lessons.

### 4.5 Handwritten writing responses (teacher-uploaded)
- FR-23. For a writing exercise, the teacher can upload multiple photos in page order for a student. Uploads are for writing exercises only. EXIF/metadata is stripped.
- FR-24. The harness transcribes photos verbatim (no correction, `[?]` for illegible words). Teacher sees a side-by-side screen (photos left, editable text right) and corrects the transcription. One response per exercise: the teacher designates which source (typed or transcription) is final.
- FR-25. The transcription then goes through the same scrub, evaluation, and release flow. Photos are visible to the teacher only, retained until the student is deleted, and are never shown to students. Students are told to write only their agreed first name on handwritten work.

### 4.6 Revision (writing exercises only)
- FR-26. After release, the student sees their text with coded spans and can tap a flagged span to edit only that span. One round; submit locks it. Grammar short answers are not revisable in v1.
- FR-27. Originals, annotations, and revisions are stored separately. The teacher reads revisions side by side with changed spans highlighted and marks each attempted span `fixed`, `unfixed`, or `changed_wrongly`. Revisions are not sent to the harness in v1.

### 4.7 Writing lessons
- FR-28. Teacher triggers a lesson by describing it and pressing Generate. The harness drafts 200 to 400 words: explanation plus a few practice examples. Examples are read-only (not interactive), with answers shown.
- FR-29. Same review loop: edit, regenerate with note, assign. Student reads it in-app and presses "Mark as read"; read status shows on the teacher overview.

### 4.8 Learner profile
- FR-30. Per student, computed by plain code (never by the harness), from teacher-approved data only: counts per error code from approved annotations and wrong deterministic items, plus revision outcomes per code, within a recency window (default last 5 submissions, configurable in settings).
- FR-31. Teacher can view the profile and keep private free-text notes per student. Notes are sent to the harness under the opaque ID. The notes field shows a warning: "Sent to the AI provider. No surnames or personal details."

### 4.9 Class overview (teacher)
- FR-32. One screen listing each student with pending work and pipeline stage (assigned, in progress, submitted, awaiting transcription review, awaiting scrub, evaluating, draft ready, ready to release, released, revision open, revision submitted) and unread lessons.

### 4.10 Operations
- FR-33. The app logs each harness call's tokens and cost, shows monthly spend, and enforces a hard monthly cap in the app (estimate before call, record after). At the cap, generation/evaluation pause with a clear message. Cap is a setting.
- FR-34. Harness failures or timeouts leave the job in a retryable error state; no work is lost.
- FR-35. Student-facing UI is English only, plain language, large text, no jargon in errors.
- FR-36. No in-app AI-use notice is required; the teacher informs students in class that their work is processed by an AI provider.

## 5. Non-functional requirements
- **Platform**: Google Cloud only. **Confirmed:** `us-east4`/`us-east5` do not support current Claude models as fixed regional endpoints on Vertex; use the **`us` multi-region endpoint** instead (keeps data in the US; 10% price premium over the `global` endpoint, which has no US-residency guarantee). Single production project, no staging.
- **Budget**: total under $20/month including cloud and Claude. App-enforced Claude cap; billing alerts at $10 and $15 as backstop. **Confirmed estimate:** ~$1-4/month at 8 students, ~$5-15/month at 30 students (Claude spend; GCP infra stays within free tiers at this scale) — see ARCHITECTURE.md section 11.
- **Privacy**: students identified only by pseudonym and opaque ID; usernames never leave the API; harness gets scrubbed text only (photo-to-transcribe is the one exception); **confirmed:** Google/Anthropic do not train models on Vertex customer data; logs never contain student text or images.
- **Security**: no direct client access to the database or storage; all authorization in the API; photos only via short-lived signed URLs to the teacher; strict output validation of all harness results; student text treated as untrusted data in prompts.
- **Reliability**: single-teacher classroom use; no HA requirement. Daily Firestore backups with 7-day retention.
- **Usability**: mobile-first student UI, laptop-first teacher UI, accessible contrast and text size.

## 6. Open items (decide during build)
1. ~~Exact Claude model names per operation and Vertex region availability~~ **Resolved:** `claude-sonnet-5` for all five harness operations, via the `us` multi-region Vertex endpoint. Upgrade `evaluate_exercise`/`evaluate_writing`/`transcribe` to `claude-opus-5` only if golden-set results (HARNESS_SPEC.md section 9) show Sonnet missing or miscoding errors.
2. Teacher-provided golden set of 8 to 10 annotated passages (see HARNESS_SPEC.md section 9) before the first real student session.
3. Whether to add a "word choice" code later (deliberately excluded now).
4. Vertex AI Model Garden access for Claude models must be requested per-model before Phase 1 GCP setup; approval has no fixed SLA (seen stuck pending in 2026 reports) — request early so it isn't a blocker. **Confirmed 2026-10-08: access and serving quota are separate gates** — granting Model Garden access does not itself grant a nonzero per-minute request quota, and there is no self-service way to raise it (`gcloud alpha services quota update` caps the override at 0 for this metric). A real quota-increase request via Console is required too — see infra/README.md.
