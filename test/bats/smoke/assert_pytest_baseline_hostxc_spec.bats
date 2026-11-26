#!/usr/bin/env bats
# bats file_tags=core
#
# Guard for isaac#460: the host-side cross-container leg of
# `assert_pytest_baseline.sh --gpu` must not be able to silently vanish.
# Previously a missing host pytest (warning only), a missing JUnit report,
# or an all-skipped leg still let the GPU job print OK because the
# in-container run alone collected GPU_INTEGRATION_BASELINE tests.
#
# Hermetic: a stub run.sh writes a canned in-container report, and a python3
# shim in PATH simulates the host pytest (absent / no report / all skipped /
# passing). No docker, no GPU.

bats_require_minimum_version 1.5.0

setup() {
  FAKE="$(mktemp -d)"
  mkdir -p "${FAKE}/test" "${FAKE}/script" "${FAKE}/bin"
  REAL_PY="$(command -v python3)"
  export REAL_PY

  cp "${BATS_TEST_DIRNAME}/assert_pytest_baseline.sh" \
    "${FAKE}/test/assert_pytest_baseline.sh"
  chmod +x "${FAKE}/test/assert_pytest_baseline.sh"

  cat > "${FAKE}/test/pytest-baseline.txt" <<'BASE'
HOSTED_UNIT_BASELINE = 1
GPU_INTEGRATION_BASELINE = 3
AGGREGATE_TARGET = 4
BASE

  # In-container leg: 3 passing tests, enough to meet the baseline alone.
  cat > "${FAKE}/script/run.sh" <<STUB
#!/usr/bin/env bash
cat > "${FAKE}/test/.gpu-pytest-report.xml" <<'XML'
<testsuites><testsuite tests="3" failures="0" errors="0" skipped="0"/></testsuites>
XML
exit 0
STUB
  chmod +x "${FAKE}/script/run.sh"

  # python3 shim simulating the host pytest according to XC_MODE.
  cat > "${FAKE}/bin/python3" <<'SHIM'
#!/usr/bin/env bash
if [[ "$1" == "-m" && "$2" == "pytest" ]]; then
  if [[ "$3" == "--version" ]]; then
    [[ "${XC_MODE}" == "nopytest" ]] && exit 1
    exit 0
  fi
  case "${XC_MODE}" in
    noreport) exit 1 ;;
    skipped) xml='<testsuite tests="2" failures="0" errors="0" skipped="2"/>' ;;
    ok) xml='<testsuite tests="2" failures="0" errors="0" skipped="0"/>' ;;
  esac
  for a in "$@"; do
    case "${a}" in --junitxml=*) printf '%s\n' "${xml}" > "${a#--junitxml=}" ;; esac
  done
  exit 0
fi
exec "${REAL_PY}" "$@"
SHIM
  chmod +x "${FAKE}/bin/python3"
  export PATH="${FAKE}/bin:${PATH}"
}

teardown() {
  rm -rf "${FAKE}"
}

@test "assert_pytest_baseline --gpu fails when host python3 has no pytest (isaac#460)" {
  export XC_MODE=nopytest
  run "${FAKE}/test/assert_pytest_baseline.sh" --gpu
  [ "$status" -ne 0 ]
  [[ "$output" == *"host python3 has no pytest"* ]]
}

@test "assert_pytest_baseline --gpu fails when the host leg produces no JUnit report (isaac#460)" {
  export XC_MODE=noreport
  run "${FAKE}/test/assert_pytest_baseline.sh" --gpu
  [ "$status" -ne 0 ]
  [[ "$output" == *"no JUnit report"* ]]
}

@test "assert_pytest_baseline --gpu fails when the host leg has zero passing tests (isaac#460)" {
  export XC_MODE=skipped
  run "${FAKE}/test/assert_pytest_baseline.sh" --gpu
  [ "$status" -ne 0 ]
  [[ "$output" == *"passed 0"* ]]
}

@test "assert_pytest_baseline --gpu passes when the host leg runs and passes (isaac#460)" {
  export XC_MODE=ok
  run "${FAKE}/test/assert_pytest_baseline.sh" --gpu
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK: gpu-integration"* ]]
}
