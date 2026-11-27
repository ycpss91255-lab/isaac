"""Output-mode resolver (isaac#514).

``ISAAC_OUTPUT_MODE`` defaults to ``python`` for Python callbacks.
Any other explicit value raises ValueError.
"""

import sys
from pathlib import Path

import pytest

_FRAMEWORK_DIR = Path(__file__).resolve().parents[3] / "framework"
sys.path.insert(0, str(_FRAMEWORK_DIR))

from isaac_devkit.output_mode import (  # noqa: E402
    DEFAULT_MODE,
    ENV_VAR,
    MODES,
    resolve_output_mode,
)

pytestmark = pytest.mark.core


def test_unset_defaults_to_python():
    assert resolve_output_mode({}) == "python"


@pytest.mark.parametrize("value", ["python"])
def test_valid_values_pass_through(value):
    assert resolve_output_mode({"ISAAC_OUTPUT_MODE": value}) == value


@pytest.mark.parametrize("value", ["ros", "ROS", "Python", "", "both", " ros", "ros "])
def test_invalid_values_raise_naming_value_and_allowed_set(value):
    with pytest.raises(ValueError) as exc:
        resolve_output_mode({"ISAAC_OUTPUT_MODE": value})
    msg = str(exc.value)
    assert repr(value) in msg
    assert "ISAAC_OUTPUT_MODE" in msg
    assert "'python'" in msg
    assert "'ros'" not in msg.replace(repr(value), "", 1)


def test_other_variables_are_ignored():
    assert resolve_output_mode({"ISAAC_LIVESTREAM": "1"}) == "python"


def test_reads_os_environ_by_default(monkeypatch):
    monkeypatch.setenv("ISAAC_OUTPUT_MODE", "ros")
    with pytest.raises(ValueError, match="ISAAC_OUTPUT_MODE"):
        resolve_output_mode()
    monkeypatch.delenv("ISAAC_OUTPUT_MODE")
    assert resolve_output_mode() == "python"


def test_constants():
    assert ENV_VAR == "ISAAC_OUTPUT_MODE"
    assert set(MODES) == {"python"}
    assert DEFAULT_MODE == "python"
