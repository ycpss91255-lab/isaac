"""Kit-side runner for the ISAAC_IO_PLUGIN integration test (isaac#423).

Boots ``IsaacDriver`` with its default extensions. Once the timeline is
playing, ``main()`` reports the configured tuple (``[BOOT_EXT]``), whether the
plugin marker exists (``[MARKER_PRIM]``), and the sorted list of loaded
``rclpy`` and ``isaacsim.ros2*`` modules (``[ROS_MODULES]``).
"""

import argparse
import sys


def loaded_ros_modules():
    """List the client and bridge modules currently loaded in this process."""
    return sorted(
        name for name in sys.modules
        if name == "rclpy" or name.startswith(("rclpy.", "isaacsim.ros2"))
    )


def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script-dir", required=True)
    parser.add_argument("--usd-path", required=True)
    args = parser.parse_args()

    sys.path.insert(0, args.script_dir)

    from isaac_devkit.driver import IsaacDriver  # noqa: E402

    usd_path = args.usd_path

    class _Driver(IsaacDriver):
        USD = usd_path

        def main(self) -> None:
            import omni.usd

            print(f"[BOOT_EXT] {type(self).BOOT_EXTENSIONS!r}", flush=True)
            stage = omni.usd.get_context().get_stage()
            root = stage.GetDefaultPrim().GetPath()
            marker = stage.GetPrimAtPath(f"{root}/io_plugin_marker")
            print(f"[MARKER_PRIM] {bool(marker and marker.IsValid())}",
                  flush=True)
            print(f"[ROS_MODULES] {loaded_ros_modules()}", flush=True)
            self._should_quit = True

    _Driver().run()


if __name__ == "__main__":
    _main()
