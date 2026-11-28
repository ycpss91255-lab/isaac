# ROS independence checks

These reverse tests verify that Isaac can run without a ROS dependency and does not load any ROS modules when no I/O plugin is configured. This is deliberately the only directory under `test/integration/` where tests may name ROS modules. The suite runs in the same GPU job as the other integration tests. The `[FILE-TIMING]` report excludes the test files in this directory.

| File | Purpose |
| --- | --- |
| `test_io_plugin_integration.py` | Checks the marker prim with the plugin enabled and checks for loaded modules with the plugin unset. |
| `_io_plugin_runner.py` | Boots the driver and reports the marker prim and loaded modules. |
| `_io_plugin_marker.py` | Defines the fake plugin that creates the marker prim on the robot. |
| `test_scene_default_driver.py`, `_scene_default_driver_runner.py` | Open the Jetbot USD with the default driver and check that the timeline advances for 20 updates with no ROS modules loaded. |
| `test_output_mode_python_gpu.py` | Checks that Python output mode delivers an RGB frame with zero `isaacsim.ros2.bridge.*` OmniGraph nodes, and that step time holds 30 Hz. |
| `_output_mode_runner.py` | Boots the Jetbot scene in Python mode and prints the RGB count, ROS node count and step-time markers. |
| `conftest.py` | Loads the shared pytest group checks. |
