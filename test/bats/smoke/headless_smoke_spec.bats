#!/usr/bin/env bats
# bats file_tags=headless
#
# Behavioral guard for script/ci/headless_smoke.sh (isaac#461).
#
# The headless stage was never started by any test: CI only built it, and the
# GPU jobs ran the `test` and `stream` stages. base's compose gives headless
# `restart: unless-stopped`, so a broken start command or environment shows up
# as a container that restarts forever, while the hosted pytest, the bats and
# both GPU jobs stay green (reproduced by changing the stage CMD to `false`).
#
# headless_smoke.sh starts the stage with `./script/run.sh -t headless -d`
# under its own compose project, waits a settle window, and requires
# State.Status == running AND RestartCount == 0 (a restarting container is
# also "Running" between two restarts, so Running alone is not enough). It
# tears the project down on every exit.
#
# The real script runs against a stub run.sh and a stub docker that record
# their argv. The stub docker answers `inspect` from the HEADLESS_STATE
# fixture ("<status> <restarts>"), so each verdict is driven by what the
# container looks like. No real docker, no GPU.
#
# Baked into /smoke_test/ next to the script by the devel-test stage.

bats_require_minimum_version 1.5.0

setup() {
  FAKE="$(mktemp -d)"
  mkdir -p "${FAKE}/script/ci" "${FAKE}/bin"
  cp "${BATS_TEST_DIRNAME}/headless_smoke.sh" "${FAKE}/script/ci/headless_smoke.sh"
  chmod +x "${FAKE}/script/ci/headless_smoke.sh"

  cat > "${FAKE}/.env.generated" <<'ENV'
USER_NAME=alice
IMAGE_NAME=isaac
DOCKER_HUB_USER=alice
PROJECT_NAME=alice-isaac
ENV
  printf 'name: ${PROJECT_NAME}\n' > "${FAKE}/compose.yaml"

  export RUN_ARGS_FILE="${FAKE}/run-args.txt"
  cat > "${FAKE}/script/run.sh" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$@" >> "${RUN_ARGS_FILE:?}"
exit "${STUB_RUN_RC:-0}"
STUB
  chmod +x "${FAKE}/script/run.sh"

  export DOCKER_ARGS_FILE="${FAKE}/docker-args.txt"
  cat > "${FAKE}/bin/docker" <<'STUB'
#!/usr/bin/env bash
printf '[profiles=%s] %s\n' "${COMPOSE_PROFILES:-}" "$*" >> "${DOCKER_ARGS_FILE:?}"
case "$*" in
  *"ps -aq headless"*)
    [ "${STUB_NO_CONTAINER:-0}" = 1 ] || echo cid0 ;;
  inspect\ -f*)
    echo "${HEADLESS_STATE:-running 0}" ;;
esac
exit 0
STUB
  chmod +x "${FAKE}/bin/docker"
  export PATH="${FAKE}/bin:${PATH}"

  # Short windows: the stub answers instantly.
  export HEADLESS_SETTLE=2 HEADLESS_POLL=1
  unset SMOKE_PROJECT STUB_RUN_RC STUB_NO_CONTAINER HEADLESS_STATE
}

teardown() {
  rm -rf "${FAKE}"
}

@test "headless_smoke: a running container with no restarts passes" {
  export HEADLESS_STATE="running 0"
  run "${FAKE}/script/ci/headless_smoke.sh"
  [ "${status}" -eq 0 ]
}

@test "headless_smoke: starts the headless stage detached, never another stage" {
  run "${FAKE}/script/ci/headless_smoke.sh"
  [ "${status}" -eq 0 ]
  grep -qx -- '-t' "${RUN_ARGS_FILE}"
  grep -qx -- 'headless' "${RUN_ARGS_FILE}"
  grep -qx -- '-d' "${RUN_ARGS_FILE}"
  ! grep -qx -- 'stream' "${RUN_ARGS_FILE}"
}

@test "headless_smoke: a restarting container fails (the #461 symptom)" {
  export HEADLESS_STATE="restarting 9"
  run "${FAKE}/script/ci/headless_smoke.sh"
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"restarting"* ]]
}

