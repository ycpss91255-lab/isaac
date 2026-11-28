"""Kit-side runner for the OutputHub GPU delivery test (isaac#365).

Run with Isaac's python:

    /isaac-sim/python.sh _output_hub_runner.py \\
        --repo-root <repo> --robot-usd <official jetbot.usd>

Builds a ground + the official Jetbot, adds a camera, IMU and two lidars,
calls ``setup_output`` in python mode, registers one callback per kind,
steps the app and prints marker lines (Kit's ``app.close`` calls
``_exit(0)``, so the test asserts on markers, not the exit code):

    [HUB RGB] count=N dtype=... shape=...
    [HUB DEPTH] count=N dtype=... shape=...
    [HUB JOINT] count=N names=K
    [HUB IMU] count=N orientation_len=4
    [HUB LIDAR3D] count=N dtype=... shape=...
    [HUB LIDAR2D] count=N dtype=... shape=... angles_dtype=... angles_shape=...
    [HUB EXIT CLEAN]
    [HUB RAISED] <exception>
"""

import argparse
import os
import sys
import time
from collections import Counter
from functools import partial
from pathlib import Path

_ROBOT = "/World/Robot"
_CHASSIS = f"{_ROBOT}/chassis"
_CAMERA = f"{_CHASSIS}/HubCam"
_IMU = f"{_CHASSIS}/HubImu"
_WIDTH, _HEIGHT = 640, 480
_STEPS = 300


def _build_stage(robot_usd):
    import omni.usd
    from pxr import Gf, UsdGeom, UsdLux, UsdPhysics

    omni.usd.get_context().new_stage()
    stage = omni.usd.get_context().get_stage()
    UsdGeom.Xform.Define(stage, "/World")
    UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    UsdLux.DistantLight.Define(stage, "/World/Sun").GetIntensityAttr().Set(
        3000.0
    )
    ground = UsdGeom.Cube.Define(stage, "/World/Ground")
    ground.GetSizeAttr().Set(1.0)
    xf = UsdGeom.Xformable(ground.GetPrim())
    xf.AddTranslateOp().Set(Gf.Vec3d(0, 0, -0.5))
    xf.AddScaleOp().Set(Gf.Vec3f(20, 20, 1))
    UsdPhysics.CollisionAPI.Apply(ground.GetPrim())
    stage.DefinePrim(_ROBOT).GetReferences().AddReference(robot_usd)
    cam = UsdGeom.Camera.Define(stage, _CAMERA)
    UsdGeom.Xformable(cam.GetPrim()).AddTranslateOp().Set(
        Gf.Vec3d(0.0, 0.0, 0.5)
    )
    return stage


def _array_shape(array):
    return "x".join(map(str, array.shape))


def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--robot-usd", required=True)
    args = parser.parse_args()

    os.environ["ISAAC_LIVESTREAM"] = "0"
    os.environ["ISAAC_OUTPUT_MODE"] = "python"
    sys.path.insert(0, str(Path(args.repo_root).resolve() / "framework"))
    from _kit_boot import time_kit_boot

    try:
        from isaac_devkit.output import (
            CameraOutput,
            ImuOutput,
            JointOutput,
            Lidar2dOutput,
            Lidar3dOutput,
            setup_output,
        )
        from isaac_devkit.sensors import load_config, setup_sensor

        with time_kit_boot() as SimulationApp:
            app = SimulationApp({
                "headless": True,
                "extra_args": [
                    "--enable", "isaacsim.core.nodes",
                    "--enable", "isaacsim.sensors.experimental.physics",
                ],
            })
        import omni.timeline
        from isaacsim.sensors.experimental.physics import IMU

        stage = _build_stage(args.robot_usd)
        for _ in range(10):
            app.update()
        IMU.create(_IMU)
        config_dir = Path(args.repo_root) / "src/config/lidar"
        cloud = load_config(config_dir / "ouster_os1.yaml")
        scan = load_config(config_dir / "example_rotary_2d.yaml")
        for config in (cloud, scan):
            config["mount"]["parent_prim"] = _CHASSIS
        # Aim part of the planar scan at the ground for a repeatable return.
        scan["mount"]["pose"]["rpy"] = [0, 15, 0]

        out = setup_output(
            cameras=[
                CameraOutput("hub_rgb", _CAMERA, _WIDTH, _HEIGHT),
                CameraOutput("hub_depth", _CAMERA, _WIDTH, _HEIGHT, True),
            ],
            joint=JointOutput(_CHASSIS),
            imu=ImuOutput("hub_imu", _IMU),
            lidars_3d=[Lidar3dOutput("hub_cloud", setup_sensor(cloud, stage))],
            lidars_2d=[Lidar2dOutput("hub_scan", setup_sensor(scan, stage))],
        )
        counts = Counter()
        latest = {}

        def record(kind, frame):
            assert frame.kind == kind
            # Between scans a lidar may have no returns on this tick.
            if kind == "lidar_3d" and frame.data.size == 0:
                return
            if kind == "lidar_2d" and frame.data["ranges"].size == 0:
                return
            counts[kind] += 1
            latest[kind] = frame.data

        kinds = ("rgb", "depth", "joint_state", "imu", "lidar_3d", "lidar_2d")
        for kind in kinds:
            out.register(partial(record, kind), kinds=[kind])
        omni.timeline.get_timeline_interface().play()
        for _ in range(_STEPS):
            app.update()
            out.step(time.monotonic())

        for tag, kind in (
            ("RGB", "rgb"), ("DEPTH", "depth"), ("LIDAR3D", "lidar_3d"),
        ):
            if counts[kind]:
                data = latest[kind]
                print(f"[HUB {tag}] count={counts[kind]} dtype={data.dtype} "
                      f"shape={_array_shape(data)}", flush=True)
            else:
                print(f"[HUB {tag}] count=0", flush=True)
        if counts["lidar_2d"]:
            ranges = latest["lidar_2d"]["ranges"]
            angles = latest["lidar_2d"]["angles"]
            print(
                f"[HUB LIDAR2D] count={counts['lidar_2d']} "
                f"dtype={ranges.dtype} shape={_array_shape(ranges)} "
                f"angles_dtype={angles.dtype} "
                f"angles_shape={_array_shape(angles)}",
                flush=True,
            )
        else:
            print("[HUB LIDAR2D] count=0", flush=True)
        joint_count = counts["joint_state"]
        names = len(latest["joint_state"]["names"]) if joint_count else 0
        print(f"[HUB JOINT] count={joint_count} names={names}", flush=True)
        olen = len(latest["imu"]["orientation"]) if counts["imu"] else 0
        print(f"[HUB IMU] count={counts['imu']} orientation_len={olen}",
              flush=True)
        print("[HUB EXIT CLEAN]", flush=True)
        app.close()
    except Exception as exc:  # noqa: BLE001 -- surfaced as a marker
        import traceback

        traceback.print_exc()
        print(f"[HUB RAISED] {type(exc).__name__}: {exc}", flush=True)


if __name__ == "__main__":
    _main()
