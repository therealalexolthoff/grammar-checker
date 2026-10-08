#!/usr/bin/env bash
# Starts the Firestore emulator for local development.
#
# One-time setup: gcloud components install cloud-firestore-emulator
# Usage: ./scripts/dev_firestore_emulator.sh
# Then, in the API's environment: export FIRESTORE_EMULATOR_HOST=localhost:8085
set -euo pipefail
gcloud emulators firestore start --host-port=localhost:8085
