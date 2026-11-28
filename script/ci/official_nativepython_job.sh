#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
# shellcheck source=gpu_job_lib.sh
. ./script/ci/gpu_job_lib.sh
gpu_job_apply_and_pin_ws_path
gpu_job_build headless
gpu_job_cache_dirs
export BASELINE_PROJECT="isaac-official-nativepython-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}"
bash ./script/ci/official_nativepython.sh
