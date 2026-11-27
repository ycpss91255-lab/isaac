"""Import-safety invariant for isaac_devkit (ADR-0017 section 8 / PRD A1).

Hosted (no Isaac Sim installed): import every ``isaac_devkit`` module --
including the package ``__init__`` re-export surface -- and assert that
after each import ``sys.modules`` contains none of ``omni`` / ``pxr`` /
``isaacsim`` / ``isaaclab``. "Import succeeded" alone is not sufficient: a module-top
``import omni`` inside a try/except would pass a plain import check on a
host where the import fails, yet still leak Isaac modules inside the
container. The companion static guard is the ruff TID253 rule in
``framework/pyproject.toml``.

Red state note (isaac#130 scaffold): the six module cases fail with
``ModuleNotFoundError`` until each module lands; the package and
``exceptions`` cases pass from the scaffold commit onward.
"""

import ast
import importlib
import inspect
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

_FRAMEWORK_DIR = Path(__file__).resolve().parents[3] / "framework"
sys.path.insert(0, str(_FRAMEWORK_DIR))

# Top-level Isaac namespaces that must never be imported at module top
# anywhere in the package (function-local imports only).
_ISAAC_TOP_LEVEL = ("omni", "pxr", "isaacsim", "isaaclab")

# Every module of the package, plus the package itself (its curated
# __init__ re-export surface must also stay pure).
_DEVKIT_MODULES = (
    "isaac_devkit",
    "isaac_devkit.exceptions",
    "isaac_devkit.model_import",
    "isaac_devkit.materials",
    "isaac_devkit.sensors",
    "isaac_devkit.ros_io",
    "isaac_devkit.scene",
    "isaac_devkit.driver",
    "isaac_devkit.sim_version",
    "isaac_devkit.stamp",
    "isaac_devkit.buffers",
    "isaac_devkit.output_mode",
    "isaac_devkit.output_hub",
    "isaac_devkit.output",
    "isaac_devkit.output_python",
)


def _leaked_isaac_modules():
    """Return sorted Isaac module names currently present in sys.modules."""
    return sorted(
        name
        for name in sys.modules
        if name.partition(".")[0] in _ISAAC_TOP_LEVEL
    )


@pytest.mark.parametrize("module_name", _DEVKIT_MODULES)
def test_hosted_import_leaves_sys_modules_isaac_free(module_name):
    """Hosted import of each devkit module must not pull in Isaac modules."""
    module = importlib.import_module(module_name)
    assert module is not None

    leaked = _leaked_isaac_modules()
    assert leaked == [], (
        f"hosted import of {module_name!r} leaked Isaac modules into "
        f"sys.modules: {leaked}; every Isaac import must be "
        "function-local (ADR-0017 section 8)"
    )


def _assert_no_isaaclab_imports(module):
    """Check function-local imports too, since spawning needs to work without Lab."""
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert name.partition(".")[0] != "isaaclab", (
                f"{module.__name__}:{node.lineno} imports {name}"
            )


def test_scene_has_no_isaaclab_imports():
    from isaac_devkit import scene

    _assert_no_isaaclab_imports(scene)


def test_joint_drive_reexport_is_host_safe_and_independent_of_isaaclab():
    from isaac_devkit import model_import

    apply_joint_drive = model_import.apply_joint_drive
    assert callable(apply_joint_drive)
    owner = importlib.import_module(apply_joint_drive.__module__)
    assert owner.__name__.startswith("isaac_devkit.")
    assert owner is not model_import, "model_import must re-export the scene-side helper"
    assert owner.apply_joint_drive is apply_joint_drive
    assert _leaked_isaac_modules() == []
    _assert_no_isaaclab_imports(owner)
