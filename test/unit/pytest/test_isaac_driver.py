"""Host-side tests for the IsaacDriver launch configuration and lifecycle."""

import sys
import types
from copy import deepcopy
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "framework"))

from isaac_devkit import driver as id_mod  # noqa: E402  (path injection before import)

pytestmark = pytest.mark.core

OMWR_MODEL = "usd/robot/custom/omwr/omwr.usd"


# ---------- parse_livestream_env ----------


class TestParseLivestreamEnv:
    def test_unset_returns_headless(self):
        assert id_mod.parse_livestream_env(None) == {"headless": True}

    def test_empty_string_returns_headless(self):
        assert id_mod.parse_livestream_env("") == {"headless": True}

    def test_zero_returns_headless(self):
        assert id_mod.parse_livestream_env("0") == {"headless": True}

    def test_one_returns_native_livestream(self):
        cfg = id_mod.parse_livestream_env("1")
        assert cfg == {"headless": False, "livestream": 1}

    def test_two_returns_webrtc_with_raytracing(self):
        cfg = id_mod.parse_livestream_env("2")
        assert cfg == {
            "headless": False,
            "livestream": 2,
            "renderer": "RaytracedLighting",
        }

    def test_unknown_value_raises(self):
        with pytest.raises(ValueError) as ei:
            id_mod.parse_livestream_env("3")
        assert "'3'" in str(ei.value)
        # Lists the accepted values so a misconfigured compose file is
        # obvious at boot time.
        assert "'0'" in str(ei.value) or "'1'" in str(ei.value)

    def test_garbage_value_raises(self):
        with pytest.raises(ValueError):
            id_mod.parse_livestream_env("yes")


STREAM_EXPERIENCE = "/isaac-sim/apps/isaacsim.exp.base.python.streaming.kit"


class TestParseLivestreamSimulationApp:
    @pytest.mark.parametrize("value", [None, "", "0", "1", "2"])
    def test_launch_config_and_experience(self, value):
        config, experience = id_mod.parse_livestream_simulation_app(value)
        assert config["headless"] is True
        assert "livestream" not in config
        assert config["disable_viewport_updates"] is False
        assert experience == (STREAM_EXPERIENCE if value in ("1", "2") else None)

    def test_streaming_modes_return_identical_config_and_experience(self):
        assert (
            id_mod.parse_livestream_simulation_app("1")
            == id_mod.parse_livestream_simulation_app("2")
        )

    @pytest.mark.parametrize("value", ["3", "yes"])
    def test_unknown_value_raises(self, value):
        with pytest.raises(ValueError, match=repr(value)):
            id_mod.parse_livestream_simulation_app(value)


# ---------- resolve_repo_relative_usd ----------


class TestResolveRepoRelativeUsd:
    def test_relative_path_resolves_under_repo_root(self, tmp_path):
        # Fake a framework layout: repo_root/framework/isaac_devkit/driver.py.
        # Models live under <repo_root>/src, so resolution anchors there
        # (same directory the pre-extraction script/ layout resolved to).
        repo_root = tmp_path / "myrepo"
        module_dir = repo_root / "framework" / "isaac_devkit"
        module_dir.mkdir(parents=True)
        fake_module = module_dir / "driver.py"
        fake_module.write_text("# stub")

        resolved = id_mod.resolve_repo_relative_usd(
            OMWR_MODEL,
            module_file=str(fake_module),
        )

        assert resolved == repo_root / "src" / OMWR_MODEL

    def test_absolute_path_returned_unchanged(self, tmp_path):
        abs_usd = tmp_path / "anywhere" / "fixture.usda"
        resolved = id_mod.resolve_repo_relative_usd(
            str(abs_usd),
            module_file=__file__,  # value irrelevant for absolute path
        )
        assert resolved == abs_usd

    def test_empty_string_raises(self):
        with pytest.raises(ValueError) as ei:
            id_mod.resolve_repo_relative_usd("", module_file=__file__)
        message = str(ei.value)
        assert "USD" in message
        assert "absolute path" in message
        assert "<repo_root>/src" not in message
        assert OMWR_MODEL not in message

    def test_subclass_forgot_to_set_usd_raises(self):
        # Mirrors the "subclass forgot to set USD" failure mode -- the
        # class attribute defaults to "" so resolve sees an empty path.
        default_usd_value = id_mod.IsaacDriver.USD
        with pytest.raises(ValueError):
            id_mod.resolve_repo_relative_usd(
                default_usd_value, module_file=__file__,
            )