@test "headless_smoke: a container that restarted but is running now still fails" {
  # Between two restarts a crash-looping container reports running.
  export HEADLESS_STATE="running 3"
  run "${FAKE}/script/ci/headless_smoke.sh"
  [ "${status}" -ne 0 ]
  [[ "${output}" == *"RestartCount"* ]]
}

@test "headless_smoke: an exited container fails" {
  export HEADLESS_STATE="exited 0"
  run "${FAKE}/script/ci/headless_smoke.sh"
  [ "${status}" -ne 0 ]
}

@test "headless_smoke: no container for the project fails closed" {
  export STUB_NO_CONTAINER=1
  run "${FAKE}/script/ci/headless_smoke.sh"
  [ "${status}" -ne 0 ]
}

@test "headless_smoke: a failing run.sh fails the smoke" {
  export STUB_RUN_RC=1
  run "${FAKE}/script/ci/headless_smoke.sh"
  [ "${status}" -ne 0 ]
}

@test "headless_smoke: runs under its own compose project and tears it down, pass or fail" {
  export SMOKE_PROJECT=alice-isaac-hl-demo
  export HEADLESS_STATE="restarting 9"
  run "${FAKE}/script/ci/headless_smoke.sh"
  [ "${status}" -ne 0 ]
  grep -qx 'PROJECT_NAME=alice-isaac-hl-demo' "${FAKE}/.env.generated"
  grep -q "profiles=\\*\\] compose -p alice-isaac-hl-demo .* down" "${DOCKER_ARGS_FILE}"
  # Never the default project a developer's stack lives in.
  ! grep -q "compose -p alice-isaac " "${DOCKER_ARGS_FILE}"
}

@test "headless_smoke: the project defaults to '<derived>-headless-smoke'" {
  run "${FAKE}/script/ci/headless_smoke.sh"
  [ "${status}" -eq 0 ]
  grep -qx 'PROJECT_NAME=alice-isaac-headless-smoke' "${FAKE}/.env.generated"
}

# --- the GPU job script (headless_smoke_job.sh) --------------------------

job_setup() {
  JFAKE="$(mktemp -d)"
  mkdir -p "${JFAKE}/script/ci"
  for f in gpu_job_lib.sh headless_smoke_job.sh; do
    cp "${BATS_TEST_DIRNAME}/${f}" "${JFAKE}/script/ci/${f}"
  done
  export CALLS="${JFAKE}/calls.log" GITHUB_WORKSPACE="${JFAKE}"
  export GITHUB_RUN_ID=1234 GITHUB_RUN_ATTEMPT=2
  cat > "${JFAKE}/script/setup.sh" <<'STUB'
#!/usr/bin/env bash
echo "setup $*" >> "${CALLS}"
printf 'WS_PATH=/wrong/parent\n' > .env.generated
STUB
  cat > "${JFAKE}/script/build.sh" <<'STUB'
#!/usr/bin/env bash
echo "build $*" >> "${CALLS}"
STUB
  cat > "${JFAKE}/script/ci/headless_smoke.sh" <<'STUB'
#!/usr/bin/env bash
echo "smoke project=${SMOKE_PROJECT:-unset}" >> "${CALLS}"
exit "${SMOKE_RC:-0}"
STUB
  chmod +x "${JFAKE}/script/"*.sh "${JFAKE}/script/ci/"*.sh
}

@test "headless smoke job: apply, build headless, smoke under a per-run project -- in order" {
  job_setup
  run bash "${JFAKE}/script/ci/headless_smoke_job.sh"
  [ "${status}" -eq 0 ]
  run cat "${CALLS}"
  [ "${lines[0]}" = "setup apply" ]
  [ "${lines[1]}" = "build -t headless" ]
  [ "${lines[2]}" = "smoke project=isaac-hl-smoke-1234-2" ]
  rm -rf "${JFAKE}"
}

@test "headless smoke job: a failing smoke fails the job" {
  job_setup
  SMOKE_RC=1 run bash "${JFAKE}/script/ci/headless_smoke_job.sh"
  [ "${status}" -eq 1 ]
  rm -rf "${JFAKE}"
}
