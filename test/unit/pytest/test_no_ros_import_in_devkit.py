"""Guard the boundary between the devkit and downstream ROS I/O plugins."""

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

_PACKAGE_DIR = (
    Path(__file__).resolve().parents[3] / "framework" / "isaac_devkit"
)

_ROS_IMPORT_GUARD = textwrap.dedent("""\
    import sys
    from importlib.abc import MetaPathFinder

    class RosImportGuard(MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if (fullname.partition(".")[0] == "rclpy" or
                    fullname.startswith(("isaacsim.ros2", "rosidl_"))):
                raise ImportError(f"Blocked ROS import: {fullname}")
            return None

    sys.meta_path.insert(0, RosImportGuard())
""")


def _is_banned(name):
    root = name.partition(".")[0]
    return (
        root in ("rclpy", "builtin_interfaces")
        or root.startswith("rosidl_")
        or name == "isaacsim.ros2"
        or name.startswith("isaacsim.ros2.")
    )


def _module_top_ros_imports(source):
    """Return ``(lineno, name)`` of banned imports at module level."""
    offenders = []
    for node in ast.parse(source).body:
        if isinstance(node, ast.Import):
            offenders += [
                (node.lineno, a.name) for a in node.names if _is_banned(a.name)
            ]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _is_banned(module):
                offenders.append((node.lineno, module))
    return offenders


@pytest.mark.parametrize(
    "module_file", sorted(_PACKAGE_DIR.rglob("*.py")), ids=lambda p: p.name
)
def test_no_ros_dependencies_in_source(module_file):
    source = module_file.read_text(encoding="utf-8")
    for lineno, line in enumerate(source.splitlines(), start=1):
        assert "rclpy" not in line and "isaacsim.ros2" not in line, (
            f"{module_file.name}:{lineno}: {line}"
        )
    offenders = _module_top_ros_imports(source)
    assert offenders == [], (
        f"{module_file.name} has module-top ROS imports: {offenders}"
    )


@pytest.mark.parametrize(
    "line",
    [
        "import rclpy",
        "from rclpy.node import Node",
        "from rosidl_runtime_py import message_to_ordereddict",
        "from builtin_interfaces.msg import Time",
        "import isaacsim.ros2.bridge",
        "from isaacsim.ros2.bridge import ROS2Context",
    ],
)
def test_detector_flags_ros_imports(line):
    assert _module_top_ros_imports(line + "\n") != []


def test_detector_ignores_unrelated_imports():
    src = "import os\nfrom pathlib import Path\n"
    assert _module_top_ros_imports(src) == []


def test_importing_entire_devkit_leaves_process_ros_free():
    probe = _ROS_IMPORT_GUARD + textwrap.dedent("""\
        import importlib
        import pkgutil

        def check_modules(after):
            leaked = sorted(name for name in sys.modules if
                            name.partition(".")[0] == "rclpy" or
                            name.startswith(("isaacsim.ros2", "rosidl_")))
            if leaked:
                raise RuntimeError(f"{after} loaded ROS modules: {leaked}")

        sys.path.insert(0, sys.argv[1])
        import isaac_devkit
        check_modules(isaac_devkit.__name__)
        for module in pkgutil.walk_packages(isaac_devkit.__path__, "isaac_devkit."):
            importlib.import_module(module.name)
            check_modules(module.name)
    """)
    result = subprocess.run(
        [sys.executable, "-c", probe, str(_PACKAGE_DIR.parent)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_import_guard_blocks_ros_dependency(tmp_path):
    package = tmp_path / "ros_dependent"
    package.mkdir()
    (package / "__init__.py").write_text("import rclpy\n", encoding="utf-8")
    probe = _ROS_IMPORT_GUARD + "import ros_dependent\n"
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=tmp_path,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert "ImportError: Blocked ROS import: rclpy" in result.stderr, result.stderr


def test_default_boot_extensions_do_not_request_ros(monkeypatch):
    monkeypatch.syspath_prepend(str(_PACKAGE_DIR.parent))
    from isaac_devkit import IsaacDriver

    assert not any("ros2" in name.lower() for name in IsaacDriver.BOOT_EXTENSIONS)


@pytest.mark.parametrize("name", ["ros_io", "sensor_ros"])
def test_builtin_ros_module_is_removed(name):
    assert not (_PACKAGE_DIR / f"{name}.py").exists()


@pytest.mark.parametrize("name", ["setup_ros2_io", "RosIo", "Msg"])
def test_package_does_not_export_ros_io(name, monkeypatch):
    monkeypatch.syspath_prepend(str(_PACKAGE_DIR.parent))
    import isaac_devkit

    assert not hasattr(isaac_devkit, name)
    assert name not in isaac_devkit.__all__
