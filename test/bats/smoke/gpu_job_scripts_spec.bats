#!/usr/bin/env bats
# bats file_tags=core
#
# Behavioral guard for the self-hosted GPU job scripts:
#   script/ci/gpu_integration_job.sh  (main.yaml gpu-integration)
#   script/ci/stream_smoke_job.sh     (ci-stream-smoke.yaml stream-smoke)
#   script/ci/stream_visual_e2e_job.sh (visual stream acceptance)
#
# These jobs run through the org reusable workflow
# ycpss91255-lab/.github/.github/workflows/gpu-self-hosted.yml, which owns
# the runner, the fork-PR gate, the pre-checkout workspace reclaim and the
# checkout, and then runs ONE repo script. These scripts hold the step logic
# the workflows used to carry inline, so this spec pins what those steps
# did: the order, the WS_PATH pin, which env reaches which command, the
# writable cache dirs, and that a failing step fails the job.
#
# Hermetic: the real job scripts run from a fake repo root against stub
# setup.sh / build.sh / assert_pytest_baseline.sh / stream_smoke.sh / docker that
# record what they receive. No docker, no GPU.
#
# Baked into /smoke_test/ next to the job scripts by the devel-test stage.

bats_require_minimum_version 1.5.0

setup() {
  FAKE="$(mktemp -d)"
  local scripts="${BATS_TEST_DIRNAME}/../../../script/ci" f
  # devel-test includes the complete CI script directory under /lint.
  if [[ ! -f "${scripts}/gpu_integration_job.sh" ]]; then
    scripts=/lint/ci
  fi
  mkdir -p "${FAKE}/script/ci" "${FAKE}/test" "${FAKE}/bin"
  for f in gpu_job_lib.sh gpu_integration_job.sh stream_smoke_job.sh stream_visual_e2e_job.sh; do
    cp "${scripts}/${f}" "${FAKE}/script/ci/${f}"
  done
  cp "${scripts}/official_startuptests.sh" "${FAKE}/script/ci/"
  if [ -f "${scripts}/startuptests_in_container.sh" ]; then
    cp "${scripts}/startuptests_in_container.sh" "${FAKE}/script/ci/"
  fi
  cp "${BATS_TEST_DIRNAME}/startuptests_docker_stub.py" "${FAKE}/bin/docker"
  chmod +x "${FAKE}/script/ci/"*.sh "${FAKE}/bin/docker"
  export PATH="${FAKE}/bin:${PATH}"
  unset DOCKER_HUB_USER STARTUP_RC BASELINE_RC
  unset STARTUP_JUNIT_FAILURES STARTUP_JUNIT_ERRORS STARTUP_JUNIT_WRAPPED STARTUP_JUNIT_TRUNCATED

  export CALLS="${FAKE}/calls.log"
  export GITHUB_WORKSPACE="${FAKE}"
  export HOME="${BATS_TEST_TMPDIR}/home"
  export ISAAC_CI_CACHE_ROOT="${BATS_TEST_TMPDIR}/runner-cache"
  mkdir -p "${HOME}"
  unset ISAAC_CI_CACHE_KEY ISAAC_CI_COLD_CACHE GITHUB_REF_TYPE GITHUB_REF
  unset GITHUB_EVENT_NAME GITHUB_EVENT_PATH
  cat > "${FAKE}/bin/nvidia-smi" <<'STUB'
#!/usr/bin/env bash
[[ "$#" == 2 && "$1" == --query-gpu=driver_version && "$2" == --format=csv,noheader ]] || exit 2
printf '%s\n' 550.54.15 560.35.03
STUB
  chmod +x "${FAKE}/bin/nvidia-smi"
  export GITHUB_RUN_ID=1234
  export GITHUB_RUN_ATTEMPT=2
  unset ISAAC_ALLOW_SHARED_IDENTITY BASELINE_PROJECT \
    SMOKE_PROJECT SMOKE_REAP_PROJECT_PREFIX

  # setup.sh apply writes a cache with the mis-detected WS_PATH the job must
  # overwrite (base detect_ws_path returns _work/<repo>, base#586).
  cat > "${FAKE}/script/setup.sh" <<'STUB'
#!/usr/bin/env bash
echo "setup $*" >> "${CALLS}"
printf 'IMAGE_NAME=isaac\nDOCKER_HUB_USER=alice\nWS_PATH=/wrong/parent\nPROJECT_NAME=alice-isaac\n' \
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
  echo "baseline $* project=${BASELINE_PROJECT:-unset} shared=${ISAAC_ALLOW_SHARED_IDENTITY:-unset}"
  grep '^WS_PATH=' .env.generated
  [ -w isaac-sim/kit/cache ] && [ -w isaac-sim/nvidia/computecache ] \
    && [ -w isaac-sim/documents ] && echo "caches=writable"
} >> "${CALLS}"
exit "${BASELINE_RC:-0}"
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
  # The hosted test_official_pythontests.py exercises the bucket runner.
  cat > "${FAKE}/script/ci/official_pythontests.sh" <<'STUB'
