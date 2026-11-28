"""IsaacDriver base class -- lifecycle-only pattern (ADR-0009).

Subclass contract:

    from isaac_devkit.driver import IsaacDriver

    class MyDriver(IsaacDriver):
        USD = "model/usd/robot/openbase/openbase.usd"  # repo-relative

        def setup(self, stage):
            self.stage = stage

        def main(self):
            while not self._should_quit and self._app.is_running():
                # per-tick work
                self._app.update()

        def shutdown(self):
            # close files and release application resources
            pass

    if __name__ == "__main__":
        MyDriver().run()

The base class starts Kit with ``isaacsim.SimulationApp``, installs signal
handlers, opens the stage, applies scene defaults, starts the timeline,
and closes the app. The subclass owns the main loop (ADR-0009).

Launch configuration and path resolution can be tested on the host.
Kit imports are local to the methods that use them.
"""

from __future__ import annotations

import importlib
import os
import signal
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Pure-Python helpers (host-runnable, no Isaac Sim dependency).
# ---------------------------------------------------------------------------


def load_io_plugin(spec: str):
    """Resolve an ``ISAAC_IO_PLUGIN`` value (``module:function``) to a callable.

    Raises ``RuntimeError`` with a message naming the variable on a bad
    format, an unimportable module, or a missing / non-callable function.
    """
    parts = spec.split(":")
    if len(parts) != 2 or not all(p and p == p.strip() and " " not in p
                                  for p in parts):
        raise RuntimeError(
            f"ISAAC_IO_PLUGIN={spec!r} is malformed; expected "
            "module:function (e.g. my_pkg.io:setup_io)"
        )
    module_name, func_name = parts
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise RuntimeError(
            f"ISAAC_IO_PLUGIN: module {module_name!r} import failed: {exc}"
        ) from exc
    func = getattr(module, func_name, None)
    if not callable(func):
        raise RuntimeError(
            f"ISAAC_IO_PLUGIN: callable {func_name!r} not found in module "
            f"{module_name!r}"
        )
    return func


def parse_livestream_env(env_value: Optional[str]) -> Dict[str, Any]:
    """Translate the ``ISAAC_LIVESTREAM`` env value into SimulationApp kwargs.

    Values follow the docker stage convention introduced in
    `ycpss91255-lab/isaac#28`:

    - unset / empty / ``"0"`` -> headless, no streaming. Used by the
      ``headless`` Docker stage where Kit boots without a window or
      WebRTC publisher.
    - ``"1"`` -> native streaming. Kit's legacy streaming protocol.
    - ``"2"`` -> WebRTC streaming with raytraced lighting.

    Raising on unknown values rather than silently defaulting catches
    typos in compose / .env files at boot time instead of producing a
    confused-looking idle container.
    """
    if env_value is None or env_value == "" or env_value == "0":
        return {"headless": True}
    if env_value == "1":
        return {"headless": False, "livestream": 1}
    if env_value == "2":
        return {
            "headless": False,
            "livestream": 2,
            "renderer": "RaytracedLighting",
        }
    raise ValueError(
        f"unsupported ISAAC_LIVESTREAM value {env_value!r}; "
        "expected one of '', '0', '1', '2'"
    )


def parse_livestream_simulation_app(
    env_value: Optional[str],
) -> tuple[Dict[str, Any], Optional[str]]:
    """Return the headless launch config and optional streaming Kit experience.

    The experience file controls streaming in Isaac Sim 6.2. Modes 1 and 2
    both select the same WebRTC experience. Mode 1 formerly used native streaming.
    """
    if env_value not in (None, "", "0", "1", "2"):
        raise ValueError(
            f"unsupported ISAAC_LIVESTREAM value {env_value!r}; "
            "expected one of '', '0', '1', '2'"
        )
    config = {
        "headless": True,
        "disable_viewport_updates": False,
    }
    if env_value in ("1", "2"):
        return config, "/isaac-sim/apps/isaacsim.exp.base.python.streaming.kit"
    return config, None


def boot_extension_kit_args(extensions) -> list:
    """Build ordered Kit ``--enable <ext>`` pairs for SimulationApp's extra_args."""
    args: list = []
    for ext in extensions or ():
        args += ["--enable", ext]
    return args


