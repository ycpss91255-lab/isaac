"""Check the repo-local scene recipe and its container command (#336)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

ROOT = Path(__file__).resolve().parents[3]
LOCAL = ROOT / "script/local"


def test_scene_recipe_is_registered_and_invokes_launcher():
    registry = (LOCAL / "justfile.local").read_text(encoding="utf-8")
    assert re.search(r"""^mod\?\s+run\s+['"]run/justfile\.run['"]\s*$""", registry, re.M)
    source = (LOCAL / "run/justfile.run").read_text(encoding="utf-8")
    recipe = re.search(r"^@?scene\b[^\n]*:\s*\n((?:[ \t]+[^\n]*\n?)+)", source, re.M)
    assert recipe, "missing scene recipe"
    body = "\n".join(line for line in recipe[1].splitlines() if not line.lstrip().startswith("#"))
    assert "script/exec.sh" in body
    assert "/isaac-sim/python.sh" in body
    assert "framework/isaac_devkit/run_scene.py" in body


@pytest.mark.skipif(shutil.which("just") is None, reason="requires the just executable")
@pytest.mark.parametrize("args", [
    ["models/my robot.usd"],
    ["models/my robot.usd", "--driver", "drivers/my driver.py"],
], ids=["default", "custom"])
def test_just_run_scene_forwards_arguments_to_exec(tmp_path, args):
    shutil.copyfile(ROOT / "justfile", tmp_path / "justfile")
    shutil.copytree(LOCAL, tmp_path / "script/local")
    wrapper = tmp_path / "script/exec.sh"
    wrapper.write_text(
        "#!/usr/bin/env python3\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)

    result = subprocess.run(
        ["just", "run", "scene", *args], cwd=tmp_path,
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    received = json.loads(result.stdout)
    python = received.index("/isaac-sim/python.sh")
    assert received[python + 1:] == ["framework/isaac_devkit/run_scene.py", *args]