#!/usr/bin/env bash
echo "pythontests" >> "${CALLS}"
STUB
  chmod +x "${FAKE}/script/ci/official_pythontests.sh"
  # uid_matrix_spec exercises the matrix and its failure status separately.
  printf '#!/bin/sh\nexit 0\n' > "${FAKE}/script/ci/uid_matrix.sh"
  chmod +x "${FAKE}/script/setup.sh" "${FAKE}/script/build.sh" \
    "${FAKE}/script/ci/uid_matrix.sh" \
    "${FAKE}/test/assert_pytest_baseline.sh" "${FAKE}/script/ci/stream_smoke.sh"
}

teardown() {
  rm -rf "${FAKE}"
}

# Run in place of a GPU workload. Snapshot the bind mounts while the job owns
# them and write through both links. Once the job exits, the run may be gone.
install_cache_probe() {
  local workload="${FAKE}/${1:-test/assert_pytest_baseline.sh}"
  cat > "${workload}" <<'STUB'
#!/usr/bin/env bash
set -eu
mkdir -p observed
probe_mount() {
  local mount="$1" name="$2" target
  [[ -L "${mount}" ]]
  target="$(realpath -e "${mount}")"
  echo "${target}" > "observed/${name}.target"
  stat -c '%d:%i' "$(dirname "${target}")" > "observed/${name}.parent-inode"
  cp -a "${mount}/." "observed/${name}"
  rm -f "${mount}/obsolete"
  echo "${GITHUB_RUN_ID}" > "${mount}/writer"
}
probe_mount isaac-sim/kit/cache kit-cache
probe_mount isaac-sim/nvidia/computecache computecache
if [[ -f after-cache-write.sh ]]; then
  # shellcheck disable=SC1091
  source ./after-cache-write.sh
fi
STUB
  chmod +x "${workload}"
}

# Discover the key independently of the separator between version and driver.
# The first warm job runs under a different ID from the job under test.
prepare_seed() {
  GITHUB_RUN_ID=100 SMOKE_RC=7 run bash "${FAKE}/script/ci/stream_smoke_job.sh"
  [ "${status}" -eq 7 ]
  key_dir="$(find "${ISAAC_CI_CACHE_ROOT}" -mindepth 1 -maxdepth 1 -type d)"
  seed="${key_dir}/seed"
  run_dir="${key_dir}/run-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"
  local name
  for name in kit-cache computecache; do
    mkdir -p "${seed}/${name}"
    printf '%s\0seed\n' "${name}" > "${seed}/${name}/marker"
    touch "${seed}/${name}/obsolete"
  done
  cp -a "${seed}" "${BATS_TEST_TMPDIR}/original"
}

assert_run_mounts() {
  local expected="$1" workspace="${2:-${FAKE}}" name
  for name in kit-cache computecache; do
    [ "$(cat "${workspace}/observed/${name}.target")" = "${expected}/${name}" ]
  done
}

assert_discarded_run() {
  assert_run_mounts "${run_dir}"
  [ ! -e "${run_dir}" ]
  [ -f "${key_dir}/run-9876-1/active" ]
  diff -r "${BATS_TEST_TMPDIR}/original" "${seed}"
}

prepare_discarded_run() {
  prepare_seed
  mkdir -p "${key_dir}/run-9876-1"
  touch "${key_dir}/run-9876-1/active"
  install_cache_probe script/ci/stream_smoke.sh
}

