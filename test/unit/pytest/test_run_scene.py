"""USD launcher class discovery, driver selection, and CLI dispatch (#336)."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.core

FRAMEWORK = Path(__file__).resolve().parents[3] / "framework"


@pytest.fixture
def launcher(monkeypatch):
    monkeypatch.syspath_prepend(str(FRAMEWORK))
    from isaac_devkit import run_scene

    return run_scene


def write_driver(tmp_path, classes):
    path = tmp_path / "user driver.py"
    path.write_text("from isaac_devkit.driver import IsaacDriver\n" + classes, encoding="utf-8")
    return path


def test_load_single_driver_class(launcher, tmp_path):
    from isaac_devkit.driver import IsaacDriver

    path = write_driver(tmp_path, "class Helper: pass\nclass Robot(IsaacDriver): pass\n")
    cls = launcher.load_driver_class(path)
    assert issubclass(cls, IsaacDriver)
    assert cls.__name__ == "Robot"


@pytest.mark.parametrize("classes", [
    "class Helper: pass\n",
    "class First(IsaacDriver): pass\nclass Second(IsaacDriver): pass\n",
], ids=["no-subclass", "multiple-subclasses"])
def test_load_requires_one_driver_class(launcher, tmp_path, classes):
    path = write_driver(tmp_path, classes)
    with pytest.raises(ValueError):
        launcher.load_driver_class(path)


def test_build_default_driver_opens_cli_usd(launcher, tmp_path):
    from isaac_devkit.default_driver import DefaultSceneDriver

    usd = tmp_path / "robot.usda"
    usd.touch()
    driver = launcher.build_driver(str(usd))
    assert isinstance(driver, DefaultSceneDriver)
    assert driver.USD == str(usd)


@pytest.mark.parametrize("declared_usd", ["", "models/custom.usd"], ids=["fallback", "override"])
def test_build_custom_driver_selects_usd(launcher, tmp_path, declared_usd):
    from isaac_devkit.driver import IsaacDriver

    path = write_driver(tmp_path, f"class Robot(IsaacDriver):\n    USD = {declared_usd!r}\n")
    usd = tmp_path / "robot.usda"
    usd.touch()
    driver = launcher.build_driver(str(usd), driver_path=str(path))
    assert isinstance(driver, IsaacDriver)
    assert type(driver).__name__ == "Robot"
    assert driver.USD == (declared_usd or str(usd))


@pytest.mark.parametrize("custom", [False, True], ids=["default", "custom"])
def test_main_builds_and_runs_selected_driver(launcher, tmp_path, monkeypatch, custom):
    usd = tmp_path / "robot.usda"
    usd.touch()
    path = write_driver(tmp_path, "class Robot(IsaacDriver): pass\n") if custom else None
    argv = [str(usd)]
    if path:
        argv.extend(["--driver", str(path)])

    driver = Mock()
    built = []

    def build(usd, driver_path=None):
        built.append((Path(usd), Path(driver_path) if driver_path is not None else None))
        return driver

    monkeypatch.setattr(launcher, "build_driver", build)
    launcher.main(argv)
    assert built == [(usd, path)]
    driver.run.assert_called_once_with()


def test_main_requires_usd(launcher, monkeypatch):
    monkeypatch.setattr(launcher, "build_driver", lambda *a, **kw: pytest.fail("missing USD"))
    with pytest.raises(SystemExit) as exc:
        launcher.main([])
    assert exc.value.code not in (0, None)


def test_script_entrypoint_runs_driver_with_cli_usd(tmp_path):
    usd = tmp_path / "robot.usda"
    usd.touch()
    path = write_driver(tmp_path, """
class Robot(IsaacDriver):
    def run(self):
        print(f"[USER DRIVER] {self.USD}")
""")
    result = subprocess.run(
        [sys.executable, str(FRAMEWORK / "isaac_devkit/run_scene.py"),
         str(usd), "--driver", str(path)],
        env={**os.environ, "PYTHONPATH": str(FRAMEWORK)},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert f"[USER DRIVER] {usd}" in result.stdout.splitlines()
