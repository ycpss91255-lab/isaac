#!/usr/bin/env bash
# gpu_integration_job.sh -- the M2 GPU integration gate (PRD #4-int /
# isaac#132), run by main.yaml's core-gpu job through the org
# reusable workflow gpu-self-hosted.yml (which owns the runner, the fork-PR
# gate, the workspace reclaim and the checkout).
#
# Builds the devel-test image, then runs the headless integration suite inside
# that container, including the no-ROS suite under test/integration/. The gate
# requires at least one passing test, enforces the
# GPU collection floor and checks the hosted-unit plus GPU aggregate.
# Guard: test/bats/smoke/gpu_job_scripts_spec.bats.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"
# shellcheck source=gpu_job_lib.sh
. "${repo_root}/script/ci/gpu_job_lib.sh"

gpu_job_apply_and_pin_ws_path
gpu_job_build test
gpu_job_group "Check host UID and GID matrix with GPU import"
script/ci/uid_matrix.sh
gpu_job_endgroup
gpu_job_cache_dirs

# BASELINE_PROJECT: per-run-unique compose project so run.sh's EXIT-trap
# _app_cleanup (project-wide `compose down --remove-orphans`) can never reap a
# co-hosted manual stream stack on this shared GPU host (owv#55). base's
# self-test.yaml convention -- run_id + run_attempt: unique per re-run.
gpu_job_group "GPU integration pytest + aggregate gate (M2)"
export BASELINE_PROJECT="isaac-baseline-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}"
./test/assert_pytest_baseline.sh --gpu
gpu_job_endgroup

gpu_job_group "Official Isaac Sim startuptests"
./script/ci/official_startuptests.sh
gpu_job_endgroup