check_cold_job() {
  prepare_discarded_run
  # A retry may encounter a leftover run directory with the same identity.
  mkdir -p "${run_dir}/"{kit-cache,computecache}
  touch "${run_dir}/"{kit-cache,computecache}/leftover
  run env "$@" bash "${FAKE}/script/ci/stream_smoke_job.sh"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"cache mode: cold (empty cache dir ${run_dir})"* ]]
  local name
  for name in kit-cache computecache; do
    [ -z "$(find "${FAKE}/observed/${name}" -mindepth 1 -print -quit)" ]
  done
  assert_discarded_run
}

@test "gpu integration job: apply, pin WS_PATH, build test, caches, gpu baseline, official startuptests -- in order" {
  run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  run cat "${CALLS}"
  [ "${lines[0]}" = "setup apply" ]
  [ "${lines[1]}" = "build -t test shared=1" ]
  [ "${lines[2]}" = "baseline --gpu project=isaac-baseline-1234-2 shared=unset" ]
  [ "${lines[3]}" = "WS_PATH=${FAKE}" ]
  [ "${lines[4]}" = "caches=writable" ]
  [[ "${lines[5]}" == "docker run "* ]]
  [ "${lines[6]}" = "pythontests" ]
  [ "${#lines[@]}" -eq 7 ]

  # The baseline gate must finish successfully before starting another Isaac.
  : > "${CALLS}"
  BASELINE_RC=3 run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -ne 0 ]
  run grep -c '^docker ' "${CALLS}"
  [ "${output}" = "0" ]
}

assert_startuptests_log() {
  local rc="$1"
  local artifacts="${FAKE}/artifacts/startuptests"
  local app_dir="${artifacts}/kit-logs/Kit/Isaac-Sim Streaming (Newton)/6.2"
  grep -Fxq "Kit startup fixture rc=${rc}" "${app_dir}/kit_20261127_162941.log"
}

assert_startuptests_report() {
  python3 - "${FAKE}/artifacts/startuptests/r.xml" "$@" <<'PY'
import sys
import xml.etree.ElementTree as ET

path, root_tag, failures, errors, *failure_messages = sys.argv[1:]
root = ET.parse(path).getroot()
assert root.tag == root_tag, root.tag
suite = root if root_tag == "testsuite" else root.find("testsuite")
assert suite.get("name") == "startuptests.default"
assert suite.get("failures") == failures and suite.get("errors") == errors, suite.attrib
assert len(suite.findall("testcase/error")) == int(errors)
main_failures = suite.findall("testcase[@name='tests-startup.main.sh']/failure")
assert [entry.get("message") for entry in main_failures] == failure_messages
PY
}

@test "gpu integration job: successful startuptests retain JUnit and the Kit log" {
  STARTUP_JUNIT_WRAPPED=1 run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  assert_startuptests_report testsuites 0 0
  assert_startuptests_log 0
}

@test "gpu integration job: failed startuptests fail the job and retain JUnit and the Kit log" {
  STARTUP_RC=23 run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 23 ]
  grep -q '^docker run ' "${CALLS}"
  assert_startuptests_report testsuite 1 0 "Exit code: 23"
  assert_startuptests_log 23
}

@test "gpu integration job: JUnit failure fails the job even when run_tests.py exits zero" {
  STARTUP_JUNIT_FAILURES=1 run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  assert_startuptests_report testsuite 1 0 "Exit code: 55"
  assert_startuptests_log 0
  [ "${status}" -ne 0 ]
}

@test "gpu integration job: an error inside testsuites fails the job even when run_tests.py exits zero" {
  STARTUP_JUNIT_WRAPPED=1 STARTUP_JUNIT_ERRORS=1 run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  assert_startuptests_report testsuites 0 1
  assert_startuptests_log 0
  [ "${status}" -ne 0 ]
}

@test "gpu integration job: a truncated JUnit report fails the job even when run_tests.py exits zero" {
  STARTUP_JUNIT_TRUNCATED=1 run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  grep -q '<testsuite ' "${FAKE}/artifacts/startuptests/r.xml"
  assert_startuptests_log 0
  [ "${status}" -ne 0 ]
}

@test "gpu integration job: works from any cwd (resolves the repo root itself)" {
  cd /
  run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  grep -qx "setup apply" "${CALLS}"
}

