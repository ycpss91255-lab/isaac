#!/usr/bin/env bats
# bats file_tags=core
#
# Behavioral guard for the self-hosted GPU job scripts:
#   script/ci/gpu_integration_job.sh  (main.yaml gpu-integration)
#   script/ci/stream_smoke_job.sh     (ci-stream-smoke.yaml stream-smoke)
#
# Both jobs now run through the org reusable workflow
# ycpss91255-lab/.github/.github/workflows/gpu-self-hosted.yml, which owns
# the runner, the fork-PR gate, the pre-checkout workspace reclaim and the
# checkout, and then runs ONE repo script. These scripts hold the step logic
# the two workflows used to carry inline, so this spec pins what those steps
# did: the order, the WS_PATH pin, which env reaches which command, the
# writable cache dirs, and that a failing step fails the job.
#
# Hermetic: the real job scripts run from a fake repo root against stub
# setup.sh / build.sh / assert_pytest_baseline.sh / stream_smoke.sh that
# record what they receive. No docker, no GPU.
#
# Baked into /smoke_test/ next to the job scripts by the devel-test stage.

bats_require_minimum_version 1.5.0

setup() {
  FAKE="$(mktemp -d)"
  mkdir -p "${FAKE}/script/ci" "${FAKE}/test"
  for f in gpu_job_lib.sh gpu_integration_job.sh stream_smoke_job.sh; do
    cp "${BATS_TEST_DIRNAME}/${f}" "${FAKE}/script/ci/${f}"
  done
  chmod +x "${FAKE}/script/ci/"*.sh

  export CALLS="${FAKE}/calls.log"
  export GITHUB_WORKSPACE="${FAKE}"
  export HOME="${BATS_TEST_TMPDIR}/home"
  export ISAAC_CI_CACHE_ROOT="${BATS_TEST_TMPDIR}/runner-cache"
  mkdir -p "${HOME}"
  unset ISAAC_CI_CACHE_KEY
  export GITHUB_RUN_ID=1234
  export GITHUB_RUN_ATTEMPT=2
  unset ISAAC_ALLOW_SHARED_IDENTITY BASELINE_PROJECT GPU_ROS_DOMAIN_ID \
    SMOKE_PROJECT SMOKE_REAP_PROJECT_PREFIX

  # setup.sh apply writes a cache with the mis-detected WS_PATH the job must
  # overwrite (base detect_ws_path returns _work/<repo>, base#586).
  cat > "${FAKE}/script/setup.sh" <<'STUB'
#!/usr/bin/env bash
echo "setup $*" >> "${CALLS}"
printf 'IMAGE_NAME=isaac\nWS_PATH=/wrong/parent\nPROJECT_NAME=alice-isaac\n' \
  > .env.generated
STUB

  cat > "${FAKE}/script/build.sh" <<'STUB'
#!/usr/bin/env bash
echo "build $* shared=${ISAAC_ALLOW_SHARED_IDENTITY:-unset}" >> "${CALLS}"
exit "${BUILD_RC:-0}"
STUB

  cat > "${FAKE}/test/assert_pytest_baseline.sh" <<'STUB'
#!/usr/bin/env bash
{
  echo "baseline $* project=${BASELINE_PROJECT:-unset} domain=${GPU_ROS_DOMAIN_ID:-unset} shared=${ISAAC_ALLOW_SHARED_IDENTITY:-unset}"
  grep '^WS_PATH=' .env.generated
  [ -w isaac-sim/kit/cache ] && [ -w isaac-sim/nvidia/computecache ] \
    && [ -w isaac-sim/documents ] && echo "caches=writable"
} >> "${CALLS}"
STUB

  cat > "${FAKE}/script/ci/stream_smoke.sh" <<'STUB'
#!/usr/bin/env bash
{
  echo "smoke project=${SMOKE_PROJECT:-unset} reap=${SMOKE_REAP_PROJECT_PREFIX:-unset} shared=${ISAAC_ALLOW_SHARED_IDENTITY:-unset}"
  grep '^WS_PATH=' .env.generated
  [ -w isaac-sim/kit/logs ] && echo "caches=writable"
} >> "${CALLS}"
if [ -n "${SMOKE_RC:-}" ]; then
  echo "kit-log-line-from-the-failed-run" > isaac-sim/kit/logs/stream-smoke.log
  exit "${SMOKE_RC}"
fi
STUB
  # uid_matrix_spec exercises the matrix and its failure status separately.
  printf '#!/bin/sh\nexit 0\n' > "${FAKE}/script/ci/uid_matrix.sh"
  chmod +x "${FAKE}/script/setup.sh" "${FAKE}/script/build.sh" \
    "${FAKE}/script/ci/uid_matrix.sh" \
    "${FAKE}/test/assert_pytest_baseline.sh" "${FAKE}/script/ci/stream_smoke.sh"
}

