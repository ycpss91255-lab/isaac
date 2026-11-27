#!/usr/bin/env bash
set -euo pipefail

cd /isaac-sim
rc=0
python3 run_tests.py --suite startuptests --output /tmp/r.xml || rc=$?

# Kit writes per-app logs under HOME. Copy them before Docker removes the container.
mkdir -p /artifacts/kit-logs || true
cp -r "${HOME}/.nvidia-omniverse/logs/." /artifacts/kit-logs/ || true
exit "${rc}"
