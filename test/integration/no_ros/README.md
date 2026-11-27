# ROS independence checks

These reverse tests verify that Isaac can run without a ROS dependency and does not load any ROS modules when no I/O plugin is configured. This is deliberately the only directory under `test/integration/` where tests may name ROS modules. The suite runs in the same GPU job as the other integration tests.

| File | Purpose |
| --- | --- |
| `test_io_plugin_integration.py` | Checks the marker prim with the plugin enabled and checks for loaded modules with the plugin unset. |
| `_io_plugin_runner.py` | Boots the driver and reports the marker prim and loaded modules. The headless example uses the same module filter. |
| `_io_plugin_marker.py` | Defines the fake plugin that creates the marker prim on the robot. |
| `conftest.py` | Loads the shared pytest group checks. |
