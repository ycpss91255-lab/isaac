"""Apply a runtime drive to a USD revolute joint and report its authored gains."""

import argparse
import sys
from pathlib import Path


def _read_angular_drive(stage, joint_path):
    """Read (has_drive, stiffness, damping) from a joint's angular DriveAPI."""
    from pxr import UsdPhysics

    prim = stage.GetPrimAtPath(joint_path)
    drive = UsdPhysics.DriveAPI(prim, "angular")
    if not drive:
        return (False, float("nan"), float("nan"))
    stiffness_attr = drive.GetStiffnessAttr()
    damping_attr = drive.GetDampingAttr()
    stiffness = stiffness_attr.Get() if stiffness_attr else None
    damping = damping_attr.Get() if damping_attr else None
    return (
        True,
        float(stiffness) if stiffness is not None else float("nan"),
        float(damping) if damping is not None else float("nan"),
    )


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--stiffness", type=float, default=800.0)
    parser.add_argument("--damping", type=float, default=40.0)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    framework_dir = repo_root / "framework"
    if str(framework_dir) not in sys.path:
        sys.path.insert(0, str(framework_dir))

    from _kit_boot import time_kit_boot

    with time_kit_boot() as SimulationApp:
        app = SimulationApp({"headless": True})
    try:
        import omni.usd
        from pxr import UsdPhysics

        from isaac_devkit.usd_model import apply_joint_drive

        context = omni.usd.get_context()
        context.new_stage()
        stage = context.get_stage()
        joint_path = "/Robot/hinge"
        UsdPhysics.RevoluteJoint.Define(stage, joint_path)
        if not apply_joint_drive(joint_path, args.stiffness, args.damping):
            raise RuntimeError(f"apply_joint_drive returned falsy for {joint_path}")

        has_drive, stiffness, damping = _read_angular_drive(stage, joint_path)
        print(
            f"[DRIVE SUMMARY] joint={joint_path} "
            f"has_drive={has_drive} stiffness={stiffness:g} "
            f"damping={damping:g}",
            flush=True,
        )
        print("[EXIT CLEAN]", flush=True)
    except Exception as exc:  # noqa: BLE001
        import traceback

        print(f"[RAISED] {type(exc).__name__}: {exc}", flush=True)
        print("[TRACEBACK]\n" + traceback.format_exc(), flush=True)
        raise
    finally:
        app.close()


if __name__ == "__main__":
    _main()
