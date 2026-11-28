#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
. script/ci/gpu_job_lib.sh

gpu_job_apply_and_pin_ws_path
gpu_job_build stream
gpu_job_cache_dirs
bash script/ci/stream_visual_e2e.sh
