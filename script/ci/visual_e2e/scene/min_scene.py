"""Build a lit red cube for the stream visual E2E and wait for a stable stage."""

import asyncio

import omni.kit.app
import omni.usd
from pxr import Gf, Sdf, UsdGeom, UsdLux, UsdShade


def material(stage, path, rgb):
    mat = UsdShade.Material.Define(stage, path)
    shader = UsdShade.Shader.Define(stage, path + "/Shader")
    shader.CreateIdAttr("UsdPreviewSurface")
    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*rgb))
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.6)
    mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
    return mat


async def build_once():
    from omni.kit.viewport.utility import get_active_viewport

    app = omni.kit.app.get_app()
    ctx = omni.usd.get_context()
    # Creating a stage before the viewport exists can stall Kit startup.
    while get_active_viewport() is None or not app.is_app_ready():
        await app.next_update_async()
    for _ in range(30):
        await app.next_update_async()
    ctx.new_stage()
    for _ in range(10):
        await app.next_update_async()
    stage = ctx.get_stage()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    world = UsdGeom.Xform.Define(stage, "/World")
    stage.SetDefaultPrim(world.GetPrim())

    floor = UsdGeom.Cube.Define(stage, "/World/Floor")
    floor.GetSizeAttr().Set(1.0)
    UsdGeom.XformCommonAPI(floor).SetScale(Gf.Vec3f(10, 10, 0.1))
    UsdGeom.XformCommonAPI(floor).SetTranslate(Gf.Vec3d(0, 0, -0.05))
    UsdShade.MaterialBindingAPI.Apply(floor.GetPrim()).Bind(
        material(stage, "/World/Looks/Grey", (0.5, 0.5, 0.5)))

    cube = UsdGeom.Cube.Define(stage, "/World/RedCube")
    cube.GetSizeAttr().Set(1.0)
    UsdGeom.XformCommonAPI(cube).SetTranslate(Gf.Vec3d(0, 0, 0.5))
    UsdShade.MaterialBindingAPI.Apply(cube.GetPrim()).Bind(
        material(stage, "/World/Looks/Red", (1.0, 0.0, 0.0)))

    dome = UsdLux.DomeLight.Define(stage, "/World/Dome")
    dome.CreateIntensityAttr(1000.0)
    sun = UsdLux.DistantLight.Define(stage, "/World/Sun")
    sun.CreateIntensityAttr(3000.0)
    UsdGeom.XformCommonAPI(sun).SetRotate(Gf.Vec3f(-50, 0, 30))

    cam = UsdGeom.Camera.Define(stage, "/World/Cam")
    view = Gf.Matrix4d().SetLookAt(
        Gf.Vec3d(4, -4, 3), Gf.Vec3d(0, 0, 0.5), Gf.Vec3d(0, 0, 1)
    )
    cam.AddTransformOp().Set(view.GetInverse())
    while get_active_viewport() is None:
        await app.next_update_async()
    get_active_viewport().camera_path = "/World/Cam"
    for _ in range(30):
        await app.next_update_async()


async def build():
    """Rebuild if Kit loads its default stage during the stability window."""
    app = omni.kit.app.get_app()
    for attempt in range(1, 6):
        await build_once()
        for _ in range(600):
            await app.next_update_async()
            stage = omni.usd.get_context().get_stage()
            if stage is None or not stage.GetPrimAtPath("/World/RedCube").IsValid():
                break
        else:
            print(f"[SBF] scene ready (build attempts={attempt})", flush=True)
            return
        print(f"[SBF] stage replaced after build {attempt}", flush=True)
    raise RuntimeError("stage replaced on every build attempt")


asyncio.ensure_future(build())
