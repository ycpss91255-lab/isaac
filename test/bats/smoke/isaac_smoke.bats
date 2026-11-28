#!/usr/bin/env bats
# bats file_tags=core
#
# Isaac Sim image smoke. Image-side; runs in /smoke_test/ inside the
# test stage built atop the Dockerfile's BASE_IMAGE (nvcr.io/nvidia/isaac-sim).

setup() {
  load "${BATS_TEST_DIRNAME}/test_helper"
}

@test "isaac-sim launchers exist and are executable" {
  test -x /isaac-sim/runheadless.sh
  test -x /isaac-sim/runapp.sh
}

@test "isaac-sim ships Python 3.12 in /isaac-sim/kit/python/bin/python3" {
  test -x /isaac-sim/kit/python/bin/python3
  run /isaac-sim/kit/python/bin/python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
  assert_success
  assert_output "3.12"
}

@test "runtime user is host-aligned (not root, not isaac-sim default)" {
  run id -un
  assert_success
  refute_output "root"
  refute_output "isaac-sim"
}

@test "runtime user is in isaac-sim group (can read /isaac-sim/* mode 0750)" {
  run id -nG
  assert_success
  assert_output --partial "isaac-sim"
}

@test "HOME is writable" {
  test -w "${HOME}"
}

@test "bundled ROS 2 humble + jazzy libs are both readable" {
  assert_dir_exists /isaac-sim/exts/isaacsim.ros2.core/humble/lib
  assert_dir_exists /isaac-sim/exts/isaacsim.ros2.core/jazzy/lib
  run ls /isaac-sim/exts/isaacsim.ros2.core/humble/lib/librmw_fastrtps_cpp.so
  assert_success
  run ls /isaac-sim/exts/isaacsim.ros2.core/jazzy/lib/librmw_fastrtps_cpp.so
  assert_success
}

@test "bundled ROS 2 humble + jazzy rclpy are both readable (Python 3.12)" {
  assert_dir_exists /isaac-sim/exts/isaacsim.ros2.core/humble/rclpy/rclpy
  assert_dir_exists /isaac-sim/exts/isaacsim.ros2.core/jazzy/rclpy/rclpy
}

@test "optional training and URDF packages are absent from standalone Sim Python" {
  for module in isaaclab torch xa"cro"; do
    run /isaac-sim/python.sh -c '
from importlib import import_module
from sys import argv

try:
    import_module(argv[1])
except ModuleNotFoundError as error:
    if error.name != argv[1]:
        raise
    print(f"ModuleNotFoundError: {error}")
else:
    raise SystemExit(f"{argv[1]} unexpectedly imports")
' "${module}"
    assert_success
    assert_output "ModuleNotFoundError: No module named '${module}'"
  done
}

# Isaac Sim shares prebundled packages between extensions as symlink
# farms. A pip step that deletes the copy the others link into leaves the
# package without an importable __init__.py -- on 6.0.1 that was
# `packaging` under omni.services.pip_archive, which silently broke
# matplotlib plots and the Newton experience (isaac#288).
@test "no pip_prebundle package lost its __init__.py (isaac#288)" {
  run find /isaac-sim -xtype l -name '__init__.py' -path '*pip_prebundle*'
  assert_success
  assert_output ""
}
