# ESL Grammar & Writing Tool

Web app for one ESL teacher and their class. Read these before doing anything else:
- docs/REQUIREMENTS.md (what to build)
- docs/ARCHITECTURE.md (how it fits together)
- docs/HARNESS_SPEC.md (AI service contract and the 14-code taxonomy)
- docs/BUILD_PLAN.md (phases; start at Phase 0)

## Stack
Python 3.12 + FastAPI + Pydantic for the API and harness (two Cloud Run services), React frontend, Firestore, Cloud Storage, Identity Platform, Claude via Vertex AI. Google Cloud only, US East.

## Rules that must never be broken
- The harness has no database or storage access and is never given usernames or unscrubbed student text. Photos go to `transcribe` only.
- Clients never access Firestore or Storage directly; all authorization is server-side in the API.
- Original student text is never modified; only the teacher-edited scrubbed copy is sent to the harness.
- Never log student text or images.
- Validate all harness output in the API; never show invalid output to the teacher.
- Total cost must stay under $20/month; the Claude spend cap is enforced in the app.
- Scope is grammar, punctuation, spelling, capitalization only. No numeric scores anywhere.

## Working style
- The teacher reads Python, not TypeScript/React: keep backend code clear, typed, and commented where non-obvious.
- Work phase by phase per BUILD_PLAN.md. Complete Phase 0 verification and report findings before writing code.
- Ask the teacher before deviating from any decision in docs/. Items marked [VERIFY] must be confirmed, not assumed.
- Prefer the simplest approach that meets the requirements; do not add services or dependencies without asking.

## Keep code minimal
Before writing code, work down this list and stop at the first step that works:
1. Does this need to exist? If not, skip it.
2. Does the codebase already have it? Reuse it.
3. Does the standard library or the platform do it?
4. Is there an already-installed dependency that does it?
5. Otherwise write the smallest thing that works.

- Read the code a change touches before editing it.
- Prefer a short, readable solution over a clever one-liner; the teacher reads the Python.
- No speculative features, abstractions, or config for needs that don't exist yet.
- Ask before adding a new dependency or service.
- If the project already has a component, utility, or pattern for something, use it instead of the native or generic alternative.

**These rules never override the "Rules that must never be broken" section above.** Authorization checks, harness output validation, the original-versus-scrubbed separation, privacy-safe logging, and the spend cap are required code, not over-engineering. Never remove or skip them to make code shorter.