def resolve_repo_relative_usd(usd_path: str, *, module_file: str) -> Path:
    """Resolve a repo-relative USD path to an absolute ``Path``.

    Subclasses declare ``USD = "model/usd/robot/openbase/openbase.usd"``
    so that the path travels with the repo and does not bake in a
    container mount point. The resolution uses the module's filesystem
    location: ``framework/isaac_devkit/driver.py`` lives two levels under
    the repo root, so ``parents[2]`` of that module's file is the repo
    root. Models live under ``<repo_root>/src`` (e.g. ``src/model/usd/``),
    so resolution anchors at ``<repo_root>/src`` -- the same directory the
    pre-extraction ``src/script/isaac_driver.py`` resolved against via its
    ``parents[1]``, keeping the repo-relative ``USD`` convention intact
    across the move.

    Absolute paths are returned unchanged so that ad-hoc tests can point
    at a fixture USD outside the repo without subclassing the resolver.
    """
    if not usd_path:
        raise ValueError(
            "USD class attribute is required; subclass must set it to a "
            "repo-relative path (e.g. 'model/usd/robot/openbase/openbase.usd')"
        )
    p = Path(usd_path)
    if p.is_absolute():
        return p
    # framework/isaac_devkit/driver.py -> parents[2] = repo root; models
    # live under <repo_root>/src (the old anchor directory).
    repo_root = Path(module_file).resolve().parents[2]
    return repo_root / "src" / usd_path


# ---------------------------------------------------------------------------
# Lifecycle base class.
# ---------------------------------------------------------------------------


