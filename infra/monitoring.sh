#!/usr/bin/env bash
# Monitoring alerts (docs/ARCHITECTURE.md section 8), emailed to the
# teacher. Each matches a structured log line the services write (see
# shared/logs.py) - ids and error types only, never student text.
#
#   1. An AI call failed (error, timeout, or output that didn't validate).
#   2. A server error: any 5xx response, or an unexpected error in either service.
#   3. AI spend passed 75% of the monthly cap, or reached it.
#
# At most one email per alert per hour. Safe to re-run: existing channels
# and policies (matched by display name) are left alone.
#
# Usage: ALERT_EMAIL=you@example.com ./infra/monitoring.sh
set -euo pipefail

PROJECT_ID="esl-grammar-tool"
: "${ALERT_EMAIL:?set ALERT_EMAIL}"
CHANNEL_NAME="Teacher email"

CHANNEL="$(gcloud alpha monitoring channels list --project="$PROJECT_ID" \
  --filter="displayName=\"$CHANNEL_NAME\"" --format="value(name)")"
if [[ -z "$CHANNEL" ]]; then
  CHANNEL="$(gcloud alpha monitoring channels create --project="$PROJECT_ID" \
    --display-name="$CHANNEL_NAME" --type=email \
    --channel-labels="email_address=$ALERT_EMAIL" --format="value(name)")"
fi

# create_alert "<name>" "<log filter>" "<what to do, shown in the email>"
create_alert() {
  local name="$1" filter="$2" doc="$3"
  if [[ -n "$(gcloud alpha monitoring policies list --project="$PROJECT_ID" \
      --filter="displayName=\"$name\"" --format="value(name)")" ]]; then
    echo "exists: $name"
    return
  fi
  local file
  file="$(mktemp)"
  python3 - "$name" "$filter" "$doc" "$CHANNEL" >"$file" <<'PY'
import json, sys
name, log_filter, doc, channel = sys.argv[1:]
print(json.dumps({
    "displayName": name,
    "combiner": "OR",
    "conditions": [{"displayName": name, "conditionMatchedLog": {"filter": log_filter}}],
    "alertStrategy": {"notificationRateLimit": {"period": "3600s"}, "autoClose": "86400s"},
    "notificationChannels": [channel],
    "documentation": {"content": doc, "mimeType": "text/markdown"},
}))
PY
  gcloud alpha monitoring policies create --project="$PROJECT_ID" --policy-from-file="$file" >/dev/null
  rm -f "$file"
  echo "created: $name"
}

create_alert "ESL: AI call failed" \
  'resource.type="cloud_run_revision" AND jsonPayload.event="harness_call_failed"' \
  "An AI call failed. The work is not lost: the teacher can retry it. If this repeats, check the jobs collection in Firestore for the error."

create_alert "ESL: server error" \
  'resource.type="cloud_run_revision" AND (httpRequest.status>=500 OR jsonPayload.event="unhandled_error")' \
  "The API or the harness returned a server error. Check Cloud Run logs for the service and path named in the log entry."

create_alert "ESL: AI spend" \
  'resource.type="cloud_run_revision" AND jsonPayload.event=("spend_threshold" OR "spend_cap_reached")' \
  "This month's AI spend has passed 75% of the cap, or reached it (generation and evaluation then pause until next month or until the cap setting is raised)."
