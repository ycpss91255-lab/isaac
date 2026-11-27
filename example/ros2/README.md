# example/ros2 -- app-side ROS 2 templates

These ROS 2 Humble nodes subscribe to camera images from an Isaac scene and publish velocity commands on `/cmd_vel`.

This is the ROS 2-by-default bidirectional topology embodied structurally
(ADR-0017 section 6): the framework owns the bridge wiring on the Isaac
side; your application logic lives in standard ROS 2 packages over here.

Two templates are provided so you can pick your language:

| Package | Build type | Language | Nodes |
|---|---|---|---|
| [`src/example_app_py`](src/example_app_py/) | `ament_python` | Python | `camera_subscriber`, `cmd_vel_publisher` |
| [`src/example_app_cpp`](src/example_app_cpp/) | `ament_cmake` | C++ | `camera_subscriber`, `cmd_vel_publisher` |

Both templates are minimal but real: colcon-buildable and `ament_lint`-clean.
Copy one, rename it, and replace the node bodies with your own logic.

## Topics

The table lists the node defaults. If your scene uses another camera namespace, set `camera_topic` to its image topic (for example, `/jetbot/camera/color/image_raw` for the Jetbot integration scene).

| Direction | Topic | Type | ROS 2 parameter |
|---|---|---|---|
| Isaac -> app (inbound) | `/camera_bot/camera/color/image_raw` | `sensor_msgs/Image` | `camera_topic` |
| app -> Isaac (outbound) | `/cmd_vel` | `geometry_msgs/Twist` | `cmd_vel_topic` |

## Prerequisites

- Docker (the example is exercised inside the official `ros:humble` image;
  you do not need a host ROS 2 install).

## Build

Run from this directory (`example/ros2/`):

```bash
docker run --rm -v "$PWD":/ws -w /ws ros:humble \
  bash -c 'source /opt/ros/humble/setup.bash && colcon build'
```

`colcon` discovers both packages under `src/` and builds them. Artifacts
land in `build/`, `install/`, `log/` (all gitignored).

## Lint and test

`ament_lint` runs through `colcon test` (the standard ROS 2 path):

```bash
docker run --rm -v "$PWD":/ws -w /ws ros:humble bash -c '
  source /opt/ros/humble/setup.bash &&
  colcon build &&
  colcon test &&
  colcon test-result --all'
```

A clean run reports `0 errors, 0 failures` (the C++ `cppcheck` linter is
skipped because the optional tool is not in the base image -- that is a
skip, not a failure).

## Run with an Isaac scene

Start a scene that publishes camera images and subscribes to velocity commands on the same DDS domain as these nodes. With the default topics, run:

```bash
docker run --rm --net=host -v "$PWD":/ws -w /ws ros:humble bash -c '
  source /opt/ros/humble/setup.bash &&
  source install/setup.bash &&
  ros2 run example_app_py camera_subscriber'
```

You should see one `[FRAME OK]` log line per received camera frame. In
another container, publish motion:

```bash
docker run --rm --net=host -v "$PWD":/ws -w /ws ros:humble bash -c '
  source /opt/ros/humble/setup.bash &&
  source install/setup.bash &&
  ros2 run example_app_py cmd_vel_publisher'
```

Each `[CMD_VEL OK]` line reports a Twist published by the node. The C++ package uses the same parameters:
`ros2 run example_app_cpp camera_subscriber` /
`ros2 run example_app_cpp cmd_vel_publisher`.

CI checks these templates with `colcon build` and `ament_lint` in the hosted ROS container.

## Make it yours

1. Copy `src/example_app_py` or `src/example_app_cpp` to your own name.
2. Rename the package: the directory, the `name` in `package.xml`, and
   (Python) `package_name` in `setup.py` / the inner module directory, or
   (C++) `project()` in `CMakeLists.txt`.
3. Set `camera_topic` and `cmd_vel_topic` to the topics used by your scene.
4. Replace the node bodies with your application logic.

## License

Apache-2.0. See [LICENSE](../../LICENSE).

## Translations

- [English](README.md)
- [繁體中文](README.zh-TW.md)
- [简体中文](README.zh-CN.md)
- [日本語](README.ja.md)