@test "gpu integration job: replaces existing cache dirs with run links keyed by BASE_IMAGE and first GPU driver" {
  echo 'ARG BASE_IMAGE="nvcr.io/nvidia/isaac-sim:9.9.9"' > "${FAKE}/Dockerfile"
  local sim="${FAKE}/isaac-sim" observed_key
  mkdir -p "${sim}/kit/cache" "${sim}/nvidia/computecache"
  touch "${sim}/kit/cache/old" "${sim}/nvidia/computecache/old"
  install_cache_probe

  run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"cache mode: warm (no seed yet)"* ]]
  observed_key="$(find "${ISAAC_CI_CACHE_ROOT}" -mindepth 1 -maxdepth 1 -type d)"
  [[ "${observed_key##*/}" == 9.9.9*550.54.15 ]]
  assert_run_mounts "${observed_key}/run-1234-2"
  [ ! -e "${FAKE}/observed/kit-cache/old" ]
  [ ! -e "${FAKE}/observed/computecache/old" ]
}

@test "gpu integration job: sanitizes the BASE_IMAGE override and still includes the driver" {
  echo 'ARG BASE_IMAGE="nvcr.io/nvidia/isaac-sim:9.9.9"' > "${FAKE}/Dockerfile"
  export ISAAC_CI_CACHE_KEY="Runner_2.test/cache"
  install_cache_probe
  run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  local observed_key
  observed_key="$(find "${ISAAC_CI_CACHE_ROOT}" -mindepth 1 -maxdepth 1 -type d)"
  [[ "${observed_key##*/}" == Runner_2.test_cache*550.54.15 ]]
  assert_run_mounts "${observed_key}/run-1234-2"
}

@test "gpu integration job: a failed nvidia-smi query uses nodriver" {
  printf '#!/bin/sh\nexit 1\n' > "${FAKE}/bin/nvidia-smi"
  install_cache_probe
  run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  local observed_key
  observed_key="$(find "${ISAAC_CI_CACHE_ROOT}" -mindepth 1 -maxdepth 1 -type d)"
  [[ "${observed_key##*/}" == default*nodriver ]]
  assert_run_mounts "${observed_key}/run-1234-2"
}

@test "gpu integration job: both caches survive workspace cleanup between runs" {
  unset ISAAC_CI_CACHE_ROOT
  local sim="${FAKE}/isaac-sim" observed_key
  install_cache_probe
  run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  observed_key="$(find "${HOME}/isaac-ci-cache" -mindepth 1 -maxdepth 1 -type d)"
  [[ "${observed_key##*/}" == default*550.54.15 ]]
  touch "${sim}/kit/data/previous-run"
  rm -rf "${sim}" "${FAKE}/observed"

  GITHUB_RUN_ID=1235 run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  assert_run_mounts "${observed_key}/run-1235-2"
  grep -Fxq 1234 "${FAKE}/observed/kit-cache/writer"
  grep -Fxq 1234 "${FAKE}/observed/computecache/writer"
  [ -d "${sim}/kit/data" ]
  [ ! -L "${sim}/kit/data" ]
  [ ! -e "${sim}/kit/data/previous-run" ]
}

@test "gpu integration job: baseline sees writable mounts and state dirs stay in the workspace" {
  run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  grep -qx 'caches=writable' "${CALLS}"

  local state path
  for state in kit/data kit/logs ov/cache ov/data ov/logs pip nvidia/glcache documents; do
    path="${FAKE}/isaac-sim/${state}"
    [ -d "${path}" ]
    [ ! -L "${path}" ]
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
  dir_perms=$(stat -c '%a' "${FAKE}/isaac-sim/kit/data")
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

@test "warm job sees a writable copy of each seeded cache and leaves the live seed untouched" {
  prepare_seed
  chmod 444 "${seed}/"{kit-cache,computecache}/marker
  chmod 755 "${seed}/"{kit-cache,computecache}
  install_cache_probe
  export ORIGINAL_SEED="${seed}"
  cat > "${FAKE}/after-cache-write.sh" <<'STUB'
diff -r "${BATS_TEST_TMPDIR}/original" "${ORIGINAL_SEED}"
STUB
  printf '%s\n' '{"inputs":{"final_acceptance":"false"}}' > "${FAKE}/event.json"

  GITHUB_EVENT_NAME=workflow_dispatch GITHUB_EVENT_PATH="${FAKE}/event.json" \
    run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"cache mode: warm (seed copied from ${seed})"* ]]
  assert_run_mounts "${run_dir}"
  local name snapshot
  for name in kit-cache computecache; do
    snapshot="${FAKE}/observed/${name}"
    diff -r "${BATS_TEST_TMPDIR}/original/${name}" "${snapshot}"
    [[ "$(stat -c '%a' "${snapshot}")" == *777 ]]
    [[ "$(stat -c '%a' "${snapshot}/marker")" == *666 ]]
  done
}

