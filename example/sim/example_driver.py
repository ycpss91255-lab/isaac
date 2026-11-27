"""載入 camera_bot 場景、建立相機 prim，並執行指定次數的模擬更新。

在 Isaac 容器內執行::

    /isaac-sim/python.sh example/sim/example_driver.py
"""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path
from typing import Any, Dict

import yaml

# Resolve sibling framework on the host / in the container mount so
# ``import isaac_devkit`` works whether launched as a script or imported
# by a test. example/sim/example_driver.py -> parents[2] = repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_FRAMEWORK = _REPO_ROOT / "framework"
if str(_FRAMEWORK) not in sys.path:
    sys.path.insert(0, str(_FRAMEWORK))

from isaac_devkit.driver import IsaacDriver, parse_livestream_env  # noqa: E402

# Prim paths build_scene composes the scene under (scene.build_scene
# references the robot USD at /World/Robot).
_ROBOT_PRIM = "/World/Robot"


# ---------------------------------------------------------------------------
# Pure helpers (host-runnable, no Isaac Sim).
# ---------------------------------------------------------------------------


def load_three_file_scene(scene_path: Any) -> Dict[str, Any]:
    """Load scene.yaml and deep-merge its ``imports`` into one scene dict.

    The three-file scene (ADR-0017 section 4) is ``scene.yaml`` (the
    environment + ``imports`` of the other two) plus ``robot.yaml`` and
    ``object.yaml``. This reads ``scene.yaml``, resolves each ``imports``
    entry relative to the scene file, and shallow-merges the top-level
    keys of each imported fragment into the result (later files win on a
    key clash; the example's fragments hold disjoint keys ``robot`` /
    ``objects``).

    Pure: only filesystem + YAML, no Isaac. The returned dict is the
    shape used by scene construction and sensor placement.

    Args:
        scene_path: Path to ``scene.yaml``.

    Returns:
        The merged scene dict.

    Raises:
        FileNotFoundError: ``scene.yaml`` or an imported fragment is
            missing.
    """
    scene_file = Path(scene_path).expanduser().resolve()
    if not scene_file.exists():
        raise FileNotFoundError(f"scene file not found: {scene_file}")
    with scene_file.open() as f:
        merged: Dict[str, Any] = yaml.safe_load(f) or {}

    imports = merged.pop("imports", []) or []
    for rel in imports:
        frag_path = (scene_file.parent / rel).resolve()
        if not frag_path.exists():
            raise FileNotFoundError(
                f"imported scene fragment not found: {frag_path} "
                f"(from imports entry {rel!r} in {scene_file})"
            )
        with frag_path.open() as f:
            fragment = yaml.safe_load(f) or {}
        for key, value in fragment.items():
            merged[key] = value
    return merged


def expected_robot_prim_path(_scene: Dict[str, Any]) -> str:
    """Return the robot root prim path build_scene composes.

    Pure string computation (the L1 target the GPU assertions in #132
    check). ``build_scene`` references the robot USD under
    ``/World/Robot`` regardless of the robot's name.
    """
    return _ROBOT_PRIM


def expected_base_link_prim_path(scene: Dict[str, Any]) -> str:
    """Return the ``base_link`` prim path under the robot root (pure)."""
    return f"{expected_robot_prim_path(scene)}/base_link"


# ---------------------------------------------------------------------------
# Driver.
# ---------------------------------------------------------------------------


