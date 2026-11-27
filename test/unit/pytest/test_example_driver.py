"""Hosted coverage for scene loading and the camera_bot driver lifecycle."""

import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "framework"))
sys.path.insert(0, str(REPO_ROOT / "example" / "sim"))

import example_driver as ed  # noqa: E402  (path injection before import)

pytestmark = pytest.mark.core

EXAMPLE_SCENE = REPO_ROOT / "example" / "sim" / "scene" / "scene.yaml"


# ---------- import-safety: the example stays hosted-importable ----------


class TestImportSafety:
    def test_no_isaac_modules_imported(self):
        # Importing the example driver must not pull omni / pxr / isaacsim
        # (every Isaac import is function-local, PRD A1).
        for banned in ("omni", "pxr", "isaacsim"):
            assert banned not in sys.modules, (
                f"{banned} leaked into sys.modules on example import"
            )


# ---------- three-file scene merge ----------


class TestLoadThreeFileScene:
    def test_merges_into_single_scene_dict(self):
        scene = ed.load_three_file_scene(EXAMPLE_SCENE)
        # robot from robot.yaml
        assert scene["robot"]["name"] == "camera_bot"
        assert scene["robot"]["model"].endswith(".usd")
        assert scene["robot"]["source_urdf"].endswith(".urdf")
        # objects from object.yaml
        assert len(scene["objects"]) == 1
        assert scene["objects"][0]["mobility"] in ("dynamic", "static")
        assert scene["environment"]["ground_plane"] is True
        assert "ros2_io" not in scene

    def test_robot_has_nested_sensor_placement(self):
        scene = ed.load_three_file_scene(EXAMPLE_SCENE)
        sensors = scene["robot"]["sensors"]
        assert len(sensors) >= 1
        assert sensors[0]["link"] == "base_link"
        assert sensors[0]["config"].endswith("custom.yaml")

    def test_missing_scene_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ed.load_three_file_scene(tmp_path / "nope.yaml")

    def test_missing_import_target_raises(self, tmp_path):
        scene = tmp_path / "scene.yaml"
        scene.write_text("imports: [robot.yaml]\n")
        with pytest.raises(FileNotFoundError):
            ed.load_three_file_scene(scene)

    def test_imports_resolved_relative_to_scene_file(self, tmp_path):
        # A scene that imports a sibling robot fragment merges its keys.
        (tmp_path / "robot.yaml").write_text(
            "robot: {name: r, model: m.urdf, pose: {xyz: [0,0,0], rpy: [0,0,0]}}\n"
        )
        scene = tmp_path / "scene.yaml"
        scene.write_text("imports: [robot.yaml]\n")
        merged = ed.load_three_file_scene(scene)
        assert merged["robot"]["name"] == "r"


# ---------- expected prim-path strings (L1 target, pure) ----------


class TestExpectedPrimPaths:
    def test_robot_root_and_base_link(self):
        scene = ed.load_three_file_scene(EXAMPLE_SCENE)
        assert ed.expected_robot_prim_path(scene) == "/World/Robot"
        assert (
            ed.expected_base_link_prim_path(scene)
            == "/World/Robot/base_link"
        )


def test_main_ticks_without_an_io_plugin(monkeypatch):
    ticks = []
    driver = ed.ExampleDriver()
    driver._app = types.SimpleNamespace(
        is_running=lambda: True, update=lambda: ticks.append(1)
    )
    monkeypatch.setenv("EXAMPLE_TICK_BUDGET", "2")
    driver.main()
    assert len(ticks) == 2


# ---------- SCENE attr shape ----------


class TestSceneAttr:
    def test_scene_attr_points_at_three_file_scene(self):
        assert ed.ExampleDriver.SCENE.endswith("scene/scene.yaml")

    def test_scene_attr_is_set(self):
        assert ed.ExampleDriver.SCENE != ""


# ---------- run() lifecycle order spy (pure) ----------


class TestLifecycleOrder:
    """The example's run() walks the SCENE-driven lifecycle
    (ADR-0017 section 9 / PRD A2):

        SimulationApp -> load_scene -> get_stage -> build_scene ->
        setup_sensors -> ensure_scene_defaults ->
        play_timeline -> setup -> main -> shutdown -> close

    Verified hosted with a fake isaacsim module and recorder overrides;
    monkeypatch restores sys.modules + signal afterwards so the
    import-safety invariant holds for sibling tests.
    """

    @staticmethod
    def _fake_isaacsim(calls):
        fake = types.ModuleType("isaacsim")

        class _FakeApp:
            def __init__(self, _kwargs):
                calls.append("simulation_app")

            def is_running(self):
                return False

            def update(self):
                pass

            def close(self):
                calls.append("close")

        fake.SimulationApp = _FakeApp
        return fake

    def test_run_walks_scene_lifecycle_in_order(self, monkeypatch):
        calls = []
        monkeypatch.setitem(
            sys.modules, "isaacsim", self._fake_isaacsim(calls)
        )
        monkeypatch.delenv("ISAAC_LIVESTREAM", raising=False)
        monkeypatch.setattr(ed.signal, "signal", lambda *_a: None)

        class _Spy(ed.ExampleDriver):
            def _load_scene(self):
                calls.append("load_scene")
                return {"robot": {}}

            def _get_stage(self):
                calls.append("get_stage")
                return object()

            def _build_scene(self, scene, stage):
                calls.append("build_scene")

            def _setup_sensors(self, scene, stage):
                calls.append("setup_sensors")

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

        _Spy().run()

        assert calls == [
            "simulation_app",
            "load_scene",
            "get_stage",
            "build_scene",
            "setup_sensors",
            "ensure_scene_defaults",
            "play_timeline",
            "setup",
            "main",
            "shutdown",
            "close",
        ]

    def test_sigint_during_main_still_calls_shutdown(self, monkeypatch):
        # Injected SIGINT path (ADR-0017 marker-line acceptance: shutdown
        # called after injected SIGINT). _on_signal flips _should_quit;
        # main() observes it and returns normally, so shutdown() + close()
        # both run -- cleanup is not skipped on the Ctrl+C path.
        calls = []
        monkeypatch.setitem(
            sys.modules, "isaacsim", self._fake_isaacsim(calls)
        )
        monkeypatch.delenv("ISAAC_LIVESTREAM", raising=False)
        monkeypatch.setattr(ed.signal, "signal", lambda *_a: None)

        class _Spy(ed.ExampleDriver):
            def _load_scene(self):
                return {"robot": {}}

            def _get_stage(self):
                return object()

            def _build_scene(self, scene, stage):
                pass

            def _setup_sensors(self, scene, stage):
                pass

            def _ensure_scene_defaults(self, stage):
                pass

            def _play_timeline(self):
                pass

            def setup(self, stage):
                pass

            def main(self):
                # Simulate Kit delivering SIGINT mid-loop: the handler
                # flips the quit flag and the loop breaks normally.
                self._on_signal(2, None)
                calls.append("main")

            def shutdown(self):
                calls.append("shutdown")

        spy = _Spy()
        spy.run()
        assert spy._should_quit is True
        assert calls.index("shutdown") > calls.index("main")
        assert "close" in calls