@test "successful visual stream job promotes the whole run directory and removes the old seed" {
  prepare_seed
  install_cache_probe script/ci/stream_visual_e2e.sh
  # Probe the real lock at the instant the job moves either directory.
  export SEED_DIR="${seed}" RUN_DIR="${run_dir}"
  local mv_bin
  mv_bin="$(command -v mv)"
  export REAL_MV="${mv_bin}"
  cat > "${FAKE}/bin/mv" <<'STUB'
#!/usr/bin/env bash
for arg in "$@"; do
  if [[ "${arg}" -ef "${SEED_DIR}" || "${arg}" -ef "${RUN_DIR}" ]]; then
    if flock -sn "${SEED_DIR%/*}/seed.lock" true; then
      echo "seed promotion requires an exclusive seed.lock" >&2
      exit 1
    fi
    break
  fi
done
exec "${REAL_MV}" "$@"
STUB
  chmod +x "${FAKE}/bin/mv"
  run bash "${FAKE}/script/ci/stream_visual_e2e_job.sh"
  [ "${status}" -eq 0 ]
  assert_run_mounts "${run_dir}"
  [ ! -e "${run_dir}" ]
  # A rename preserves the run directory's inode; copying back in place does not.
  [ "$(stat -c '%d:%i' "${seed}")" = "$(cat "${FAKE}/observed/kit-cache.parent-inode")" ]
  local name
  for name in kit-cache computecache; do
    grep -Fxq "${GITHUB_RUN_ID}" "${seed}/${name}/writer"
    cmp "${BATS_TEST_TMPDIR}/original/${name}/marker" "${seed}/${name}/marker"
    [ ! -e "${seed}/${name}/obsolete" ]
  done
  [ "$(find "${key_dir}" -mindepth 1 -maxdepth 1 -type d)" = "${seed}" ]
}

@test "failed smoke job deletes only its run and preserves both seed caches byte for byte" {
  prepare_discarded_run
  echo 'exit 23' > "${FAKE}/after-cache-write.sh"
  run bash "${FAKE}/script/ci/stream_smoke_job.sh"
  [ "${status}" -eq 23 ]
  assert_discarded_run
}

@test "SIGTERM after cache writes cancels the job and preserves both seed caches byte for byte" {
  prepare_discarded_run
  # Signal the job shell itself. Its foreground workload then exits successfully.
  cat > "${FAKE}/after-cache-write.sh" <<'STUB'
kill -TERM "${PPID}"
touch observed/term-sent
STUB
  run bash "${FAKE}/script/ci/stream_smoke_job.sh"
  [ "${status}" -ne 0 ]
  [ -f "${FAKE}/observed/term-sent" ]
  assert_discarded_run
}

@test "tag ref type uses an empty cold cache" {
  check_cold_job GITHUB_REF_TYPE=tag
}

@test "tag ref path uses an empty cold cache" {
  check_cold_job GITHUB_REF=refs/tags/v1.0
}

@test "ISAAC_CI_COLD_CACHE=1 uses an empty cold cache" {
  check_cold_job ISAAC_CI_COLD_CACHE=1
}

@test "workflow_dispatch final acceptance uses an empty cold cache" {
  command -v jq >/dev/null || skip "dispatch payload parsing requires jq"
  printf '%s\n' '{"inputs":{"final_acceptance":"true"}}' > "${FAKE}/event.json"
  check_cold_job GITHUB_EVENT_NAME=workflow_dispatch GITHUB_EVENT_PATH="${FAKE}/event.json"
}

