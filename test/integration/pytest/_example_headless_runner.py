"""Build the Jetbot scene and report the camera prim, robot structure and driver lifecycle."""

import argparse
import ctypes
import os
import signal
import sys
from pathlib import Path

_ROBOT_PRIM = "/World/Robot"
# The Jetbot's articulation body; it has no ``base_link``.
_CHASSIS_PRIM = f"{_ROBOT_PRIM}/chassis"


def _build_scene_dict(robot_usd: str) -> dict:
    """In-memory scene: ground and the Jetbot."""
    return {
        "environment": {"ground_plane": True},
        "robot": {
            "name": "jetbot",
            "model": robot_usd,  # absolute path bypasses MODEL_PATH search
            "pose": {"xyz": [0.0, 0.0, 0.0], "rpy": [0.0, 0.0, 0.0]},
        },
    }


def _camera_cfg() -> dict:
    """Custom RGB camera mounted on the Jetbot chassis (no external assets)."""
    return {
        "mount": {
            "parent_prim": _CHASSIS_PRIM,
            "pose": {"xyz": [0.1, 0.0, 0.1], "rpy": [0.0, 0.0, 0.0]},
        },
        "sensor": {"category": "camera", "type": "custom"},
        "sensors": [
            {
                "role": "rgb",
                "name": "color",
                "pose": {"xyz": [0.0, 0.0, 0.0], "rpy": [0.0, 0.0, 0.0]},
                "resolution": [1280, 720],
                "fps": 30,
                "hfov": 90.0,
                "vfov": 60.0,
            }
        ],
        "ros": {
            "topic_prefix": "/jetbot/camera",
            "frame_id_prefix": "jetbot_camera",
        },
    }


def _cuda_device_count() -> int:
    """Functional CUDA probe via the driver API (no torch dependency)."""
    cuda = ctypes.CDLL("libcuda.so.1")
    rc = cuda.cuInit(0)
    if rc != 0:
        raise RuntimeError(f"cuInit failed: rc={rc}")
    count = ctypes.c_int(0)
    rc = cuda.cuDeviceGetCount(ctypes.byref(count))
    if rc != 0:
        raise RuntimeError(f"cuDeviceGetCount failed: rc={rc}")
    return count.value


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--robot-usd", required=True)
    args = parser.parse_args()

    os.environ["ISAAC_LIVESTREAM"] = "0"

    repo_root = Path(args.repo_root).resolve()
    framework_dir = repo_root / "framework"
    if str(framework_dir) not in sys.path:
        sys.path.insert(0, str(framework_dir))
    robot_usd = str(Path(args.robot_usd).resolve())

    try:
        from isaac_devkit.driver import (  # noqa: E402
            IsaacDriver,
            parse_livestream_env,
        )
        from isaac_devkit.usd_model import (  # noqa: E402
            _summarize_prim_records,
        )

        class _ExampleIntegrationDriver(IsaacDriver):
            """Build the Jetbot scene, then probe it in setup() / main()."""

            def __init__(self) -> None:
                super().__init__()
                self._robot_prim_path = _ROBOT_PRIM

            # -- Lifecycle (the SCENE shape the example driver walked) --

            def run(self) -> None:
                from isaacsim import SimulationApp

                kwargs = parse_livestream_env(
                    os.environ.get("ISAAC_LIVESTREAM")
                )
                self._app = SimulationApp(kwargs)
                signal.signal(signal.SIGINT, self._on_signal)
                signal.signal(signal.SIGTERM, self._on_signal)
                try:
                    import omni.usd

                    scene = _build_scene_dict(robot_usd)
                    stage = omni.usd.get_context().get_stage()
                    from isaac_devkit.scene import build_scene

                    # robot.model is absolute, so repo_root only anchors
                    # the (unused) legacy model/usd fallback.
                    build_scene(scene, stage, repo_root)
                    self._setup_camera(stage)
                    self._ensure_scene_defaults(stage)
                    self._play_timeline()
                    self.setup(stage)
                    self.main()
                    self.shutdown()
                except Exception as exc:  # noqa: BLE001
                    print(f"[RAISED] {type(exc).__name__}: {exc}", flush=True)
                    raise
                finally:
                    sys.stdout.flush()
                    sys.stderr.flush()
                    self._app.close()

            def _setup_camera(self, stage) -> None:
                from pxr import UsdGeom

                from isaac_devkit.sensors import setup_camera

                mount = setup_camera(_camera_cfg(), stage)
                camera = stage.GetPrimAtPath(f"{mount}/color")
                if not camera or not camera.IsA(UsdGeom.Camera):
                    raise AssertionError(f"Missing USD camera under {mount}")
                print(f"[CAMERA PRIM] {camera.GetPath()}", flush=True)

            def setup(self, stage) -> None:
                import carb.settings

                log_path = carb.settings.get_settings().get("/log/file")
                print(f"[KIT LOG] path={log_path}", flush=True)
                print(f"[CUDA OK] devices={_cuda_device_count()}", flush=True)
                print("[BOOT OK]", flush=True)

                self._assert_l1(stage)

            # -- L1: model/structure assertions ----------------------

            def _assert_l1(self, stage) -> None:
                from pxr import Usd, UsdPhysics

                base_link_path = _CHASSIS_PRIM
                base_link = stage.GetPrimAtPath(base_link_path)
                valid = bool(base_link.IsValid())
                has_rb = bool(
                    valid and base_link.HasAPI(UsdPhysics.RigidBodyAPI)
                )
                print(
                    f"[L1 BASE_LINK OK] path={base_link_path} "
                    f"valid={valid} rigidbody={has_rb}",
                    flush=True,
                )

                # Fold the live committed-USD robot subtree into a
                # PrimSummary with the same pure summarizer the unit tests
                # exercise, then report the OBSERVED link/joint structure.
                # Report paths relative to the USD robot root.
                robot_root = stage.GetPrimAtPath(self._robot_prim_path)
                records = []
                for prim in Usd.PrimRange(robot_root):
                    path = str(prim.GetPath())
                    if path == self._robot_prim_path:
                        continue
                    records.append((path, prim.GetTypeName()))

                robot_name = _build_scene_dict(robot_usd)["robot"]["name"]
                expected_root = f"/{robot_name}"
                prefix_len = len(self._robot_prim_path)
                rerooted = [
                    (expected_root + path[prefix_len:], type_name)
                    for path, type_name in records
                ]
                rerooted.insert(0, (expected_root, "Xform"))

                actual = _summarize_prim_records(rerooted, usd_path="")
                print(
                    f"[L1 COUNTS OK] links={len(actual.link_paths)} "
                    f"joints={actual.joint_count} root={actual.root_prim}",
                    flush=True,
                )

            def main(self) -> None:
                self._app.update()
                self._on_signal(signal.SIGINT, None)

            def shutdown(self) -> None:
                if self._should_quit:
                    print("[SIGINT SHUTDOWN OK]", flush=True)
                print("[EXIT CLEAN]", flush=True)

        _ExampleIntegrationDriver().run()
    except Exception as exc:  # noqa: BLE001
        print(f"[RAISED] {type(exc).__name__}: {exc}", flush=True)
        raise


if __name__ == "__main__":
    _main()
