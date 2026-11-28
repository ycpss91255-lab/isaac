"""Boot a headless driver and report the USD camera prims built from its YAML."""

import argparse
import ctypes
import os
import sys
from pathlib import Path


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
    parser.add_argument("--script-dir", required=True)
    parser.add_argument("--camera-yaml", required=True)
    parser.add_argument("--usd-path", required=True)
    args = parser.parse_args()

    os.environ["ISAAC_LIVESTREAM"] = "0"

    # Self-resolve the sibling framework from the repo root so
    # ``import isaac_devkit`` (which isaac_driver re-exports from) works
    # regardless of the container mount layout. The base env_8 sets
    # PYTHONPATH=~/work/framework, but that does not resolve when the repo
    # is mounted as a NESTED worktree (its framework/ is not at
    # ~/work/framework) -- isaac#134. ``--script-dir`` is <repo>/src/script,
    # so its parents[1] is the repo root; mirror the #132 example runner's
    # self-resolution. The driver path stays first on sys.path.
    script_dir = Path(args.script_dir).resolve()
    framework_dir = script_dir.parents[1] / "framework"
    if framework_dir.is_dir() and str(framework_dir) not in sys.path:
        sys.path.insert(0, str(framework_dir))
    sys.path.insert(0, str(script_dir))

    try:
        from isaac_driver import IsaacDriver  # noqa: E402

        usd_path = args.usd_path
        camera_yaml = args.camera_yaml

        class _CameraSmokeDriver(IsaacDriver):
            USD = usd_path

            # Exercise camera creation without boot-time extensions.
            BOOT_EXTENSIONS = ()

            def setup(self, stage) -> None:
                import carb.settings

                log_path = carb.settings.get_settings().get("/log/file")
                print(f"[KIT LOG] path={log_path}", flush=True)
                print(f"[CUDA OK] devices={_cuda_device_count()}", flush=True)
                print("[BOOT OK]", flush=True)

                from camera_setup import load_config, setup_camera
                from pxr import UsdGeom

                cfg = load_config(camera_yaml)
                mount = setup_camera(cfg, stage)
                for sensor in cfg["sensors"]:
                    camera = stage.GetPrimAtPath(f"{mount}/{sensor['name']}")
                    if not camera or not camera.IsA(UsdGeom.Camera):
                        raise AssertionError(f"Missing camera {sensor['name']} under {mount}")
                    print(f"[CAMERA PRIM] {camera.GetPath()}", flush=True)
                assert not stage.GetPrimAtPath("/World/CameraGraphs").IsValid()

            def main(self) -> None:
                self._app.update()

            def shutdown(self) -> None:
                print("[EXIT CLEAN]", flush=True)

        _CameraSmokeDriver().run()
    except Exception as exc:  # noqa: BLE001
        print(f"[RAISED] {type(exc).__name__}: {exc}", flush=True)
        raise


if __name__ == "__main__":
    _main()