@test "job startup removes day-old runs and preserves recent runs" {
  prepare_discarded_run
  export STALE_RUN="${key_dir}/run-2345-1"
  mkdir "${STALE_RUN}"
  touch -d '25 hours ago' "${STALE_RUN}"
  touch -d '23 hours ago' "${key_dir}/run-9876-1"
  cat > "${FAKE}/after-cache-write.sh" <<'STUB'
[[ ! -e "${STALE_RUN}" ]]
STUB

  run bash "${FAKE}/script/ci/stream_smoke_job.sh"
  [ "${status}" -eq 0 ]
  [ -f "${key_dir}/run-9876-1/active" ]
}

@test "retention keeps exactly the current key and the most recent other key" {
  prepare_seed
  local other
  for other in previous oldest newest; do
    mkdir -p "${ISAAC_CI_CACHE_ROOT}/${other}/seed/"{kit-cache,computecache}
    touch "${ISAAC_CI_CACHE_ROOT}/${other}/seed/kit-cache/marker"
  done
  # Both newer keys sort ahead of the current key even if it is touched at exit.
  touch -d '1 day ago' "${ISAAC_CI_CACHE_ROOT}/oldest"
  touch -d '1 day hence' "${ISAAC_CI_CACHE_ROOT}/previous"
  touch -d '2 days hence' "${ISAAC_CI_CACHE_ROOT}/newest"
  run bash "${FAKE}/script/ci/stream_smoke_job.sh"
  [ "${status}" -eq 0 ]
  [ -d "${seed}" ]
  [ -f "${ISAAC_CI_CACHE_ROOT}/newest/seed/kit-cache/marker" ]
  [ "$(find "${ISAAC_CI_CACHE_ROOT}" -mindepth 1 -maxdepth 1 -type d | wc -l)" -eq 2 ]
}

@test "concurrent successful jobs use separate runs and publish one complete seed" {
  prepare_seed
  install_cache_probe script/ci/stream_smoke.sh
  export BARRIER="${BATS_TEST_TMPDIR}/ready"
  mkdir "${BARRIER}"
  cat > "${FAKE}/after-cache-write.sh" <<'STUB'
touch "isaac-sim/kit/cache/job-${GITHUB_RUN_ID}" "isaac-sim/nvidia/computecache/job-${GITHUB_RUN_ID}"
touch "${BARRIER}/${GITHUB_RUN_ID}"
# Both jobs must have written their caches before either job exits.
for ((i = 0; i < 200; i++)); do
  [[ -f "${BARRIER}/1234" && -f "${BARRIER}/1235" ]] && exit 0
  sleep 0.05
done
exit 1
STUB
  local second="${BATS_TEST_TMPDIR}/second-workspace" first_pid second_pid
  cp -a "${FAKE}" "${second}"
  bash "${FAKE}/script/ci/stream_smoke_job.sh" > "${FAKE}/job.log" 2>&1 &
  first_pid=$!
  GITHUB_RUN_ID=1235 GITHUB_WORKSPACE="${second}" \
    bash "${second}/script/ci/stream_smoke_job.sh" > "${second}/job.log" 2>&1 &
  second_pid=$!
  local first_rc=0 second_rc=0
  wait "${first_pid}" || first_rc=$?
  wait "${second_pid}" || second_rc=$?
  [ "${first_rc}" -eq 0 ]
  [ "${second_rc}" -eq 0 ]
  assert_run_mounts "${run_dir}"
  assert_run_mounts "${key_dir}/run-1235-2" "${second}"
  [ ! -e "${run_dir}" ]
  [ ! -e "${key_dir}/run-1235-2" ]

  local winner name expected
  winner="$(cat "${seed}/kit-cache/writer")"
  [[ "${winner}" == 1234 || "${winner}" == 1235 ]]
  for name in kit-cache computecache; do
    expected="${BATS_TEST_TMPDIR}/original/${name}"
    diff -r "${expected}" "${FAKE}/observed/${name}"
    diff -r "${expected}" "${second}/observed/${name}"
    rm "${expected}/obsolete"
    echo "${winner}" > "${expected}/writer"
    touch "${expected}/job-${winner}"
  done
  diff -r "${BATS_TEST_TMPDIR}/original" "${seed}"
}