# ---------- Construction without Kit ----------


class TestConstructionWithoutKit:
    """The class must be import-safe and constructible on the host so
    unit tests can poke at attribute defaults without booting Isaac Sim.
    Kit-touching code is deferred into ``run`` and friends.
    """

    def test_default_attrs(self):
        driver = id_mod.IsaacDriver()
        assert driver._should_quit is False
        assert driver._app is None
        assert not hasattr(driver, "_app_launcher")

    def test_default_usd_is_empty(self):
        assert id_mod.IsaacDriver.USD == ""

    def test_signal_handler_flips_quit_flag(self):
        # Exercises the pure side of the SIGINT path without installing
        # the handler globally.
        driver = id_mod.IsaacDriver()
        assert driver._should_quit is False
        driver._on_signal(2, None)  # SIGINT
        assert driver._should_quit is True


# ---------- boot_extension_kit_args (isaac#248) ----------


class TestBootExtensionKitArgs:
    """Pure helper building the Kit ``--enable`` argv for boot-time
    extension loads (``IsaacDriver.BOOT_EXTENSIONS``). Boot-time enable is
    an optimisation; runtime enable works too (isaac#248).
    """

    def test_single_extension(self):
        assert id_mod.boot_extension_kit_args(["isaacsim.sensors.rtx"]) == [
            "--enable",
            "isaacsim.sensors.rtx",
        ]

    def test_multiple_extensions_preserve_order(self):
        assert id_mod.boot_extension_kit_args(
            ("isaacsim.core.nodes", "isaacsim.sensors.rtx")
        ) == [
            "--enable",
            "isaacsim.core.nodes",
            "--enable",
            "isaacsim.sensors.rtx",
        ]

    def test_empty_is_noop(self):
        assert id_mod.boot_extension_kit_args(()) == []

    def test_none_is_noop(self):
        assert id_mod.boot_extension_kit_args(None) == []

    def test_default_boot_extensions(self):
        assert id_mod.IsaacDriver.BOOT_EXTENSIONS == ("isaacsim.core.nodes",)


# ---------- A7 contract shape + lifecycle-order spy (ADR-0017 additions) ----


class TestSceneAttrShape:
    """``SCENE`` class attr (ADR-0017 section 9 A7 shape). Greenfield
    addition -- ``run()`` still consumes ``USD``; the SCENE-driven
    lifecycle rewire lands with the example (#131).
    """

    def test_default_scene_is_empty(self):
        assert id_mod.IsaacDriver.SCENE == ""


def _install_simulation_app(monkeypatch, calls):
    class SimulationApp:
        def __init__(self, launch_config, experience=None):
            calls.append("simulation_app")
            self.config = deepcopy(launch_config)
            self.experience = experience
            self.argv_at_init = list(sys.argv)

        def is_running(self):
            return False

        def close(self):
            calls.append("close")

    isaacsim = types.ModuleType("isaacsim")
    isaacsim.SimulationApp = SimulationApp
    monkeypatch.setitem(sys.modules, "isaacsim", isaacsim)
    monkeypatch.setattr(id_mod.signal, "signal", lambda *_: None)
    monkeypatch.delenv("ISAAC_LIVESTREAM", raising=False)
    return SimulationApp


class _HostedDriver(id_mod.IsaacDriver):
    def _open_stage(self):
        return object()

    def _ensure_scene_defaults(self, stage):
        pass

    def _play_timeline(self):
        pass


