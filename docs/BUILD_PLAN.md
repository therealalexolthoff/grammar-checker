# Build Plan (v1)

Read REQUIREMENTS.md, ARCHITECTURE.md, and HARNESS_SPEC.md first. The teacher reads Python but not TypeScript or React, so keep backend code clear, typed, commented where non-obvious, and keep logic in the backend. Ask the teacher before deviating from any decision in these docs.

## Phase 0: Verify assumptions (before coding)
Report findings to the teacher and update the docs:
1. Claude models available on Vertex AI in us-east4 / us-east5; pick region. Model IDs; pricing; structured output/tool-use support; prompt caching support; image input.
2. Vertex data terms: no training on customer data.
3. Identity Platform: TOTP MFA prerequisites; synthetic-email username approach; free-tier limits.
4. Firestore backup scheduling with 7-day retention; Cloud Storage signed URL approach on Cloud Run (service account signing).
5. Estimated monthly cost at 8 and 30 students.

## Phase 1: Foundations
- Repo layout: `api/`, `harness/`, `web/`, `shared/taxonomy` (code list used by both services), `docs/`.
- GCP project setup script/README (APIs, service accounts, Firestore, bucket, Identity Platform, Cloud Run).
- FastAPI skeleton for both services; Pydantic models for all schemas; Firestore emulator for dev; CI-style test command.
- Done when: both services deploy and a health check passes; the API can invoke the harness privately.

## Phase 2: Auth and accounts
- Teacher login with TOTP MFA. Teacher creates/deactivates students and resets passwords. Student login with username + password.
- Authorization middleware with role/ownership checks; audit log; tests proving a student cannot read another student's data or teacher-only fields.
- Done when: all auth paths work end-to-end on deployed services.

## Phase 3: Harness (mock first)
- Implement the five operations with mock mode and the shared validation (codes, span checks, schemas, permutations).
- Job records, spend log, settings doc, cost estimation and hard cap in the API.
- Then wire real Claude on Vertex per operation, with prompt templates (versioned), repair attempt, and prompt caching if supported.
- Done when: every operation passes validation tests in mock mode, and real-mode calls work for each with cost recorded.

## Phase 4: Grammar exercises, end to end
- Teacher: describe, generate, edit, regenerate with note, approval checklist (answers and concept codes), assign.
- Student (phone-first): list, open, autosave, tap-to-place reorder, confirm and submit, lock.
- Deterministic grading with normalization rule. Grammar exercises without short answers go straight to ready-to-release. Release flow and student results view (correct answers shown, no numeric scores).
- Done when: a full cycle works for fill-blank and reorder items on a real phone.

## Phase 5: Scrub and evaluation
- Teacher review screen (original read-only, scrubbed editable), send for evaluation, annotation display, accept/edit/override/recode/regenerate, invalidation on scrub edit, release.
- Student view with coded spans plus marks and feedback sentences for short answers.
- Done when: short-answer grammar exercises flow through to released student view.

## Phase 6: Writing exercises, photos, revision
- Writing exercise generation and typed responses; teacher photo upload (multi-page, EXIF stripped, private bucket, signed URLs); transcription with side-by-side correction screen; designate final source.
- Evaluation with coded spans; release; student span-level revision (one round, locked); teacher revision review and outcome marking.
- Done when: both typed and photo paths complete including revision.

## Phase 7: Lessons, profile, overview
- Learner profile computed from approved data and revision outcomes (recency window from settings); profile view; teacher notes with warning and inclusion in context bundles.
- Context assembler with unit tests; lesson generation, review, assign, student reading with Mark as read.
- Class overview screen with pipeline stages and unread lessons.

## Phase 8: Hardening
- Golden set runner and report (HARNESS_SPEC section 9); tune prompts with the teacher.
- Monitoring alerts, billing alerts ($10/$15), backups (7 days), student deletion flow (type username, deletes Firestore, Storage, auth user).
- Security review: no direct client access rules, signed URL expiry, no student text in logs, prompt injection tests (student text such as "ignore previous instructions").
- Done when: a pilot session with the real class is safe to run.

## Acceptance checklist (v1)
- [ ] Students see nothing before release; never see photos, corrections, explanations, or teacher notes.
- [ ] Only scrubbed text (and photos for transcription) reach the harness; no usernames ever.
- [ ] Original text preserved untouched; scrub edits invalidate evaluation.
- [ ] All harness output is validated; invalid output never reaches the teacher UI.
- [ ] Hard spend cap works and is visible; total cost under $20/month.
- [ ] Reopen, override, delete, and password reset are audit-logged.
- [ ] Deterministic grading is strict-character with whitespace normalization.
- [ ] Student UI works on a phone: autosave, tap-to-place, large targets.
- [ ] Teacher MFA (TOTP) enforced.
