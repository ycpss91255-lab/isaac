"""Observe the stage and timeline while the default driver's own loop ticks."""

import json
import sys
from pathlib import Path
from unittest.mock import patch


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "framework"))
    from isaac_devkit import run_scene
    from isaac_devkit.default_driver import DefaultSceneDriver

    default_main = DefaultSceneDriver.main

    def observe_main(driver):
        import omni.timeline
        import omni.usd

        stage = omni.usd.get_context().get_stage()
        prim = stage.GetDefaultPrim()
        timeline = omni.timeline.get_timeline_interface()
        start = timeline.get_current_time()
        update = driver._app.update
        ticks = 0

        def observed_update():
            nonlocal ticks
            update()
            ticks += 1
            if ticks == 20:
                driver._should_quit = True

        with patch.object(driver._app, "update", observed_update):
            default_main(driver)

        report = {
            "usd": stage.GetRootLayer().realPath,
            "default_prim": str(prim.GetPath()) if prim.IsValid() else None,
            "updates": ticks,
            "playing": timeline.is_playing(),
            "start": start,
            "end": timeline.get_current_time(),
            "ros_modules": sorted(
                name for name in sys.modules
                if name == "rclpy" or name.startswith(("rclpy.", "isaacsim.ros2"))
            ),
        }
        # Kit can exit with status zero in app.close() even after a failure.
        print("[SCENE] " + json.dumps(report), flush=True)

    with patch.object(DefaultSceneDriver, "main", observe_main):
        run_scene.main(sys.argv[1:])


if __name__ == "__main__":
    main()
