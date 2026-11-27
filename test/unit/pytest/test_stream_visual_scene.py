"""Check the Kit --exec scene without importing omni or pxr on a hosted runner."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.stream

_SCENE = Path(__file__).resolve().parents[3] / "script/ci/visual_e2e/scene/min_scene.py"


def _scene():
    assert _SCENE.is_file(), "missing the stream image's --exec scene"
    return ast.parse(_SCENE.read_text())


def _calls(node):
    return {ast.unparse(call.func) for call in ast.walk(node) if isinstance(call, ast.Call)}


def test_stage_creation_waits_for_the_app_and_a_viewport():
    tree = _scene()
    create = next(call for call in ast.walk(tree) if isinstance(call, ast.Call)
                  and ast.unparse(call.func).endswith(".new_stage"))
    waits = [loop for loop in ast.walk(tree) if isinstance(loop, ast.While)
             and loop.end_lineno < create.lineno]
    assert any("get_active_viewport" in _calls(loop.test)
               and any(name.endswith(".is_app_ready") for name in _calls(loop.test))
               and any(name.endswith(".next_update_async") for name in _calls(loop))
               for loop in waits), "yield to Kit until both startup conditions are met"


def test_scene_has_the_known_content_and_uses_its_camera():
    tree = _scene()
    paths = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)}
    assert {"/World/RedCube", "/World/Floor"} <= paths
    calls = _calls(tree)
    assert {"UsdGeom.Cube.Define", "UsdGeom.Camera.Define"} <= calls
    assert {"UsdLux.DomeLight.Define", "UsdLux.DistantLight.Define"} & calls
    assert any(isinstance(n, ast.Attribute) and n.attr == "camera_path"
               and isinstance(n.ctx, ast.Store) for n in ast.walk(tree))
    colours = [ast.literal_eval(n) for n in ast.walk(tree)
               if isinstance(n, (ast.Tuple, ast.List)) and len(n.elts) == 3
               and all(isinstance(e, ast.Constant) for e in n.elts)]
    assert (1, 0, 0) in map(tuple, colours)
    assert any(0 < r == g == b < 1 for r, g, b in colours
               if all(isinstance(c, (float, int)) for c in (r, g, b)))
    cube = next(n.targets[0] for n in ast.walk(tree) if isinstance(n, ast.Assign)
                and isinstance(n.value, ast.Call) and ast.unparse(n.value.func) == "UsdGeom.Cube.Define"
                and any(isinstance(a, ast.Constant) and a.value == "/World/RedCube"
                        for a in n.value.args))
    assert any(isinstance(n, ast.Call)
               and ast.unparse(n.func) == f"{ast.unparse(cube)}.GetSizeAttr().Set"
               and len(n.args) == 1 and isinstance(n.args[0], ast.Constant)
               and n.args[0].value == 1 for n in ast.walk(tree))


def test_ready_marker_follows_a_stable_watch_and_rebuild_on_stage_replacement():
    # Run just the prototype's monitor coroutine. build_once represents Kit
    # stage construction; the fake app advances one frame per awaited update.
    monitor = next(n for n in _scene().body if isinstance(n, ast.AsyncFunctionDef)
                   and n.name == "build")
    builds = []
    ready = []
    frame = 0

    async def build_once():
        builds.append(frame)
        assert len(builds) <= 2, "rebuilt a stable stage"

    async def next_update():
        nonlocal frame
        frame += 1
        assert frame <= 1400, "stable scene never became ready"

    def get_prim(path):
        assert path == "/World/RedCube"
        return SimpleNamespace(IsValid=lambda: len(builds) == 2 or frame < 450)

    def record(message, **kwargs):
        if "[SBF] scene ready" in message:
            ready.append((len(builds), frame))

    ctx = SimpleNamespace(get_stage=lambda: SimpleNamespace(GetPrimAtPath=get_prim))
    app = SimpleNamespace(next_update_async=next_update)
    omni = SimpleNamespace(usd=SimpleNamespace(get_context=lambda: ctx),
                           kit=SimpleNamespace(app=SimpleNamespace(get_app=lambda: app)))
    namespace = {"omni": omni, "build_once": build_once, "print": record}
    exec(compile(ast.Module(body=[monitor], type_ignores=[]), str(_SCENE), "exec"), namespace)
    asyncio.run(namespace["build"]())
    assert len(builds) == 2
    assert len(ready) == 1
    count, announced = ready[0]
    assert count == 2 and 480 <= announced - builds[-1] <= 720
