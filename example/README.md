# example/ -- the base-repo running example (onboarding walkthrough)

This directory is the single runnable example the base repo ships, and it
doubles as the scaffold template (ADR-0017). It is what a newcomer or an
agent is handed to get from zero to a live camera topic and then to their
own robot, **without reading framework source**.

- [`sim/`](sim/) -- the Isaac side: the `camera_bot` USD, the three-file
  scene, the per-sensor `custom.yaml`, and `example_driver.py` (publishes a
  camera stream, drives a chassis from `/cmd_vel`).
- [`ros2/`](ros2/) -- the app side: minimal ROS 2 packages that subscribe
  to the camera and publish `/cmd_vel`. See [`ros2/README.md`](ros2/README.md).

## Onboarding walkthrough (the M5 path)

The onboarding success metric is: scaffold a workspace, run it, swap the
robot, swap a sensor -- all by editing files in this `example/`, never by
reading `framework/` source. The three tasks below walk that path.

### 1. First topic (scaffold -> run)

The `new-workspace.sh` scaffold was removed (#326); from this repo's root:

```bash
just setup && just build && just run
```

`just run` boots the example driver; the camera topic
`/camera_bot/camera/color/image_raw` appears. Confirm it from a sibling ROS
2 container:

```bash
docker run --rm --net=host ros:humble bash -c '
  source /opt/ros/humble/setup.bash &&
  ros2 topic echo --once /camera_bot/camera/color/image_raw'
```

That first frame is the M1 "time-to-first-topic" milestone.

### 2. Swap in your own robot USD

The example loads [camera_bot.usd](sim/model/usd/robot/camera_bot/camera_bot.usd). To use your own robot:

1. Produce its USD with [asset_converter](https://github.com/ycpss91255-lab/asset_converter) and place it under `sim/model/usd/robot/`, together with any referenced assets.
2. In [sim/scene/robot.yaml](sim/scene/robot.yaml), set `robot.model` to the USD path relative to `sim/` and set `robot.name`. The example driver expects a `base_link` chassis. Set the camera's `link` to its mount on the robot.

`just run` again -- your robot boots, still publishing the camera topic.

### 3. Swap a sensor (in scope)

The camera is configured by the per-sensor YAML
[`sim/config/sensor/custom.yaml`](sim/config/sensor/custom.yaml). All of
these are in-scope edits -- change the file, re-run, no framework code:

- **Resolution / fps**: edit `sensors[0].resolution` (e.g. `[640, 480]`)
  or `sensors[0].fps`.
- **Topic override**: change `ros.topic_prefix` (the published topic and
  the matching subscriber in `ros2/` follow it).
- **Add a second camera**: append another entry under `sensors:` with a new
  `name` and its own `resolution` / `fov`; each entry yields its own
  `UsdGeom.Camera` and its own image topic.

## Out of scope / not yet implemented

The schema shape is locked from day one, but the framework only implements
the subset the example uses (ADR-0017, decision C: "interface frozen,
implementation grows"). Adding a **lidar** or **imu** sensor is an
**intentional out-of-scope boundary**: the host-side YAML validation
accepts those categories, but the Isaac-side build path **raises
`NotImplementedError`** until a real need lands it. This is by design, not a
bug -- it is the documented edge of the in-scope sensor swap above.

| Sensor swap | Status |
|---|---|
| camera resolution / fps / topic override / second camera | in scope (works today) |
| **lidar** / **imu** sensor category | **out of scope -- raises `NotImplementedError`** |
| ZED X stereo (`type: zed`) | out of scope -- raises `NotImplementedError` (needs the Stereolabs extension) |

If you need lidar or imu, that is a framework feature request (file an
issue), not something to unblock by editing `framework/` source as part of
onboarding.

## License

Apache-2.0. See [LICENSE](../LICENSE).

## Translations

- [English](README.md)
- [繁體中文](README.zh-TW.md)
- [简体中文](README.zh-CN.md)
- [日本語](README.ja.md)