teardown() {
  rm -rf "${FAKE}"
}

@test "gpu integration job: apply, pin WS_PATH, build test, caches, gpu baseline -- in order" {
  run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  run cat "${CALLS}"
  [ "${lines[0]}" = "setup apply" ]
  [ "${lines[1]}" = "build -t test shared=1" ]
  [ "${lines[2]}" = "baseline --gpu project=isaac-baseline-1234-2 domain=47 shared=unset" ]
  [ "${lines[3]}" = "WS_PATH=${FAKE}" ]
  [ "${lines[4]}" = "caches=writable" ]
  [ "${#lines[@]}" -eq 5 ]
}

@test "gpu integration job: works from any cwd (resolves the repo root itself)" {
  cd /
  run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  grep -qx "setup apply" "${CALLS}"
}

@test "gpu integration job: replaces existing cache dirs with links keyed by the BASE_IMAGE tag" {
  echo 'ARG BASE_IMAGE="nvcr.io/nvidia/isaac-sim:9.9.9"' > "${FAKE}/Dockerfile"
  local sim="${FAKE}/isaac-sim" cache="${ISAAC_CI_CACHE_ROOT}/9.9.9"
  mkdir -p "${sim}/kit/cache" "${sim}/nvidia/computecache"
  touch "${sim}/kit/cache/old" "${sim}/nvidia/computecache/old"

  run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  [ -L "${sim}/kit/cache" ]
  [ -L "${sim}/nvidia/computecache" ]
  [ "${sim}/kit/cache" -ef "${cache}/kit-cache" ]
  [ "${sim}/nvidia/computecache" -ef "${cache}/computecache" ]
  [ ! -e "${sim}/kit/cache/old" ]
  [ ! -e "${sim}/nvidia/computecache/old" ]
}

@test "gpu integration job: ISAAC_CI_CACHE_KEY overrides the BASE_IMAGE tag" {
  echo 'ARG BASE_IMAGE="nvcr.io/nvidia/isaac-sim:9.9.9"' > "${FAKE}/Dockerfile"
  export ISAAC_CI_CACHE_KEY="Runner_2.test-cache"
  local cache="${ISAAC_CI_CACHE_ROOT}/${ISAAC_CI_CACHE_KEY}"

  run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  [ "${FAKE}/isaac-sim/kit/cache" -ef "${cache}/kit-cache" ]
  [ "${FAKE}/isaac-sim/nvidia/computecache" -ef "${cache}/computecache" ]
}

@test "gpu integration job: both caches survive workspace cleanup between runs" {
  unset ISAAC_CI_CACHE_ROOT
  local sim="${FAKE}/isaac-sim" cache="${HOME}/isaac-ci-cache/default"

  run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  [ -d "${cache}/kit-cache" ]
  [ -d "${cache}/computecache" ]
  echo shader > "${cache}/kit-cache/marker"
  echo compute > "${cache}/computecache/marker"
  touch "${sim}/kit/data/previous-run"
  rm -rf "${sim}"

  run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  grep -qx shader "${sim}/kit/cache/marker"
  grep -qx compute "${sim}/nvidia/computecache/marker"
  [ -d "${sim}/kit/data" ]
  [ ! -L "${sim}/kit/data" ]
  [ ! -e "${sim}/kit/data/previous-run" ]
}

