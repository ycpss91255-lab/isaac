"""Host-side contract for scene and usd_model joint-drive gains."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "framework"))
from isaac_devkit import scene, usd_model

pytestmark = pytest.mark.core

INVALID_GAINS = [(800, None), (None, 40), (-1, 40), (800, -1)]


def test_resolve_joint_drive_gains_allows_omitted_pair():
    assert scene.resolve_joint_drive_gains(None, None) is None
    assert usd_model._resolve_joint_drive_gains(None, None) is None


@pytest.mark.parametrize(
    "stiffness,damping,expected", [("800", "40", (800.0, 40.0)), (0, 0, (0.0, 0.0))]
)
def test_resolve_joint_drive_gains_returns_float_pair(stiffness, damping, expected):
    for resolve in (scene.resolve_joint_drive_gains, usd_model._resolve_joint_drive_gains):
        gains = resolve(stiffness, damping)
        assert gains == expected
        assert all(isinstance(gain, float) for gain in gains)


@pytest.mark.parametrize("stiffness,damping", INVALID_GAINS)
def test_resolve_joint_drive_gains_rejects_invalid_pair(stiffness, damping):
    for resolve in (scene.resolve_joint_drive_gains, usd_model._resolve_joint_drive_gains):
        with pytest.raises(ValueError):
            resolve(stiffness, damping)


@pytest.mark.parametrize("stiffness,damping", [(None, None), *INVALID_GAINS])
def test_apply_joint_drive_rejects_invalid_gains_before_stage_access(stiffness, damping):
    with pytest.raises(ValueError):
        scene.apply_joint_drive("/World/Joint", stiffness, damping, stage=object())
