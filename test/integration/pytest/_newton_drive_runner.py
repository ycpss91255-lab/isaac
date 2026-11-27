"""Kit-side runner: IsaacDriver + official Jetbot, velocity command, per engine (isaac#447).

Not a pytest test (leading underscore). Builds a ground + the Jetbot on a
new stage (engine first, as Newton needs), drives both wheels with an
OmniGraph ``IsaacArticulationController`` at a constant velocity and prints
marker lines (Kit's ``app.close`` swallows the exit code)::

    [DRIVE ENGINE] active=<physx|newton>
    [DRIVE SETTINGS] rate_limit_enabled=<bool> rate_limit_hz=<float> fixed_step=<bool> looping=<bool|None>
    [DRIVE WHEELS] left=<float> right=<float> delta_rad=<float>
    [DRIVE CLOCK] sim_hz=<float> wall_hz=<float> monotonic=<bool> span_s=<float> updates=<int>

Usage (inside the GPU container)::

    /isaac-sim/python.sh _newton_drive_runner.py --script-dir <repo>/framework \
        --robot-usd <jetbot.usd> --engine physx|newton
"""

import argparse
import sys
import time
from pathlib import Path

WHEEL_JOINTS = ["left_wheel_joint", "right_wheel_joint"]
COMMAND_RAD_S = 10.0
RUN_WALL_SECONDS = 6.0


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script-dir", required=True)
    parser.add_argument("--robot-usd", required=True)
    parser.add_argument("--engine", choices=["physx", "newton"], required=True)
    args = parser.parse_args()
    if not Path(args.robot_usd).is_file():
        sys.exit(f"--robot-usd must point to an existing file, got {args.robot_usd!r}")
    sys.path.insert(0, args.script_dir)

    from isaac_devkit.driver import IsaacDriver  # noqa: E402

    engine = args.engine
    robot_usd = args.robot_usd

    class _Driver(IsaacDriver):
        USD = robot_usd
        BOOT_EXTENSIONS = ("omni.graph.action", "isaacsim.core.nodes", "isaacsim.sensors.physics.nodes")

        def _launcher_args(self):
            # Joint-state readback needs no camera or livestream.
            return {"headless": True, "livestream": 0, "enable_cameras": False}

        def _open_stage(self):
            import omni.kit.app
            import omni.usd
            from pxr import Gf, PhysxSchema, UsdGeom, UsdPhysics

            if engine == "newton":
                mgr = omni.kit.app.get_app().get_extension_manager()
                mgr.set_extension_enabled_immediate(
                    "isaacsim.physics.newton", True)
                self._app.update()
                from isaacsim.physics.newton import (
                    MuJoCoSolverConfig, NewtonConfig, configure_newton)
                configure_newton(NewtonConfig(
                    num_substeps=10, physics_frequency=60.0,
                    solver_cfg=MuJoCoSolverConfig()))
                self._app.update()
                mgr.set_extension_enabled_immediate(
                    "isaacsim.physics.newton.tensors", True)
                self._app.update()
            ctx = omni.usd.get_context()
            ctx.new_stage()
            self._app.update()
            stage = ctx.get_stage()
            UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
            UsdGeom.SetStageMetersPerUnit(stage, 1.0)
            stage.SetTimeCodesPerSecond(60.0)
            UsdPhysics.Scene.Define(stage, "/physicsScene")
            PhysxSchema.PhysxSceneAPI.Apply(
                stage.GetPrimAtPath("/physicsScene")
            ).CreateTimeStepsPerSecondAttr().Set(60)
            ground = UsdGeom.Cube.Define(stage, "/ground")
            ground.GetSizeAttr().Set(1.0)
            UsdGeom.XformCommonAPI(ground).SetScale(Gf.Vec3f(60, 60, 0.1))
            UsdGeom.XformCommonAPI(ground).SetTranslate(
                Gf.Vec3d(0, 0, -0.05))
            UsdPhysics.CollisionAPI.Apply(ground.GetPrim())
            robot = stage.DefinePrim("/Robot", "Xform")
            robot.GetReferences().AddReference(robot_usd)
            stage.SetDefaultPrim(robot)
            for _ in range(60):
                self._app.update()
            return stage

        def setup(self, stage):
            import omni.graph.core as og
            import usdrt.Sdf

            og.Controller.edit(
                {"graph_path": "/DriveGraph", "evaluator_name": "execution"},
                {
                    og.Controller.Keys.CREATE_NODES: [
                        ("tick", "omni.graph.action.OnPlaybackTick"),
                        ("read", "isaacsim.sensors.physics.IsaacReadJointState"),
                        ("art", "isaacsim.core.nodes.IsaacArticulationController"),
                    ],
                    og.Controller.Keys.CONNECT: [
                        ("tick.outputs:tick", "read.inputs:execIn"),
                        ("tick.outputs:tick", "art.inputs:execIn"),
                    ],
                    og.Controller.Keys.SET_VALUES: [
                        ("art.inputs:robotPath", "/Robot"),
                        ("art.inputs:jointNames", WHEEL_JOINTS),
                        ("art.inputs:velocityCommand",
                         [COMMAND_RAD_S, COMMAND_RAD_S]),
                        ("read.inputs:prim", [usdrt.Sdf.Path("/Robot")]),
                    ],
                },
            )

        def main(self):
            import carb.settings
            import omni.graph.core as og
            import omni.timeline

            try:
                import isaacsim.physics.newton as nw
                active = nw.get_active_physics_engine()
            except Exception:  # noqa: BLE001 - physx-only image
                active = "physx"
            print(f"[DRIVE ENGINE] active={active}", flush=True)

            timeline = omni.timeline.get_timeline_interface()
            settings = carb.settings.get_settings()
            rate_limit_enabled = settings.get("/app/runLoops/main/rateLimitEnabled")
            rate_limit_hz = settings.get("/app/runLoops/main/rateLimitFrequency")
            fixed_step = settings.get("/app/player/useFixedTimeStepping")
            is_looping = getattr(timeline, "is_looping", None)
            looping = is_looping() if callable(is_looping) else None
            print(
                f"[DRIVE SETTINGS] rate_limit_enabled={rate_limit_enabled} "
                f"rate_limit_hz={rate_limit_hz} fixed_step={fixed_step} looping={looping}",
                flush=True)

            joints = og.Controller.attribute("/DriveGraph/read.outputs:jointNames")
            positions = og.Controller.attribute(
                "/DriveGraph/read.outputs:jointPositions")

            def wheel_pos():
                names = list(joints.get())
                values = list(positions.get())
                return tuple(values[names.index(j)] for j in WHEEL_JOINTS)

            for _ in range(5):
                self._app.update()
            left_start, right_start = wheel_pos()
            times = []
            wall0 = time.monotonic()
            while time.monotonic() - wall0 < RUN_WALL_SECONDS:
                self._app.update()
                times.append(timeline.get_current_time())
            wall = time.monotonic() - wall0
            left_end, right_end = wheel_pos()
            left = left_end - left_start
            right = right_end - right_start
            span_s = times[-1] - times[0]
            sim_hz = (len(times) - 1) / span_s if span_s > 0 else 0.0
            monotonic = all(b >= a for a, b in zip(times, times[1:]))
            print(
                f"[DRIVE WHEELS] left={left:.4f} right={right:.4f} "
                f"delta_rad={abs(left) + abs(right):.4f}", flush=True)
            print(
                f"[DRIVE CLOCK] sim_hz={sim_hz:.2f} wall_hz={len(times) / wall:.2f} "
                f"monotonic={monotonic} span_s={span_s:.3f} "
                f"updates={len(times)}",
                flush=True)
            self._should_quit = True

    _Driver().run()


if __name__ == "__main__":
    _main()