class TestPlayTimeline:
    def _play(self, monkeypatch, *, impl_missing=False, callbacks_available=True):
        events = []

        def module(name, parent=None):
            full_name = f"{parent.__name__}.{name}" if parent else name
            fake = types.ModuleType(full_name)
            fake.__path__ = []
            monkeypatch.setitem(sys.modules, full_name, fake)
            if parent:
                setattr(parent, name, fake)
            return fake

        settings = types.SimpleNamespace(
            set=lambda key, value: events.append(("set", key, value)),
        )
        module("settings", module("carb")).get_settings = lambda: settings
        timeline = types.SimpleNamespace(
            set_looping=lambda flag: events.append(("set_looping", flag)),
            set_end_time=lambda end: events.append(("set_end_time", end)),
            play=lambda: events.append(("play",)),
        )
        module("timeline", module("omni")).get_timeline_interface = lambda: timeline

        def manager(source):
            class SimulationManager:
                if callbacks_available:
                    @staticmethod
                    def enable_warm_start_callback(flag):
                        events.append(("warm_start", source, flag))

            return SimulationManager

        core = module("core", module("isaacsim"))
        package = module("simulation_manager", core)
        package.SimulationManager = manager("package")
        impl = module("impl", package)
        if impl_missing:
            monkeypatch.setitem(sys.modules, f"{impl.__name__}.simulation_manager", None)
        else:
            module("simulation_manager", impl).SimulationManager = manager("impl")

        class TimelineDriver(id_mod.IsaacDriver):
            pass

        driver = TimelineDriver()
        driver._app = types.SimpleNamespace(update=lambda: events.append(("update",)))
        driver._play_timeline()
        return events

    def test_prefers_impl_warm_start(self, monkeypatch):
        events = self._play(monkeypatch)
        assert [e for e in events if e[0] == "warm_start"] == [
            ("warm_start", "impl", True),
        ]

    def test_uses_package_warm_start_when_impl_missing(self, monkeypatch):
        events = self._play(monkeypatch, impl_missing=True)
        assert ("warm_start", "package", True) in events

    def test_warns_and_plays_when_callbacks_unavailable(self, monkeypatch, capsys):
        events = self._play(monkeypatch, callbacks_available=False)
        output = capsys.readouterr().out
        assert "[isaac_driver] Warning: warm-start callback unavailable" in output
        assert ("play",) in events

    def test_sets_fixed_time_stepping_and_rate_limit(self, monkeypatch):
        events = self._play(monkeypatch)
        settings = dict(event[1:] for event in events if event[0] == "set")
        assert settings["/app/runLoops/main/rateLimitEnabled"] is True
        assert settings["/app/runLoops/main/rateLimitFrequency"] == 60
        assert settings["/app/player/useFixedTimeStepping"] is True

    def test_configures_and_plays_timeline_before_updates(self, monkeypatch):
        events = self._play(monkeypatch)
        assert ("set_looping", False) in events
        assert ("set_end_time", 1e10) in events
        assert [e[0] for e in events] == [
            "warm_start", "set", "set", "set", "set_looping", "set_end_time", "play",
        ] + ["update"] * 10

    def test_updates_app_ten_times(self, monkeypatch):
        assert self._play(monkeypatch).count(("update",)) == 10


