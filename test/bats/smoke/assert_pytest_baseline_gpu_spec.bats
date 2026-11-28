#!/usr/bin/env bats
# bats file_tags=core

bats_require_minimum_version 1.5.0

setup() {
  baseline="${BATS_TEST_TMPDIR}/test"
  mkdir -p "${baseline}" "${BATS_TEST_TMPDIR}/script"
  cp "${BATS_TEST_DIRNAME}/assert_pytest_baseline.sh" "${baseline}/"

  cat > "${baseline}/pytest-baseline.txt" <<'BASE'
HOSTED_UNIT_BASELINE = 1
GPU_INTEGRATION_BASELINE = 3
AGGREGATE_TARGET = 4
BASE

  # Simulate the container writing its JUnit report to the bind mount.
  cat > "${BATS_TEST_TMPDIR}/script/run.sh" <<'STUB'
#!/usr/bin/env bash
if [[ -n "${GPU_TEST_REPORT:-}" ]]; then
  echo "${GPU_TEST_REPORT}" > "${BATS_TEST_TMPDIR}/test/.gpu-pytest-report.xml"
fi
STUB
  chmod +x "${BATS_TEST_TMPDIR}/script/run.sh"
}

@test "GPU baseline requires a container JUnit report" {
  run env -u GPU_TEST_REPORT "${baseline}/assert_pytest_baseline.sh" --gpu
  [ "$status" -eq 1 ]
  [[ "$output" == *"no JUnit report"* ]]
}

@test "GPU baseline requires at least one passing test" {
  run env GPU_TEST_REPORT='<testsuite tests="3" skipped="3"/>' \
    "${baseline}/assert_pytest_baseline.sh" --gpu
  [ "$status" -eq 1 ]
  [[ "$output" == *"0 passing tests"* ]]
}

@test "GPU baseline enforces the in-container collection floor" {
  run env GPU_TEST_REPORT='<testsuite tests="2"/>' \
    "${baseline}/assert_pytest_baseline.sh" --gpu
  [ "$status" -eq 1 ]
  [[ "$output" == *"collected 2 < baseline"* ]]
}

@test "GPU baseline counts the container report once in the aggregate" {
  run env GPU_TEST_REPORT='<testsuites><testsuite tests="3" skipped="1"/></testsuites>' \
    "${baseline}/assert_pytest_baseline.sh" --gpu
  [ "$status" -eq 0 ]
  [[ "$output" == *"2 passed, "*"aggregate 4 >= target 4"* ]]
}
