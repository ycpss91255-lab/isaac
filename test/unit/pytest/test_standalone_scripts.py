"""Hosted tests for the pure helpers in standalone_common.py."""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT_DIR = _REPO_ROOT / "src" / "script"
_HELPER = _SCRIPT_DIR / "standalone_common.py"
_HARD_CODED_HOME = re.compile(r"/home/[^/\s<>]+/")

_ISAAC_TOP_LEVEL = ("omni", "pxr", "isaacsim", "isaaclab", "carb", "rclpy")


def _load_helper():
    spec = importlib.util.spec_from_file_location("standalone_common", _HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_helper_exists_and_imports_without_isaac():
    assert _HELPER.is_file()
    before = set(sys.modules)
    _load_helper()
    leaked = sorted(
        name
        for name in set(sys.modules) - before
        if name.partition(".")[0] in _ISAAC_TOP_LEVEL
    )
    assert leaked == []


def test_kit_config_follows_isaac_livestream():
    helper = _load_helper()
    assert helper.kit_config(None) == {"headless": True}
    assert helper.kit_config("0") == {"headless": True}
    streaming = helper.kit_config("2")
    assert streaming["livestream"] == 2
    assert streaming["headless"] is False
    with pytest.raises(ValueError):
        helper.kit_config("9")


def test_helper_has_no_openbase_attributes():
    helper = _load_helper()
    names = (
        "openbase_usd_path",
        "setup_openbase_stage",
        "OPENBASE_WHEELS",
        "OPENBASE_BASE_LINK",
    )
    assert [name for name in names if hasattr(helper, name)] == []


def test_periodic_timer_fires_once_per_period_regardless_of_tick_rate():
    helper = _load_helper()
    now = [100.0]
    timer = helper.PeriodicTimer(1.0, clock=lambda: now[0])
    fired = 0
    # 600 updates/s for 3.5 s: a tick-count gate (every 60) would fire 35x.
    for _ in range(2100):
        now[0] += 1.0 / 600.0
        if timer.due():
            fired += 1
    assert fired == 3


def test_periodic_timer_does_not_burst_after_a_stall():
    helper = _load_helper()
    now = [0.0]
    timer = helper.PeriodicTimer(1.0, clock=lambda: now[0])
    now[0] = 10.0  # a 10 s hitch (shader compile, first frame)
    assert timer.due() is True
    assert timer.due() is False


def test_run_and_exit_turns_an_exception_into_exit_code_1(capsys):
    helper = _load_helper()
    codes = []

    def _boom():
        raise ModuleNotFoundError("No module named 'omni.isaac.dynamic_control'")

    helper.run_and_exit(_boom, exit_fn=codes.append)
    assert codes == [1]
    assert "omni.isaac.dynamic_control" in capsys.readouterr().err


@pytest.mark.parametrize("returned, expected", [(None, 0), (0, 0), (3, 3)])
def test_run_and_exit_passes_main_return_code_through(returned, expected):
    helper = _load_helper()
    codes = []
    helper.run_and_exit(lambda: returned, exit_fn=codes.append)
    assert codes == [expected]


def test_standalone_smoke_has_no_hard_coded_workspace():
    source = (_SCRIPT_DIR / "test" / "standalone_smoke.sh").read_text(encoding="utf-8")
    assert not _HARD_CODED_HOME.search(source)
