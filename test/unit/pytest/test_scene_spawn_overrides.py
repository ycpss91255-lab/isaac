"""Host-side tests for physics properties and top-level spawn overrides."""

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "framework"))
from isaac_devkit import scene

pytestmark = pytest.mark.core


def _prim(attributes):
    prim = Mock()
    prim.GetPath.return_value = "/Object"
    prim.GetAttribute.side_effect = attributes.get
    return prim


def test_set_physics_properties_sets_value_and_skips_none():
    enabled = Mock()
    kinematic = Mock()
    prim = _prim({
        "physics:rigidBodyEnabled": enabled,
        "physics:kinematicEnabled": kinematic,
    })

    scene._set_physics_properties(
        prim, Mock(), {"kinematic_enabled": None, "rigid_body_enabled": False}
    )

    enabled.Set.assert_called_once_with(False)
    kinematic.Set.assert_not_called()


def test_set_physics_properties_rejects_unknown_key():
    prim = _prim({})
    schema = Mock(__name__="CollisionAPI")

    with pytest.raises(ValueError) as exc_info:
        scene._set_physics_properties(prim, schema, {"unknown_offset": 0.1})

    message = str(exc_info.value)
    assert "unknown_offset" in message
    assert "/Object" in message


def test_set_physics_properties_applies_physx_schema():
    contact_offset = Mock()
    prim = _prim({"physxCollision:contactOffset": contact_offset})

    scene._set_physics_properties(
        prim, Mock(), {"contact_offset": 0.02}, physx_schema="PhysxCollisionAPI"
    )

    prim.AddAppliedSchema.assert_called_once_with("PhysxCollisionAPI")
    contact_offset.Set.assert_called_once_with(0.02)


@pytest.fixture
def stage(monkeypatch):
    pxr = Mock()
    monkeypatch.setitem(sys.modules, "pxr", pxr)
    stage = Mock()
    prim = _prim({"physxCollision:restOffset": Mock()})
    prim.HasAPI.return_value = False
    stage.GetPrimAtPath.return_value = prim
    pxr.Usd.PrimRange.return_value = [prim]
    return stage


def _usd_spec(**overrides):
    return scene.SpawnSpec(
        prim_path="/Object",
        kind="usd",
        kwargs={"usd_path": "asset.usd", **overrides},
        translation=(0, 0, 0),
        orientation=(1, 0, 0, 0),
        mobility="static",
    )


def test_spawn_prim_rejects_unsupported_option(stage):
    with pytest.raises(ValueError) as exc_info:
        scene._spawn_prim(stage, _usd_spec(bogus_option=1))

    message = str(exc_info.value)
    assert "Unsupported spawn overrides" in message
    assert "bogus_option" in message


def test_spawn_prim_sets_collision_rest_offset(stage):
    scene._spawn_prim(stage, _usd_spec(collision_props={"rest_offset": 0.001}))

    prim = stage.GetPrimAtPath("/Object")
    prim.GetAttribute("physxCollision:restOffset").Set.assert_called_once_with(0.001)
