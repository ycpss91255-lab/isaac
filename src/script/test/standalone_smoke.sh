#!/usr/bin/env bash
# Smoke test for standalone Python scripts in src/script.
#
# For each standalone script: launch via just docker exec -T -t stream, watch
# stdout for the script's "ready marker" phrase, kill once seen. If the
# marker doesn't appear within TIMEOUT, the case fails.
#
# Exit codes:
#   0 = all selected cases PASS
#   1 = at least one FAIL
#   2 = unknown flag or pre-flight failure (checkout unavailable or stream container won't start)
#
# Flags:
#   --only <name>  Run a single case by script basename (substring match).
#   -h, --help     Print usage.
#
# Environment overrides:
#   ISAAC_SMOKE_REPO_DIR    Host checkout containing the justfile (default: this script's checkout).
#   ISAAC_SMOKE_SCRIPT_DIR  Script directory in the container (default: src/script,
#                           relative to the mounted checkout workdir).

set -uo pipefail

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

# Resolve the host checkout independently of the caller's working directory.
repo_dir="${ISAAC_SMOKE_REPO_DIR:-$(dirname -- "${BASH_SOURCE[0]}")/../../..}"
SCRIPT_PATH_IN_CONTAINER="${ISAAC_SMOKE_SCRIPT_DIR:-src/script}"
if ! cd -- "$repo_dir" || [[ ! -f justfile ]]; then
  echo "FAIL: checkout containing justfile unavailable: $repo_dir" >&2
  exit 2
fi

# Reuse the stream service in this checkout's Compose project if running.
if ! just docker exec -T -t stream true >/dev/null 2>&1; then
  echo "[smoke] starting stream container..."
  just docker run -t stream -d || {
    echo "FAIL: just docker run -t stream -d failed" >&2
    exit 2
  }
  sleep 3
fi

# Per-case runner ----------------------------------------------------
# Args: script_basename, marker_regex, timeout_sec
# Returns 0 for PASS or 1 for FAIL.
_run_case() {
  local script="$1" marker="$2" timeout="$3"

  local script_path="$SCRIPT_PATH_IN_CONTAINER/$script"
  local tmp
  tmp="$(mktemp)"

  # Launch script in background; capture stdout+stderr to tmp.
  just docker exec -T -t stream /isaac-sim/python.sh \
    "$script_path" > "$tmp" 2>&1 &
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

  # Compose does not forward SIGTERM to the remote process. Match both the
  # Isaac launcher and its Python child, escaping the configurable path.
  local script_pattern
  script_pattern="$(sed 's/[][\.^$*+?(){}|]/\\&/g' <<< "$script_path")"
  kill -TERM "$exec_pid" 2>/dev/null
  just docker exec -T -t stream pkill -TERM -f -- \
    "(^| )/isaac-sim/(python[.]sh|kit/python/bin/python3) ${script_pattern}$" >/dev/null 2>&1
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
