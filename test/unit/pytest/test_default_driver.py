"""Host-side contract for opening a USD with the default driver (#336)."""

import subprocess
import sys
import types
from pathlib import Path

import pytest

FRAMEWORK = Path(__file__).resolve().parents[3] / "framework"
sys.path.insert(0, str(FRAMEWORK))

from isaac_devkit.default_driver import DefaultSceneDriver  # noqa: E402
from isaac_devkit import driver as id_mod  # noqa: E402

pytestmark = pytest.mark.core


def test_is_an_isaac_driver():
    assert issubclass(DefaultSceneDriver, id_mod.IsaacDriver)


def test_requires_a_usd_path():
    with pytest.raises(ValueError):
        DefaultSceneDriver("")


def test_relative_usd_becomes_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    usd = Path("robot.usda")
    usd.touch()
    assert DefaultSceneDriver(usd_path=usd).USD == str(tmp_path / usd)


def test_inherits_stage_open_and_lifecycle_hooks():
    for name in ("_open_stage", "setup", "main", "shutdown"):
        assert getattr(DefaultSceneDriver, name) is getattr(id_mod.IsaacDriver, name)


def test_run_opens_usd_plays_ticks_and_closes(tmp_path, monkeypatch):
    calls = []
    usd = tmp_path / "robot.usda"
    usd.touch()
    stage = object()

    class SimulationApp:
        def __init__(self, launch_config, experience=None):
            self.ticks = 0
            calls.append("boot")

        def is_running(self):
            return self.ticks < 3

        def update(self):
            self.ticks += 1
            calls.append("update")

        def close(self):
            calls.append("close")

    def open_stage(path):
        calls.append(("open", path))
        return True

    context = types.SimpleNamespace(
        open_stage=open_stage, get_stage_state=lambda: "opened", get_stage=lambda: stage,
    )
    omni_usd = types.SimpleNamespace(
        get_context=lambda: context, StageState=types.SimpleNamespace(OPENED="opened"),
    )
    monkeypatch.setitem(sys.modules, "omni", types.SimpleNamespace(usd=omni_usd))
    monkeypatch.setitem(sys.modules, "omni.usd", omni_usd)
    isaacsim = types.SimpleNamespace(SimulationApp=SimulationApp)
    monkeypatch.setitem(sys.modules, "isaacsim", isaacsim)
    monkeypatch.setattr(id_mod.signal, "signal", lambda *_: None)
    monkeypatch.delenv("ISAAC_LIVESTREAM", raising=False)
    monkeypatch.delenv("ISAAC_IO_PLUGIN", raising=False)
    driver = DefaultSceneDriver(usd)
    monkeypatch.setattr(driver, "_ensure_scene_defaults",
                        lambda stage: calls.append(("defaults", stage)))
    monkeypatch.setattr(driver, "_play_timeline", lambda: calls.append("play"))

    driver.run()
    assert calls == [
        "boot", ("open", str(usd)), ("defaults", stage), "play",
        "update", "update", "update", "close",
    ]


@pytest.mark.parametrize("module", ["default_driver", "run_scene"])
def test_import_is_kit_free(module):
    probe = """
import importlib
import sys
sys.path.insert(0, sys.argv[1])
importlib.import_module("isaac_devkit." + sys.argv[2])
leaked = [m for m in sys.modules if m.partition(".")[0] in {"omni", "pxr", "isaacsim"}]
assert not leaked, leaked
"""
    result = subprocess.run(
        [sys.executable, "-c", probe, str(FRAMEWORK), module],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
