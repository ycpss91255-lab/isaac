#!/usr/bin/env bats
# bats file_tags=core
#
# Repo-specific runtime smoke tests. Exercise the `devel` image built
# from this repo's Dockerfile, via the `test` stage. Use the shared
# helpers in test_helper.bash (assert_cmd_installed, assert_file_exists,
# assert_dir_exists, assert_file_owned_by, assert_pip_pkg, ...) to keep
# assertions terse. Add one assertion per meaningful installation
# artifact.

setup() {
  load "${BATS_TEST_DIRNAME}/test_helper"
}

@test "entrypoint.sh is installed and executable" {
  assert_file_exists /entrypoint.sh
  assert [ -x /entrypoint.sh ]
}

@test "bash is available on PATH" {
  assert_cmd_installed bash
}

@test "fastdds.xml is baked at /isaac-sim/fastdds.xml and world-readable" {
  assert_file_exists /isaac-sim/fastdds.xml
  test -r /isaac-sim/fastdds.xml
  run grep -q '<useBuiltinTransports>false</useBuiltinTransports>' /isaac-sim/fastdds.xml
  assert_success
}

@test "NVIDIA's full streaming Kit experience is present and readable" {
  local experience=/isaac-sim/apps/isaacsim.exp.full.streaming.kit
  assert_file_exists "$experience"
  test -r "$experience"
}

@test "devel stage drops the NGC Kit healthcheck (idle containers are not 'unhealthy')" {
  # nvcr.io/nvidia/isaac-sim ships a HEALTHCHECK that greps a Kit log for
  # "App is loaded". devel / headless / stream / test idle with no Kit by
  # design, and this repo mounts the Kit logs elsewhere, so every container
  # was reported `unhealthy` forever. The devel stage (inherited by the
  # others) must reset it.
  run awk '/^FROM .* AS devel$/{p=1; next} /^FROM /{p=0} p && /^HEALTHCHECK NONE/{found=1} END{exit !found}' /lint/Dockerfile
  assert_success
}
