"""Measure Jetbot wheel motion through IsaacDriver.run() for issue #447."""

import argparse
import math
import sys
from pathlib import Path

WHEEL_JOINTS = ["left_wheel_joint", "right_wheel_joint"]
COMMAND_RAD_S = 10.0


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--robot-usd", required=True)
    parser.add_argument("--engine", choices=["physx", "newton"], required=True)
    args = parser.parse_args()
    if not Path(args.robot_usd).is_file():
        sys.exit(f"--robot-usd must point to an existing file, got {args.robot_usd!r}")
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "framework"))

    from isaac_devkit.driver import IsaacDriver  # noqa: E402

    class _Driver(IsaacDriver):
        USD = args.robot_usd
        BOOT_EXTENSIONS = (
            "omni.graph.action",
            "isaacsim.core.nodes",
            "isaacsim.sensors.physics.nodes",
        )

        def _open_stage(self):
            import omni.kit.app
            import omni.usd
            from pxr import Gf, PhysxSchema, UsdGeom, UsdPhysics

            if args.engine == "newton":
                extensions = omni.kit.app.get_app().get_extension_manager()
                extensions.set_extension_enabled_immediate("isaacsim.physics.newton", True)
                self._app.update()
                from isaacsim.physics.newton import (
                    MuJoCoSolverConfig, NewtonConfig, configure_newton,
                )

                configure_newton(NewtonConfig(
                    num_substeps=10, physics_frequency=60.0,
                    solver_cfg=MuJoCoSolverConfig(),
                ))
                self._app.update()
                extensions.set_extension_enabled_immediate(
                    "isaacsim.physics.newton.tensors", True,
                )
                self._app.update()

            ctx = omni.usd.get_context()
            ctx.new_stage()
            self._app.update()
            stage = ctx.get_stage()
            UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
            UsdGeom.SetStageMetersPerUnit(stage, 1.0)
            stage.SetTimeCodesPerSecond(60.0)
            scene = UsdPhysics.Scene.Define(stage, "/physicsScene")
            PhysxSchema.PhysxSceneAPI.Apply(scene.GetPrim()).CreateTimeStepsPerSecondAttr(60)
            ground = UsdGeom.Cube.Define(stage, "/ground")
            ground.GetSizeAttr().Set(1.0)
            transform = UsdGeom.XformCommonAPI(ground)
            transform.SetScale(Gf.Vec3f(60, 60, 0.1))
            transform.SetTranslate(Gf.Vec3d(0, 0, -0.05))
            UsdPhysics.CollisionAPI.Apply(ground.GetPrim())
            robot = stage.DefinePrim("/Robot", "Xform")
            robot.GetReferences().AddReference(self.USD)
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
                        ("art.inputs:velocityCommand", [0.0, 0.0]),
                        ("read.inputs:prim", [usdrt.Sdf.Path("/Robot")]),
                    ],
                },
            )

        def main(self):
            import omni.graph.core as og
            from isaacsim.core.simulation_manager import SimulationManager

            active_engine = SimulationManager.get_active_physics_engine()
            for _ in range(5):
                self._app.update()

            names = list(og.Controller.attribute("/DriveGraph/read.outputs:jointNames").get())
            wheel_indices = [names.index(joint) for joint in WHEEL_JOINTS]
            positions = og.Controller.attribute("/DriveGraph/read.outputs:jointPositions")

            def wheel_positions():
                values = positions.get()
                return [float(values[index]) for index in wheel_indices]

            previous = wheel_positions()
            og.Controller.attribute("/DriveGraph/art.inputs:velocityCommand").set(
                [COMMAND_RAD_S, COMMAND_RAD_S]
            )
            displacement = [0.0, 0.0]
            for _ in range(180):
                self._app.update()
                current = wheel_positions()
                for i in range(len(WHEEL_JOINTS)):
                    # PhysX wraps revolute joint positions as the wheels turn.
                    displacement[i] += math.remainder(current[i] - previous[i], math.tau)
                previous = current

            left, right = displacement
            print(f"[WHEEL MOTION] {active_engine} {left} {right}", flush=True)

    _Driver().run()


if __name__ == "__main__":
    _main()