class TestLifecycleOrderSpy:
    def test_run_walks_lifecycle_in_order(self, monkeypatch):
        calls = []
        simulation_app = _install_simulation_app(monkeypatch, calls)
        monkeypatch.delenv("ISAAC_IO_PLUGIN", raising=False)
        monkeypatch.setattr(
            id_mod.signal, "signal",
            lambda signum, handler: calls.append((signum, handler)),
        )

        class _SpyDriver(id_mod.IsaacDriver):
            USD = OMWR_MODEL

            def _open_stage(self):
                calls.append("open_stage")
                return object()

            def _ensure_scene_defaults(self, stage):
                calls.append("ensure_scene_defaults")

            def _play_timeline(self):
                calls.append("play_timeline")

            def setup(self, stage):
                calls.append("setup")

            def main(self):
                calls.append("main")

            def shutdown(self):
                calls.append("shutdown")

        driver = _SpyDriver()
        driver.run()

        assert isinstance(driver._app, simulation_app)
        assert not hasattr(driver, "_app_launcher")
        assert calls == [
            "simulation_app",
            (id_mod.signal.SIGINT, driver._on_signal),
            (id_mod.signal.SIGTERM, driver._on_signal),
            "open_stage",
            "ensure_scene_defaults",
            "play_timeline",
            "setup",
            "main",
            "shutdown",
            "close",
        ]

    def test_in_flight_exception_reported_before_close(
        self, monkeypatch, capsys
    ):
        # SimulationApp.close() ends in _exit(0), so an exception raised in
        # setup()/main() never reaches the caller (isaac#248: a
        # ModuleNotFoundError looked like a silent Kit shutdown for two
        # releases). run() must print the traceback BEFORE close().
        calls = []
        app = _install_simulation_app(monkeypatch, calls)
        monkeypatch.delenv("ISAAC_IO_PLUGIN", raising=False)
        stderr_at_close = []

        def close(self):
            stderr_at_close.append(capsys.readouterr().err)
            calls.append("close")

        monkeypatch.setattr(app, "close", close)

        class _FailingDriver(_HostedDriver):
            def setup(self, stage):
                raise ModuleNotFoundError("No module named 'fake_missing_mod'")

        with pytest.raises(ModuleNotFoundError, match="fake_missing_mod"):
            _FailingDriver().run()

        assert calls[-1] == "close"
        assert len(stderr_at_close) == 1
        err = stderr_at_close[0]
        assert "Traceback (most recent call last)" in err
        assert "fake_missing_mod" in err

    def test_clean_run_prints_no_traceback(self, monkeypatch, capsys):
        calls = []
        _install_simulation_app(monkeypatch, calls)
        monkeypatch.delenv("ISAAC_IO_PLUGIN", raising=False)
        _HostedDriver().run()
        assert calls == ["simulation_app", "close"]
        assert "Traceback" not in capsys.readouterr().err


class TestSimulationAppLaunch:
    @pytest.mark.parametrize("value, tokens", [
        (None, []),
        ("", []),
        ("   ", []),
        (" \t\n ", []),
        ("--/app/a=1", ["--/app/a=1"]),
        ("  --/app/a=1\t--/app/b=2   --enable x ",
         ["--/app/a=1", "--/app/b=2", "--enable", "x"]),
    ])
    def test_kit_args_use_launch_config(self, monkeypatch, value, tokens):
        _install_simulation_app(monkeypatch, [])
        monkeypatch.delenv("ISAAC_IO_PLUGIN", raising=False)
        if value is None:
            monkeypatch.delenv("ISAAC_KIT_EXTRA_ARGS", raising=False)
        else:
            monkeypatch.setenv("ISAAC_KIT_EXTRA_ARGS", value)
        monkeypatch.setattr(sys, "argv", ["driver.py", "--caller-option"])

        driver = _HostedDriver()
        driver.BOOT_EXTENSIONS = ("test.first", "test.second")
        driver.run()

        assert driver._app.config["extra_args"] == [
            "--enable", "test.first", "--enable", "test.second", *tokens,
        ]
        assert driver._app.argv_at_init == ["driver.py", "--caller-option"]
        assert sys.argv == ["driver.py", "--caller-option"]

    @pytest.mark.parametrize("mode", ["0", "1", "2"])
    def test_run_passes_livestream_and_experience(self, monkeypatch, mode):
        _install_simulation_app(monkeypatch, [])
        monkeypatch.delenv("ISAAC_IO_PLUGIN", raising=False)
        monkeypatch.setenv("ISAAC_LIVESTREAM", mode)
        driver = _HostedDriver()
        driver.run()
        assert driver._app.config["headless"] is True
        assert "livestream" not in driver._app.config
        assert driver._app.experience == (STREAM_EXPERIENCE if mode != "0" else None)

    def test_invalid_livestream_fails_before_kit_starts(self, monkeypatch):
        calls = []
        _install_simulation_app(monkeypatch, calls)
        monkeypatch.setenv("ISAAC_LIVESTREAM", "3")
        with pytest.raises(ValueError, match="'3'"):
            _HostedDriver().run()
        assert calls == []


