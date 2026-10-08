#!/usr/bin/env bash
# CI-style test command: installs dev deps into the current Python
# environment and runs every service's tests.
#
# Usage: ./scripts/test.sh
set -euo pipefail
cd "$(dirname "$0")/.."
pip install --quiet -r requirements-dev.txt
pytest
