"""Load the shared group guard and GPU timing hooks."""

import importlib.util
from pathlib import Path


def _load(name):
    path = Path(__file__).resolve().parents[2] / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_markers = _load("group_markers")
_timing = _load("kit_timing")

pytest_configure = _markers.pytest_configure
pytest_collection_modifyitems = _markers.pytest_collection_modifyitems
pytest_runtest_protocol = _timing.pytest_runtest_protocol
pytest_terminal_summary = _timing.pytest_terminal_summary
