#!/usr/bin/env bash
# headless_smoke.sh -- boot check for the headless stage (isaac#461).
#
# Nothing else in CI starts the headless stage: it is only built. base's
# compose gives it `restart: unless-stopped`, so a broken start command or
# environment is not a failed start, it is a container that restarts forever
# -- with the hosted pytest, the bats and the GPU jobs all green.
#
# Flow: `./script/run.sh -t headless -d` under its own compose project ->
# resolve the container by project -> for a settle window require
# State.Status == running AND RestartCount == 0 -> tear the project down
# (always).
#
# RestartCount is checked on purpose: a crash-looping container reports
# `running` between two restarts, so Status alone passes it intermittently.
#
# Environment:
#   SMOKE_PROJECT     compose project for this run
#                     (default: <derived project>-headless-smoke)
#   HEADLESS_SETTLE   seconds the container must stay up (default 20)
#   HEADLESS_POLL     seconds between checks (default 2)
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
settle_s="${HEADLESS_SETTLE:-20}"
poll_s="${HEADLESS_POLL:-2}"

if [[ -f "${repo_root}/.env.generated" ]]; then
  set -a
  # shellcheck source=/dev/null
  . "${repo_root}/.env.generated"
  set +a
fi
_default_project="${DOCKER_HUB_USER:-local}-${IMAGE_NAME:-isaac}"
project="${SMOKE_PROJECT:-${PROJECT_NAME:-${_default_project}}-headless-smoke}"

# run.sh reads the pinned PROJECT_NAME from .env.generated, so the whole stack
# lands in ${project} and the teardown below cannot touch a developer's
# default-project stack on a shared host.
if [[ -f "${repo_root}/.env.generated" ]]; then
  sed -i "s|^PROJECT_NAME=.*|PROJECT_NAME=${project}|" \
    "${repo_root}/.env.generated"
fi

compose_smoke() {
  docker compose -p "${project}" \
    --env-file "${repo_root}/.env.generated" \
    -f "${repo_root}/compose.yaml" "$@"
}

cleanup() {
  echo "[headless-smoke] teardown: down project ${project}"
  # COMPOSE_PROFILES='*': the headless service sits behind a profile, and a
  # plain `down` skips services of inactive profiles (same as stream_smoke).
  COMPOSE_PROFILES='*' compose_smoke down -t 0 --remove-orphans \
    >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

fail() {
  echo "[headless-smoke] FAIL: $*" >&2
  exit 1
}

echo "[headless-smoke] bring up headless stage (project ${project})"
( cd "${repo_root}" && ./script/run.sh -t headless -d ) \
  || fail "run.sh -t headless -d exited non-zero"

cid="$(compose_smoke ps -aq headless 2>/dev/null | head -1)"
[[ -n "${cid}" ]] || fail "no headless container found in project ${project}"

# One check: Status must be running and RestartCount 0.
check_up() {
  local state status restarts
  state="$(docker inspect -f '{{.State.Status}} {{.RestartCount}}' "${cid}" 2>/dev/null)" \
    || fail "cannot inspect container ${cid}"
  status="${state%% *}"
  restarts="${state##* }"
  [[ "${status}" == "running" ]] \
    || fail "headless container is ${status} (expected running), RestartCount=${restarts}"
  [[ "${restarts}" == "0" ]] \
    || fail "headless container restarted: RestartCount=${restarts} (expected 0)"
}

echo "[headless-smoke] settle window ${settle_s}s (poll ${poll_s}s)"
elapsed=0
check_up
while (( elapsed < settle_s )); do
  sleep "${poll_s}"
  elapsed=$(( elapsed + poll_s ))
  check_up
done

echo "[headless-smoke] OK: headless stayed running, RestartCount=0 for ${settle_s}s"
