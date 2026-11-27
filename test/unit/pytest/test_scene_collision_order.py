"""Host-side tests for collision overrides on referenced models."""

import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "framework"))
from isaac_devkit import scene

pytestmark = pytest.mark.core


class _PrimRange:
    """Depth-first iterator over a fake prim tree with USD-style pruning."""

    def __init__(self, root):
        self._pending = [root]
        self._children = ()

    def __iter__(self):
        return self

    def __next__(self):
        self._pending.extend(reversed(self._children))
        if not self._pending:
            raise StopIteration
        prim = self._pending.pop()
        self._children = prim.children
        return prim

    def PruneChildren(self):
        self._children = ()


def _prim(*children):
    prim = Mock(children=children, schemas=set(), properties={})
    prim.HasAPI.side_effect = prim.schemas.__contains__
    return prim


@pytest.mark.parametrize("has_colliders", [True, False], ids=["colliders", "geometry_only"])
def test_collision_override_targets(monkeypatch, has_colliders):
    pxr = Mock()
    monkeypatch.setitem(sys.modules, "pxr", pxr)
    pxr.Usd.PrimRange.side_effect = _PrimRange
    collision = pxr.UsdPhysics.CollisionAPI
    collision.Apply.side_effect = lambda prim: prim.schemas.add(collision)

    def set_properties(prim, schema, props, physx_schema):
        schema.Apply(prim)
        prim.properties.update(props)

    monkeypatch.setattr(scene, "_set_physics_properties", set_properties)
    nested = _prim()
    left, right = _prim(nested), _prim()
    root = _prim(left, right)
    if has_colliders:
        for prim in (left, nested, right):
            prim.schemas.add(collision)
    stage = Mock()
    stage.GetPrimAtPath.return_value = root
    props = {"rest_offset": 0.001}
    spec = scene.SpawnSpec(
        prim_path="/Object",
        kind="usd",
        kwargs={"usd_path": "asset.usd", "collision_props": props},
        translation=(0, 0, 0),
        orientation=(1, 0, 0, 0),
        mobility="static",
    )

    scene._spawn_prim(stage, spec)

    assert root.HasAPI(collision)
    assert root.properties == ({} if has_colliders else props)
    assert left.properties == right.properties == (props if has_colliders else {})
    assert nested.properties == {}