@test "gpu integration job: baseline sees writable mounts and state dirs stay in the workspace" {
  run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  grep -qx 'caches=writable' "${CALLS}"

  local state target
  for state in kit/data kit/logs ov/cache ov/data ov/logs pip nvidia/glcache documents; do
    local path="${FAKE}/isaac-sim/${state}"
    [ -d "${path}" ]
    [ ! -L "${path}" ]
  done
  for target in kit-cache computecache; do
    local path="${ISAAC_CI_CACHE_ROOT}/default/${target}"
    [ -d "${path}" ]
    [[ "$(stat -c '%a' "${path}")" == *777 ]]
  done
}

@test "gpu integration job: a failed build fails the job before the GPU suite" {
  BUILD_RC=3 run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -ne 0 ]
  run grep -c '^baseline' "${CALLS}"
  [ "${output}" = "0" ]
}

@test "stream smoke job: apply, pin WS_PATH, build stream, caches, smoke -- in order" {
  run bash "${FAKE}/script/ci/stream_smoke_job.sh"
  [ "${status}" -eq 0 ]
  run cat "${CALLS}"
  [ "${lines[0]}" = "setup apply" ]
  [ "${lines[1]}" = "build -t stream shared=1" ]
  [ "${lines[2]}" = "smoke project=isaac-smoke-1234-2 reap=isaac-smoke- shared=unset" ]
  [ "${lines[3]}" = "WS_PATH=${FAKE}" ]
  [ "${lines[4]}" = "caches=writable" ]
  [ "${#lines[@]}" -eq 5 ]
}

@test "stream smoke job: a failed smoke fails the job and prints the full kit log" {
  SMOKE_RC=1 run bash "${FAKE}/script/ci/stream_smoke_job.sh"
  [ "${status}" -eq 1 ]
  [[ "${output}" == *"kit-log-line-from-the-failed-run"* ]]
}

@test "gpu_job_cache_dirs makes the workspace world-writable (rootless Docker)" {
  # gpu_job_cache_dirs is sourced from gpu_job_lib.sh.  After it runs, every
  # file and directory under GITHUB_WORKSPACE must be accessible by any uid
  # (chmod -R a+rwX), so a container's non-root user can write to the mounted
  # workspace on a rootless Docker daemon where the runner uid maps to a
  # subuid.  On rootful daemons the chmod is harmless.
  #
  # Create a file owned by the current user with restricted permissions to
  # prove the chmod widens them.
  mkdir -p "${FAKE}/isaac-sim/kit/cache"
  chmod 700 "${FAKE}/isaac-sim/kit/cache"
  touch "${FAKE}/some-repo-file"
  chmod 600 "${FAKE}/some-repo-file"

  run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]

  # Directories must have the 'other' execute+read+write bits set.
  local dir_perms
  dir_perms=$(stat -c '%a' "${FAKE}/isaac-sim/kit/cache")
  [[ "${dir_perms}" == *7 ]]

  # Regular files must have the 'other' read+write bits set (X does not set
  # execute on regular files that lacked it).
  local file_perms
  file_perms=$(stat -c '%a' "${FAKE}/some-repo-file")
  [[ "${file_perms}" == *6 ]]
}

@test "stream smoke job: a failed smoke with no kit log still fails with the smoke's status" {
  cat > "${FAKE}/script/ci/stream_smoke.sh" <<'STUB'
#!/usr/bin/env bash
exit 4
STUB
  run bash "${FAKE}/script/ci/stream_smoke_job.sh"
  [ "${status}" -eq 4 ]
}
