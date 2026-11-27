#!/usr/bin/env bash
# headless_smoke_job.sh -- the headless boot check (isaac#461), run by
# ci-headless-smoke.yaml through the org reusable workflow gpu-self-hosted.yml
# (which owns the runner, the fork-PR gate, the workspace reclaim and the
# checkout).
#
# Builds the headless stage, then runs script/ci/headless_smoke.sh (the stage
# stays running with RestartCount 0; tears down on every exit via its own
# trap). Guard: test/bats/smoke/gpu_job_scripts_spec.bats.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"
# shellcheck source=gpu_job_lib.sh
. "${repo_root}/script/ci/gpu_job_lib.sh"

gpu_job_apply_and_pin_ws_path
gpu_job_build headless
gpu_job_cache_dirs

# SMOKE_PROJECT: per-run-unique compose project, so the smoke's project-scoped
# teardown cannot reap a co-hosted manual headless stack.
gpu_job_group "Headless smoke (stage boots, stays running, RestartCount 0)"
SMOKE_PROJECT="isaac-hl-smoke-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}" \
  bash script/ci/headless_smoke.sh
gpu_job_endgroup
