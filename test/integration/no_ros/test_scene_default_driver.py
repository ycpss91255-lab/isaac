"""Open the pinned Jetbot USD through the launcher with its default driver."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from test_assets import fetch_test_asset  # noqa: E402

pytestmark = pytest.mark.core

RUNNER = Path(__file__).with_name("_scene_default_driver_runner.py")
PYTHON_SH = "/isaac-sim/python.sh"


def test_default_scene_plays_jetbot_without_ros():
    usd = fetch_test_asset("jetbot").resolve()
    result = subprocess.run(
        [PYTHON_SH, str(RUNNER), str(usd)],
        env={**os.environ, "ISAAC_IO_PLUGIN": "", "ISAAC_KIT_EXTRA_ARGS": "",
             "ISAAC_LIVESTREAM": "0"},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=240,
    )
    assert result.returncode == 0, result.stdout[-4000:]
    reports = [line for line in result.stdout.splitlines() if line.startswith("[SCENE] ")]
    assert len(reports) == 1, result.stdout[-4000:]
    scene = json.loads(reports[0].removeprefix("[SCENE] "))
    assert Path(scene["usd"]).resolve() == usd
    assert scene["default_prim"] == "/jetbot"
    assert scene["updates"] == 20
    assert scene["playing"]
    assert scene["end"] > scene["start"], scene
    assert scene["ros_modules"] == []
