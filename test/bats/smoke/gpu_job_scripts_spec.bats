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
# setup.sh / build.sh / assert_pytest_baseline.sh / stream_smoke.sh / docker that
# record what they receive. No docker, no GPU.
#
# Baked into /smoke_test/ next to the job scripts by the devel-test stage.

bats_require_minimum_version 1.5.0

setup() {
  FAKE="$(mktemp -d)"
  local scripts="${BATS_TEST_DIRNAME}"
  if [ ! -f "${scripts}/gpu_integration_job.sh" ]; then
    scripts="${BATS_TEST_DIRNAME}/../../../script/ci"
  fi
  mkdir -p "${FAKE}/script/ci" "${FAKE}/test" "${FAKE}/bin"
  for f in gpu_job_lib.sh gpu_integration_job.sh stream_smoke_job.sh; do
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
  export GITHUB_RUN_ID=1234
  export GITHUB_RUN_ATTEMPT=2
  unset ISAAC_ALLOW_SHARED_IDENTITY BASELINE_PROJECT GPU_ROS_DOMAIN_ID \
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
  echo "baseline $* project=${BASELINE_PROJECT:-unset} domain=${GPU_ROS_DOMAIN_ID:-unset} shared=${ISAAC_ALLOW_SHARED_IDENTITY:-unset}"
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
  chmod +x "${FAKE}/script/setup.sh" "${FAKE}/script/build.sh" \
    "${FAKE}/test/assert_pytest_baseline.sh" "${FAKE}/script/ci/stream_smoke.sh"
}

teardown() {
  rm -rf "${FAKE}"
}

@test "gpu integration job: apply, pin WS_PATH, build test, caches, gpu baseline, official startuptests -- in order" {
  run bash "${FAKE}/script/ci/gpu_integration_job.sh"
  [ "${status}" -eq 0 ]
  run cat "${CALLS}"
  [ "${lines[0]}" = "setup apply" ]
  [ "${lines[1]}" = "build -t test shared=1" ]
  [ "${lines[2]}" = "baseline --gpu project=isaac-baseline-1234-2 domain=47 shared=unset" ]
  [ "${lines[3]}" = "WS_PATH=${FAKE}" ]
  [ "${lines[4]}" = "caches=writable" ]
  [[ "${lines[5]}" == "docker run "* ]]
  [ "${#lines[@]}" -eq 6 ]

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
