# GCP project setup

One-time setup for a fresh GCP project. Run in this order.

## 1. Before running the script

- Install the [gcloud CLI](https://cloud.google.com/sdk/docs/install). No local Docker needed - images build remotely via Cloud Build (`infra/cloudbuild.yaml`).
- `gcloud auth login`
- Pick a globally-unique project ID and find your billing account ID: `gcloud billing accounts list`
- Open `setup_gcp.sh` and fill in `PROJECT_ID`, `BILLING_ACCOUNT_ID`, and `REGION` at the top.

## 2. Run the script

```
./infra/setup_gcp.sh
```

It creates the project, enables the required APIs, creates Firestore (native mode, with a 7-day daily backup schedule), a private Cloud Storage bucket, the two service accounts with the roles they need, builds and deploys both Cloud Run services, and wires the API to invoke the harness privately. It ends by curling the API's `/health` and `/health/harness` endpoints to confirm Phase 1's "done when" criteria.

**Do this first, in parallel with everything else** - it has no fixed approval time and can block later work if left until last:

- Request Vertex AI Model Garden access for the Claude model (Console: Vertex AI > Model Garden > find the Claude model > Request access). Seen stuck pending for an unpredictable time in 2026 reports.
- **Model Garden access and serving quota are two separate gates.** Even after access is granted, the actual per-minute request quota for the base model can still be 0, which fails real calls with `429 RESOURCE_EXHAUSTED` (confirmed 2026-10-08 against this project). There is no self-service bump - `gcloud alpha services quota update` caps the consumer override at 0 for this metric. Request the real increase via Console: IAM & Admin > Quotas & System Limits > filter by service "Vertex AI API", search "claude" or "anthropic" > select the `anthropic-claude-sonnet` row (`us_multi_region_online_prediction_requests_per_base_model`) > Edit Quotas > submit with a justification. No fixed SLA observed - start this immediately, same as the access request.

## 3. Manual steps (console only - no gcloud command covers these)

- **Identity Platform**: Console > Identity Platform > Get Started. Enable the Email/Password provider. Enable TOTP MFA (Settings > Multi-factor authentication). The teacher's account needs a verified email before they can enroll in MFA (see docs/REQUIREMENTS.md FR-2).
- **Billing alerts**: Console > Billing > Budgets & alerts. Set alerts at $10 and $15 (see docs/REQUIREMENTS.md section 5 - these are a backstop behind the app's own spend cap, not the primary control).

## Notes

- `setup_gcp.sh` is idempotent for most steps (safe to re-run), but re-creating the project or billing link will fail loudly if they already exist - that's expected, just skip ahead.
- Deleting resources this script created is not covered here; do that by hand and deliberately.
- After granting a Cloud Run IAM invoker binding, allow up to ~60 seconds for it to propagate before the private-invoke health check succeeds - a 403 right after granting the role isn't a misconfiguration, just propagation lag.

## Done (2026-10-08)

Ran against project `esl-grammar-tool`, region `us-east4`, billing account `<billing account id>`. Both services are deployed and verified:
- `esl-harness` (private): `roles/run.invoker` granted only to `esl-api-sa`.
- `esl-api` (public): `GET /health` and `GET /health/harness` both return 200.
- Identity Platform initialized, Email/Password + optional TOTP MFA enabled, teacher account created and MFA-enrolled - all via API, no console needed.
- Billing budget created ($20 cap, alerts at 50%/75%), scoped to this project only.
- Real Claude wiring (harness real mode) deployed and code-path verified end to end (prompt construction, Vertex auth, structured-output parsing, error handling) - **but the actual live call 429'd on Vertex quota**, not a code issue. See "Still outstanding" below.

Still outstanding:
- **Vertex AI serving quota for `anthropic-claude-sonnet` is 0** - confirmed via `gcloud alpha services quota list`, confirmed no self-service bump is possible. A real quota-increase request is submitted via Console (see above) and awaiting review as of 2026-10-08. The harness is deployed with `HARNESS_MOCK_MODE=false` already, ready to work the moment the quota clears - no redeploy needed, just retry.