class TestIoPlugin:
    """``ISAAC_IO_PLUGIN=module:function`` is imported and called once with
    ``(stage, robot_prim, config)`` after the stage is built and before the
    timeline plays (isaac#423)."""

    USD = OMWR_MODEL

    class _Prim:
        def __init__(self, path):
            self._path = path

        def GetPath(self):
            return self._path

    class _Stage:
        def GetDefaultPrim(self):
            return TestIoPlugin._Prim("/foo")

    def _run(self, monkeypatch, calls):
        _install_simulation_app(monkeypatch, calls)
        stage = self._Stage()
        usd = self.USD

        class _Driver(id_mod.IsaacDriver):
            USD = usd

            def _open_stage(self):
                calls.append("open_stage")
                return stage

            def _ensure_scene_defaults(self, _stage):
                calls.append("ensure_scene_defaults")

            def _play_timeline(self):
                calls.append("play_timeline")

            def setup(self, _stage):
                calls.append("setup")

        _Driver().run()
        return stage

    def _install_plugin(self, monkeypatch, calls, name="fake_io_plugin"):
        mod = types.ModuleType(name)

        def plugin(stage, robot_prim, config):
            calls.append(("plugin", stage, robot_prim, config))

        mod.plugin = plugin
        monkeypatch.setitem(sys.modules, name, mod)

    def test_unset_does_not_call_plugin(self, monkeypatch):
        calls = []
        self._install_plugin(monkeypatch, calls)
        monkeypatch.delenv("ISAAC_IO_PLUGIN", raising=False)
        self._run(monkeypatch, calls)
        assert not [c for c in calls if isinstance(c, tuple)]

    def test_empty_does_not_call_plugin(self, monkeypatch):
        calls = []
        self._install_plugin(monkeypatch, calls)
        monkeypatch.setenv("ISAAC_IO_PLUGIN", "")
        self._run(monkeypatch, calls)
        assert not [c for c in calls if isinstance(c, tuple)]

    def test_called_once_before_play_with_expected_args(self, monkeypatch):
        calls = []
        self._install_plugin(monkeypatch, calls)
        monkeypatch.setenv("ISAAC_IO_PLUGIN", "fake_io_plugin:plugin")
        stage = self._run(monkeypatch, calls)

        plugin_calls = [c for c in calls if isinstance(c, tuple)]
        assert len(plugin_calls) == 1
        _, got_stage, robot_prim, config = plugin_calls[0]
        assert got_stage is stage
        assert robot_prim == "/foo"
        assert isinstance(config, dict)
        assert config["robot_prim"] == "/foo"
        names = [c if isinstance(c, str) else "plugin" for c in calls]
        assert names.index("ensure_scene_defaults") < names.index("plugin")
        assert names.index("plugin") < names.index("play_timeline")
        assert names.index("plugin") < names.index("setup")

    @pytest.mark.parametrize("value", [
        "no_colon", ":func", "mod:", "a:b:c", "mod :func",
    ])
    def test_bad_format_fails_with_clear_message(self, monkeypatch, value):
        calls = []
        monkeypatch.setenv("ISAAC_IO_PLUGIN", value)
        with pytest.raises(RuntimeError, match="ISAAC_IO_PLUGIN.*module:function"):
            self._run(monkeypatch, calls)
        assert "play_timeline" not in calls

    def test_missing_module_fails_with_clear_message(self, monkeypatch):
        calls = []
        monkeypatch.setenv("ISAAC_IO_PLUGIN", "no_such_io_module_423:f")
        with pytest.raises(RuntimeError, match="no_such_io_module_423.*import"):
            self._run(monkeypatch, calls)
        assert "play_timeline" not in calls

    def test_missing_function_fails_with_clear_message(self, monkeypatch):
        calls = []
        self._install_plugin(monkeypatch, calls)
        monkeypatch.setenv("ISAAC_IO_PLUGIN", "fake_io_plugin:nope")
        with pytest.raises(RuntimeError, match="nope.*fake_io_plugin"):
            self._run(monkeypatch, calls)
        assert "play_timeline" not in calls