class ExampleDriver(IsaacDriver):
    """從三份 YAML 建立 camera_bot 場景並執行模擬迴圈。"""

    # Repo-relative three-file scene entry (resolved against the repo
    # root the framework anchors on).
    SCENE = "example/sim/scene/scene.yaml"

    def __init__(self) -> None:
        super().__init__()
        self._ticks: int = 0

    # -- Lifecycle (overrides IsaacDriver.run to the SCENE shape) ---------

    def run(self) -> None:
        """Walk the SCENE-driven lifecycle (ADR-0017 section 9 / PRD A2).

        Order matters: ``SimulationApp`` must be the first Isaac Sim
        construction; the signal handler override comes after (Kit
        installs its own SIGINT during construction). The seams
        (``_load_scene`` / ``_get_stage`` / ``_build_scene`` / ... ) are
        separate methods so the lifecycle ORDER is spy-verifiable hosted
        without Isaac.
        """
        from isaacsim import SimulationApp

        kwargs = parse_livestream_env(os.environ.get("ISAAC_LIVESTREAM"))
        self._app = SimulationApp(kwargs)

        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)

        try:
            scene = self._load_scene()
            stage = self._get_stage()
            self._build_scene(scene, stage)
            self._setup_sensors(scene, stage)
            self._ensure_scene_defaults(stage)
            self._play_timeline()
            self.setup(stage)
            self.main()
            self.shutdown()
        except Exception as exc:  # noqa: BLE001
            # app.close() (the finally) calls _exit(0) and swallows the
            # traceback, so surface the failure on stdout first (the
            # marker-line acceptance convention, ADR-0017 section 7).
            print(f"[RAISED] {type(exc).__name__}: {exc}", flush=True)
            raise
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            self._app.close()

    # -- Lifecycle seams (Isaac-side; function-local imports) ------------

    def _load_scene(self) -> Dict[str, Any]:
        """Read + merge the three-file scene (pure)."""
        scene_path = _REPO_ROOT / self.SCENE
        return load_three_file_scene(scene_path)

    def _get_stage(self) -> Any:
        """Return the live USD stage from the Kit context."""
        import omni.usd

        return omni.usd.get_context().get_stage()

    def _build_scene(self, scene: Dict[str, Any], stage: Any) -> None:
        """Spawn the scene via the framework Isaac Lab adapter (#154).

        Delegates to ``isaac_devkit.scene.build_scene`` -- the
        ``to_isaaclab_cfg`` -> ``sim_utils`` cfg -> ``cfg.func()`` spawn
        path (ADR-0018 decisions 1, 3). The example no longer carries its
        own raw-``pxr`` ``DefinePrim`` / ``GetReferences().AddReference``
        spawn: the adapter spawns the environment ground + light, the
        robot USD at ``/World/Robot`` (referencing
        ``camera_bot.usd`` whose ``defaultPrim`` is ``/camera_bot``), and
        each object instance under ``/World/Objects``. ``base_link`` then
        resolves at ``/World/Robot/base_link`` so the camera placement's
        ``parent_prim`` resolves.

        ``repo_root`` is ``<repo>/example/sim`` -- the example's model
        paths resolve there (``resolve_model_path`` tolerates the robot
        entry's ``model/usd/``-prefixed value). The adapter's own sensor
        tail fires only for TOP-LEVEL ``scene.sensors`` (the example has
        none -- its camera placement is nested under
        ``scene.robot.sensors`` and is wired by ``_setup_sensors``), so
        there is no double sensor setup.
        """
        from isaac_devkit.scene import build_scene

        example_root = _REPO_ROOT / "example" / "sim"
        build_scene(scene, stage, example_root)

    def _setup_sensors(self, scene: Dict[str, Any], stage: Any) -> None:
        """依機器人的感測器設定建立相機。"""
        from isaac_devkit.sensors import load_config, setup_camera

        for placement in scene["robot"].get("sensors", []):
            cfg_rel = placement["config"]
            cfg_abs = _REPO_ROOT / "example" / "sim" / cfg_rel
            cfg = load_config(cfg_abs)
            mount = setup_camera(cfg, stage)
            print(f"[CAMERA MOUNT] {mount}", flush=True)

    def _play_timeline(self) -> None:
        """Set an effectively-infinite end time and start the timeline."""
        import omni.timeline

        timeline = omni.timeline.get_timeline_interface()
        timeline.set_end_time(1e10)
        timeline.play()
        for _ in range(10):
            self._app.update()

    # -- Subclass hooks --------------------------------------------------

    def setup(self, stage: Any) -> None:
        print("[BOOT OK]", flush=True)

    def main(self) -> None:
        """執行模擬更新，直到收到停止訊號或達到 EXAMPLE_TICK_BUDGET。"""
        budget = int(os.environ.get("EXAMPLE_TICK_BUDGET", "1800"))
        while (
            not self._should_quit
            and self._app.is_running()
            and self._ticks < budget
        ):
            self._app.update()
            self._ticks += 1

    def shutdown(self) -> None:
        """Pre-close marker; the framework finally-block calls app.close."""
        print("[EXIT CLEAN]", flush=True)


if __name__ == "__main__":
    ExampleDriver().run()
