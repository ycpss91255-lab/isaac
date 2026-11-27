#!/usr/bin/env bash
# Smoke test for isaac_ws/src/script/*_standalone.py
#
# For each standalone script: launch via just docker exec -t standalone, watch
# stdout for the script's "ready marker" phrase, kill once seen. If the
# marker doesn't appear within TIMEOUT, the case fails.
#
# Exit codes:
#   0 = all selected cases PASS
#   1 = at least one FAIL
#   2 = unknown flag or pre-flight failure (docker dir missing / standalone container won't start)
#
# Flags:
#   --only <name>  Run a single case by script basename (substring match).
#   -h, --help     Print usage.
#

set -uo pipefail

DOCKER_DIR="${HOME}/workspace/coreSAM_ws/isaac_ws/src/docker"
SCRIPT_PATH_IN_CONTAINER="${HOME}/work/src/script"
CONTAINER="$(id -un)-isaac-standalone"

# Smoke matrix: <basename>|<grep-marker>|<timeout-sec>
CASES=(
)

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
  exit 0
}

ONLY=""
while (( $# > 0 )); do
  case "$1" in
    --only) ONLY="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
done

if (( ${#CASES[@]} == 0 )); then
  echo "No standalone smoke cases configured."
  exit 0
fi

# Pre-flight ---------------------------------------------------------
if [[ ! -d "$DOCKER_DIR" ]]; then
  echo "FAIL: docker dir missing: $DOCKER_DIR" >&2
  exit 2
fi

# Bring standalone up if needed (no-op if already running)
if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "[smoke] starting standalone container..."
  "$DOCKER_DIR/run.sh" -t standalone -d >/dev/null 2>&1 || {
    echo "FAIL: just docker run -t standalone -d failed" >&2
    exit 2
  }
  sleep 3
fi

# Per-case runner ----------------------------------------------------
# Args: script_basename, marker_regex, timeout_sec
# Returns 0 for PASS or 1 for FAIL.
_run_case() {
  local script="$1" marker="$2" timeout="$3"

  local tmp
  tmp="$(mktemp)"

  # Launch script in background; capture stdout+stderr to tmp.
  "$DOCKER_DIR/exec.sh" -t standalone /isaac-sim/python.sh \
    "$SCRIPT_PATH_IN_CONTAINER/$script" > "$tmp" 2>&1 &
  local exec_pid=$!

  local elapsed=0 result="FAIL"
  while (( elapsed < timeout )); do
    if grep -q -E "$marker" "$tmp" 2>/dev/null; then
      result="PASS"
      break
    fi
    if ! kill -0 "$exec_pid" 2>/dev/null; then
      # Process died before marker — likely error in script
      break
    fi
    sleep 1
    elapsed=$(( elapsed + 1 ))
  done

  # Cleanup: kill local exec wrapper + remote python.sh inside container.
  # docker exec doesn't propagate SIGTERM to the remote process, so kill
  # remote explicitly too.
  kill -TERM "$exec_pid" 2>/dev/null
  docker exec "$CONTAINER" bash -c \
    'pkill -TERM -f /isaac-sim/python.sh' 2>/dev/null
  wait "$exec_pid" 2>/dev/null

  if [[ "$result" == "FAIL" ]]; then
    echo "FAIL $script (marker '$marker' not reached within ${elapsed}s)"
    echo "--- last 20 lines of stdout/stderr ---"
    tail -20 "$tmp" >&2
    echo "--- end ---"
  else
    echo "PASS $script (${elapsed}s)"
  fi

  rm -f "$tmp"
  [[ "$result" == "PASS" ]]
}

# Drive matrix -------------------------------------------------------
pass=0 fail=0
for c in "${CASES[@]}"; do
  IFS='|' read -r script marker timeout <<< "$c"
  if [[ -n "$ONLY" && "$script" != *"$ONLY"* ]]; then
    continue
  fi
  echo "=== $script ==="
  if _run_case "$script" "$marker" "$timeout"; then
    pass=$(( pass + 1 ))
  else
    fail=$(( fail + 1 ))
  fi
  # Settle between cases — let previous kit fully exit
  sleep 5
done

echo "---"
echo "smoke summary: pass=$pass fail=$fail"

if (( fail > 0 )); then
  exit 1
fi
exit 0