class IsaacDriver:
    """Lifecycle-only base class for Isaac Sim standalone drivers (ADR-0009).

    Class attributes:
        ``USD`` -- repo-relative path to the USD that ``run()`` opens
        after Kit boots. Deprecated in favor of ``SCENE`` (ADR-0017
        section 9); kept functional for the existing drivers until the
        forklift migration (#136). Subclass must set this for now.
        ``SCENE`` -- repo-relative path to a scene YAML (ADR-0017 A7
        contract surface). Used by scene-based drivers.

    Override surface:
        ``setup(stage)`` -- post-stage-open initialization.
        ``main()``        -- the loop. Default: ``app.update()`` until
                             ``_should_quit`` flips or Kit reports
                             ``is_running()`` is False.
        ``shutdown()``    -- pre-close cleanup.

    Internals (subclass should not override):
        ``_on_signal``, ``_open_stage``, ``_ensure_scene_defaults``,
        ``_play_timeline`` -- pieces of the ``run()`` recipe.
    """

    USD: str = ""
    SCENE: str = ""

    # External plugins can specify additional Kit extensions via ISAAC_KIT_EXTRA_ARGS.
    BOOT_EXTENSIONS: tuple = ("isaacsim.core.nodes",)

    def __init__(self) -> None:
        self._should_quit: bool = False
        self._app: Any = None

    # -- Entry point ---------------------------------------------------------

    def run(self) -> None:
        """Walk the lifecycle: init Kit, open stage, set up, loop, shut down.

        Construct SimulationApp before importing stage APIs. Kit installs
        signal handlers during startup, so register ours after construction.
        """
        config, experience = parse_livestream_simulation_app(
            os.environ.get("ISAAC_LIVESTREAM")
        )
        config["extra_args"] = (
            boot_extension_kit_args(self.BOOT_EXTENSIONS)
            + os.environ.get("ISAAC_KIT_EXTRA_ARGS", "").split()
        )

        from isaacsim import SimulationApp

        if experience is None:
            self._app = SimulationApp(config)
        else:
            self._app = SimulationApp(config, experience)

        # Override Kit's SIGINT (which swallows Ctrl+C) so the loop can
        # observe ``_should_quit`` and break out cleanly.
        signal.signal(signal.SIGINT, self._on_signal)
        signal.signal(signal.SIGTERM, self._on_signal)

        try:
            stage = self._open_stage()
            self._ensure_scene_defaults(stage)
            self._run_io_plugin(stage)
            self._play_timeline()
            self.setup(stage)
            self.main()
            self.shutdown()
        finally:
            # SimulationApp.close() forces process
            # _exit(0) on its way out and overrides any sys.exit(N)
            # downstream, so an exception in flight here would never reach
            # the caller. Print it first, or a setup()/main() failure exits
            # rc 0 with no trace (isaac#248). Subclasses that want to signal
            # failure must do so before calling super().run() or via stdout
            # markers.
            if sys.exc_info()[0] is not None:
                traceback.print_exc()
            sys.stdout.flush()
            sys.stderr.flush()
            self._app.close()

    # -- Subclass hooks ------------------------------------------------------

    def setup(self, stage: Any) -> None:
        """Post-stage-open hook. Default is a no-op."""

    def main(self) -> None:
        """Main loop. Default ticks until ``_should_quit`` or Kit stops."""
        while not self._should_quit and self._app.is_running():
            self._app.update()

    def shutdown(self) -> None:
        """Pre-close cleanup hook. Default is a no-op."""

    # -- Internals -----------------------------------------------------------

    def _on_signal(self, signum: int, _frame: Any) -> None:
        print(
            f"[isaac_driver] signal {signum} received; requesting shutdown",
            flush=True,
        )
        self._should_quit = True

    def _open_stage(self) -> Any:
        import omni.usd

        abs_path = resolve_repo_relative_usd(self.USD, module_file=__file__)
        ctx = omni.usd.get_context()
        if not ctx.open_stage(str(abs_path)):
            raise RuntimeError(
                f"open_stage returned False for {abs_path}; check the path "
                "is reachable from inside the container"
            )
        # Wait for the open to settle. 600 ticks ~= 10 s at 60 Hz which
        # covers Asset Structure 3.0 imports with sublayer chains.
        for _ in range(600):
            if ctx.get_stage_state() == omni.usd.StageState.OPENED:
                break
            self._app.update()
        else:
            raise RuntimeError(f"stage at {abs_path} never reached OPENED")
        return ctx.get_stage()

    def _run_io_plugin(self, stage: Any) -> None:
        """Call the ``ISAAC_IO_PLUGIN`` hook once, before the timeline plays.

        No-op when the variable is unset or empty (isaac#423). Format,
        import and lookup errors raise here, i.e. at startup.
        """
        spec = os.environ.get("ISAAC_IO_PLUGIN", "")
        if not spec:
            return
        plugin = load_io_plugin(spec)
        default_prim = stage.GetDefaultPrim()
        robot_prim = str(default_prim.GetPath()) if default_prim else "/World"
        config = {
            "usd_path": str(
                resolve_repo_relative_usd(self.USD, module_file=__file__)
            ),
            "robot_prim": robot_prim,
        }
        plugin(stage, robot_prim, config)

    def _ensure_scene_defaults(self, stage: Any) -> None:
        """Add a SunLight if the scene does not already bring a light.

        ADR-0009 calls for a SunLight + GroundPlane default. GroundPlane
        creation through ``omni.kit.commands.CreateGroundPlane`` is
        Kit-version-sensitive and deferred to a follow-up; SunLight via
        ``UsdLux.DistantLight`` is stable across 5.x and is enough to
        keep viewport-less debug renders readable.

        ADR-0018: ``scene.build_scene`` now spawns a distant light at
        ``/World/light`` via the ``sim_utils`` adapter. This default is
        opt-out so the scene never ends up with two SunLights -- if a
        light already exists at ``/World/light`` or ``/World/SunLight``,
        skip. (The example driver consolidation is #154.)
        """
        from pxr import UsdLux

        for existing in ("/World/light", "/World/SunLight"):
            if stage.GetPrimAtPath(existing).IsValid():
                return
        UsdLux.DistantLight.Define(stage, "/World/SunLight")

    def _play_timeline(self) -> None:
        """Enable physics warm start and pace the timeline at 60 Hz (#447)."""
        import carb.settings
        import omni.timeline

        # A physics backend can replace the package-level SimulationManager.
        # Prefer the original manager that owns the warm-start callback.
        package = "isaacsim.core.simulation_manager"
        for module_name in (f"{package}.impl.simulation_manager", package):
            try:
                module = importlib.import_module(module_name)
            except ImportError:
                continue
            manager = getattr(module, "SimulationManager", None)
            if hasattr(manager, "enable_warm_start_callback"):
                manager.enable_warm_start_callback(True)
                break
        else:
            print("[isaac_driver] Warning: warm-start callback unavailable", flush=True)

        settings = carb.settings.get_settings()
        settings.set("/app/runLoops/main/rateLimitEnabled", True)
        settings.set("/app/runLoops/main/rateLimitFrequency", 60)
        settings.set("/app/player/useFixedTimeStepping", True)

        timeline = omni.timeline.get_timeline_interface()
        timeline.set_looping(False)
        # 1e10 seconds is effectively infinite for any drive scenario.
        timeline.set_end_time(1e10)
        timeline.play()
        # A handful of warmup ticks lets physx settle so subclass.setup()
        # sees a stable stage.
        for _ in range(10):
            self._app.update()
