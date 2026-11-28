#!/usr/bin/env bash
# Keep application vocabulary out of the downstream framework contract.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

status=0
grep -HinE 'forklift|coresam|pallet|pushback|openbase' \
  framework/isaac_devkit/*.py framework/pyproject.toml || status=$?
case "$status" in
  0) echo "Framework purity lint found application terms." >&2; exit 1 ;;
  1) echo "OK: framework purity (0 matches)" ;;
  *) exit "$status" ;;
esac
