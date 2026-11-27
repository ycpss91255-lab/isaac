#!/usr/bin/env bash
# gpu_integration_job.sh -- the M2 GPU integration gate (PRD #4-int /
# isaac#132), run by main.yaml's gpu-integration job through the org
# reusable workflow gpu-self-hosted.yml (which owns the runner, the fork-PR
# gate, the workspace reclaim and the checkout).
#
# Builds the devel-test image (warm-cached on the runner), then boots
# headless Isaac and runs both suites under test/integration/. assert_pytest_baseline.sh
# --gpu enforces: the GPU suite actually RAN (passed > 0 -- a skipped GPU job
# is NOT green), collected >= GPU_INTEGRATION_BASELINE (ratchet), and the
# cross-runner aggregate (HOSTED_UNIT + GPU_INTEGRATION) >= AGGREGATE_TARGET.
# Guard: test/bats/smoke/gpu_job_scripts_spec.bats.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"
# shellcheck source=gpu_job_lib.sh
. "${repo_root}/script/ci/gpu_job_lib.sh"

gpu_job_apply_and_pin_ws_path
gpu_job_build test
gpu_job_cache_dirs

# BASELINE_PROJECT: per-run-unique compose project so run.sh's EXIT-trap
# _app_cleanup (project-wide `compose down --remove-orphans`) can never reap a
# co-hosted manual stream stack on this shared GPU host (owv#55). base's
# self-test.yaml convention -- run_id + run_attempt: unique per re-run.
gpu_job_group "GPU integration pytest + aggregate gate (M2)"
BASELINE_PROJECT="isaac-baseline-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}" \
  GPU_ROS_DOMAIN_ID="$(( (GITHUB_RUN_ID % 99) + 1 ))" \
  ./test/assert_pytest_baseline.sh --gpu
gpu_job_endgroup
