"""Declarative scene composition from YAML.

``to_scene_specs`` resolves a validated scene into JSON-serializable spawn
specifications. ``build_scene`` authors those specifications on a USD stage.
Stage access and USD schema imports are local to the runtime functions.

Usage from an IsaacDriver subclass:

    from isaac_devkit.scene import load_scene, build_scene
    scene = load_scene("scene/sensor_test_bench.yaml", repo_root)
    build_scene(scene, stage, repo_root)
"""

import math
import os
from pathlib import Path
from typing import NamedTuple, Optional

import yaml


class SpawnSpec(NamedTuple):
    """A neutral, GPU-free description of one prim to spawn.

    Fields:
        prim_path: USD prim path the spec spawns at (e.g. "/World/Robot").
        kind: One of "ground_plane", "distant_light", "usd".
        kwargs: Spawn parameters (incl. any
            ``spawn_overrides`` and, for "usd", ``usd_path``).
        translation: (x, y, z) in meters.
        orientation: (w, x, y, z) quaternion.
        mobility: "dynamic" / "static" / None (physics-prop selection for
            "usd" specs; ignored for environment specs).
    """

    prim_path: str
    kind: str
    kwargs: dict
    translation: tuple
    orientation: tuple
    mobility: Optional[str]


def load_scene(path, repo_root):
    """Load and validate a Scene YAML config."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"scene config not found: {p}")
    with p.open() as f:
        scene = yaml.safe_load(f)
    _validate_scene(scene, source=str(p))
    return scene


def _validate_scene(scene, source):
    if "robot" not in scene:
        raise ValueError(f"{source}: missing 'robot' section")

    robot = scene["robot"]
    if "model" not in robot:
        raise ValueError(f"{source}: robot needs 'model'")
    if "pose" not in robot:
        raise ValueError(f"{source}: robot needs 'pose'")

    for i, obj in enumerate(scene.get("objects", [])):
        if "model" not in obj:
            raise ValueError(f"{source}: objects[{i}] needs 'model'")
        if "pose" not in obj:
            raise ValueError(f"{source}: objects[{i}] needs 'pose'")


def _model_search_roots(repo_root):
    """Return the list of directories to search for relative model paths.

    When the ``MODEL_PATH`` environment variable is set, its colon-separated
    entries are searched in order. Otherwise, the legacy
    ``<repo_root>/model/usd/`` directory is used as the sole search root so
    that existing callers continue to work without any configuration.
    """
    env = os.environ.get("MODEL_PATH", "")
    if env:
        return [Path(p) for p in env.split(":") if p]
    return [Path(repo_root) / "model" / "usd"]


def _resolve_package_uri(uri, roots):
    """Resolve a ``package://<pkg>/<rel>`` URI under the MODEL_PATH roots.

    Use the first root containing both the package manifest and the target file.

    PURE apart from filesystem existence checks -- no Isaac import.

    Raises:
        FileNotFoundError: naming the package and listing the searched roots.
    """
    # "package://my_pkg/usd/robot.usd" -> pkg="my_pkg", rel="usd/robot.usd"
    stripped = uri[len("package://"):]
    pkg, _, rel = stripped.partition("/")
    if not pkg or not rel:
        raise FileNotFoundError(
            f"malformed package URI: '{uri}' "
            "(expected package://<package>/<path>)"
        )

    for root in roots:
        pkg_dir = root / pkg
        if (pkg_dir / "package.xml").is_file():
            candidate = pkg_dir / rel
            if candidate.exists():
                return candidate

    searched = ", ".join(str(r) for r in roots)
    raise FileNotFoundError(
        f"model not found: package '{pkg}' (from '{uri}') not resolved "
        f"under any search root (searched: {searched})"
    )


def resolve_model_path(model_rel, repo_root):
    """Resolve a model path to absolute using the MODEL_PATH search roots.

    Accepted forms:

    * **absolute path** -- returned as-is if it exists.
    * **package:// URI** -- ``package://<pkg>/<rel>`` is resolved by
      scanning each MODEL_PATH root for a ``<pkg>/`` directory that
      carries a ``package.xml``.
    * **relative path** -- searched under each MODEL_PATH root (or the
      legacy ``<repo_root>/model/usd/`` fallback).

    As a transition shim the function also accepts a relative path that
    already carries the ``model/usd/`` segment; it strips the prefix
    before searching so that the same relative tail is looked up
    everywhere.

    Raises:
        FileNotFoundError: with a message that lists every root searched.
    """
    model_rel = str(model_rel)

    # Absolute paths bypass the search entirely.
    if os.path.isabs(model_rel):
        p = Path(model_rel)
        if p.exists():
            return p
        raise FileNotFoundError(f"model not found: {p}")

    roots = _model_search_roots(repo_root)

    # package:// URIs are resolved via package.xml scanning.
    if model_rel.startswith("package://"):
        return _resolve_package_uri(model_rel, roots)

    # Strip the legacy prefix so the search root can vary.
    rel = model_rel
    if rel.startswith("model/usd/"):
        rel = rel[len("model/usd/"):]

    for root in roots:
        candidate = root / rel
        if candidate.exists():
            return candidate

    searched = ", ".join(str(r) for r in roots)
    raise FileNotFoundError(
        f"model not found: '{rel}' not in any search root "
        f"(searched: {searched})"
    )


def generate_instances(entry):
    """Expand a single object entry into N instances with spacing applied.

    Returns a list of dicts, each with 'model', 'pose', and optionally
    'variant'. Curated extras the adapter forwards (``mobility``,
    ``spawn_overrides``, ``material``) are carried through unchanged so a
    multi-instance object behaves like its single-instance form. The
    original entry is not modified.
    """
    count = entry.get("count", 1)
    spacing = entry.get("spacing", [0, 0, 0])
    base_xyz = list(entry["pose"]["xyz"])
    rpy = entry["pose"]["rpy"]
    variant = entry.get("variant")
    model = entry["model"]

    instances = []
    for i in range(count):
        xyz = [
            base_xyz[0] + spacing[0] * i,
            base_xyz[1] + spacing[1] * i,
            base_xyz[2] + spacing[2] * i,
        ]
        inst = {
            "model": model,
            "pose": {"xyz": xyz, "rpy": list(rpy)},
        }
        if variant is not None:
            inst["variant"] = variant
        for key in ("mobility", "spawn_overrides", "material"):
            if key in entry:
                inst[key] = entry[key]
        instances.append(inst)
    return instances


def resolve_sensor_configs(scene, repo_root):
    """Resolve sensor config paths relative to repo root.

    Returns a list of absolute Path objects for each sensor YAML.
    """
    sensor_refs = scene.get("sensors", [])
    resolved = []
    for ref in sensor_refs:
        p = Path(repo_root) / ref
        if not p.exists():
            raise FileNotFoundError(
                f"sensor config not found: {p} (from ref='{ref}')"
            )
        resolved.append(p)
    return resolved


def rpy_to_quat(rpy_deg):
    """Convert roll/pitch/yaw degrees to a (w, x, y, z) quaternion.

    Rotation order is XYZ intrinsic (roll about X, then pitch about Y,
    then yaw about Z), matching the old ``UsdGeom.AddRotateXYZOp`` the
    raw-pxr path used. Pure math (no numpy): each axis rotation is a
    quaternion and they are composed q = qz * qy * qx so that, read as
    intrinsic body-frame rotations, X is applied first.

    Args:
        rpy_deg: (roll, pitch, yaw) in degrees.

    Returns:
        (w, x, y, z) unit quaternion tuple of floats.
    """
    roll, pitch, yaw = (math.radians(float(a)) for a in rpy_deg)
    cr, sr = math.cos(roll / 2.0), math.sin(roll / 2.0)
    cp, sp = math.cos(pitch / 2.0), math.sin(pitch / 2.0)
    cy, sy = math.cos(yaw / 2.0), math.sin(yaw / 2.0)

    # q = qz * qy * qx (XYZ intrinsic; X applied first).
    w = cr * cp * cy + sr * sp * sy
    x = sr * cp * cy - cr * sp * sy
    y = cr * sp * cy + sr * cp * sy
    z = cr * cp * sy - sr * sp * cy
    return (w, x, y, z)


def _material_diffuse_for(entry, repo_root):
    """Return an (r, g, b) diffuse color for an entry, or None.

    The entry may carry a ``material`` key pointing to a material YAML
    (repo-relative) plus an optional ``variant`` selection. We reuse the
    pure ``materials.material_cfg_from_yaml`` mapper (#153) and take the
    diffuse color of the FIRST prim that declares one -- the minimal hook
    so ``build_scene`` can author a USD preview surface. Full per-prim
    material GPU coverage is #154. No material key -> None (skip).
    """
    material_rel = entry.get("material")
    if not material_rel:
        return None

    from isaac_devkit.materials import (
        load_material_config,
        material_cfg_from_yaml,
    )

    material_path = Path(repo_root) / material_rel
    cfg = load_material_config(material_path)
    variant = entry.get("variant")
    if isinstance(variant, dict):
        # A variant dict (e.g. {"color": "blue"}) selects by its value.
        variant = next(iter(variant.values()), None)
    spawn_cfg = material_cfg_from_yaml(cfg, variant=variant)
    for props in spawn_cfg.values():
        if "diffuse_color" in props:
            return tuple(props["diffuse_color"])
    return None


def _usd_spec(prim_path, entry, usd_abs, repo_root, mobility=None):
    """Build a "usd" SpawnSpec from a curated entry + resolved USD path.

    Curated -> kwargs: ``model`` -> ``usd_path`` (the absolute path str),
    ``pose.xyz`` -> ``translation``, ``pose.rpy`` (deg) -> ``orientation``
    quaternion, ``variant`` -> ``variants`` kwarg (structurally-distinct
    variant selection, ADR-0018 decision 7), and an optional material
    diffuse color recorded under ``visual_material_diffuse``.

    ``spawn_overrides`` (raw passthrough) is spread onto kwargs LAST so
    overrides win over curated fields (intentional power-user control,
    ADR-0018 decision 3).
    """
    pose = entry["pose"]
    kwargs = {"usd_path": str(usd_abs)}

    variant = entry.get("variant")
    if variant is not None:
        kwargs["variants"] = variant

    diffuse = _material_diffuse_for(entry, repo_root)
    if diffuse is not None:
        kwargs["visual_material_diffuse"] = diffuse

    # Raw passthrough wins over curated fields (overrides-win).
    kwargs.update(entry.get("spawn_overrides", {}))

    return SpawnSpec(
        prim_path=prim_path,
        kind="usd",
        kwargs=kwargs,
        translation=tuple(float(c) for c in pose["xyz"]),
        orientation=rpy_to_quat(pose["rpy"]),
        mobility=mobility,
    )


def to_scene_specs(scene, repo_root):
    """Map a validated scene dict to a neutral list of ``SpawnSpec``.

    PURE: imports no Isaac module. Emits, in order:

    1. environment ground plane (if ``environment.ground_plane`` truthy)
       at ``/World/ground``;
    2. a distant light at ``/World/light`` from ``environment.light``
       (curated optional ``intensity`` / ``color`` / ``angle``); if
       ``environment.light`` is absent its intensity defaults to 3000;
    3. the robot USD at ``/World/Robot``;
    4. one USD spec per object instance at
       ``/World/Objects/<modelstem>_<idx>_<instidx>``, carrying mobility.

    ``spawn_overrides`` on any entry is spread onto that spec's kwargs
    (overrides-win). The returned list is the stable seam (ADR-0018
    decision 1): a hosted unit test asserts on it without a live stage.
    """
    specs = []

    environment = scene.get("environment", {}) or {}
    if environment.get("ground_plane"):
        ground_kwargs = dict(environment.get("ground_overrides", {}))
        specs.append(
            SpawnSpec(
                prim_path="/World/ground",
                kind="ground_plane",
                kwargs=ground_kwargs,
                translation=(0.0, 0.0, 0.0),
                orientation=(1.0, 0.0, 0.0, 0.0),
                mobility=None,
            )
        )

    light = environment.get("light")
    light_kwargs = {}
    if isinstance(light, dict):
        for key in ("intensity", "color", "angle"):
            if key in light:
                light_kwargs[key] = light[key]
        light_kwargs.update(light.get("spawn_overrides", {}))
    else:
        # Default SunLight: enough to keep headless debug renders readable.
        light_kwargs = {"intensity": 3000.0}
    specs.append(
        SpawnSpec(
            prim_path="/World/light",
            kind="distant_light",
            kwargs=light_kwargs,
            translation=(0.0, 0.0, 10.0),
            orientation=(1.0, 0.0, 0.0, 0.0),
            mobility=None,
        )
    )

    robot = scene["robot"]
    robot_usd = resolve_model_path(robot["model"], repo_root)
    specs.append(
        _usd_spec("/World/Robot", robot, robot_usd, repo_root, robot.get("mobility"))
    )

    for idx, obj_entry in enumerate(scene.get("objects", [])):
        instances = generate_instances(obj_entry)
        for inst_idx, inst in enumerate(instances):
            obj_usd = resolve_model_path(inst["model"], repo_root)
            prim_name = Path(inst["model"]).stem
            prim_path = f"/World/Objects/{prim_name}_{idx}_{inst_idx}"
            specs.append(
                _usd_spec(
                    prim_path,
                    inst,
                    obj_usd,
                    repo_root,
                    mobility=inst.get("mobility"),
                )
            )

    return specs


def _orientation_xyzw(wxyz):
    """Reorder a scalar-first quaternion for callers using scalar-last order."""
    w, x, y, z = wxyz
    return (x, y, z, w)


def _set_spawn_pose(prim, translation, orientation, scale=None):
    """Set the canonical translate/orient/scale stack, retaining asset precision."""
    from pxr import Gf, UsdGeom

    xform = UsdGeom.Xformable(prim)
    if scale is None and prim.HasAttribute("xformOp:scale"):
        scale = Gf.Transform(xform.GetLocalTransformation()).GetScale()
        units = prim.GetAttribute("xformOp:scale:unitsResolve")
        if units:
            scale = Gf.CompMult(scale, Gf.Vec3d(units.Get()))
    values = (
        ("translate", Gf.Vec3d(*translation), xform.AddTranslateOp),
        ("orient", Gf.Quatd(*orientation), xform.AddOrientOp),
        ("scale", Gf.Vec3d(*(scale or (1, 1, 1))), xform.AddScaleOp),
    )
    reset = xform.GetResetXformStack()
    ops = []
    for name, value, add_op in values:
        attr = prim.GetAttribute("xformOp:" + name)
        op = UsdGeom.XformOp(attr) if attr else add_op(UsdGeom.XformOp.PrecisionDouble)
        op.Set(op.GetAttr().GetTypeName().type.pythonClass(value))
        ops.append(op)
    xform.SetXformOpOrder(ops, reset)


def _set_physics_properties(prim, schema, properties, physx_schema=None):
    """Apply a physics schema and set the supplied snake_case properties."""
    schema.Apply(prim)
    for key, value in properties.items():
        if value is None:
            continue
        name = "".join(word.title() for word in key.split("_"))
        attr_name = name[0].lower() + name[1:]
        attr = prim.GetAttribute("physics:" + attr_name)
        if not attr and physx_schema:
            namespace = physx_schema.removesuffix("API")
            prim.AddAppliedSchema(physx_schema)
            attr = prim.GetAttribute(namespace[0].lower() + namespace[1:] + ":" + attr_name)
        if not attr:
            raise ValueError(f"Unknown {schema.__name__} property {key!r} on {prim.GetPath()}")
        attr.Set(value)


def _bind_spawn_materials(prim, directory, options):
    """Build the preview shader and physics material only when requested."""
    from pxr import Gf, Sdf, Usd, UsdPhysics, UsdShade

    stage = prim.GetStage()
    visual = options.pop("visual_material", None)
    diffuse = options.pop("visual_material_diffuse", None)
    if diffuse is not None:
        visual = {"diffuse_color": diffuse, **(visual or {})}
    visual_path = options.pop("visual_material_path", "material")
    if visual is not None:
        visual_path = Sdf.Path(visual_path).MakeAbsolutePath(directory)
        material = UsdShade.Material.Define(stage, visual_path)
        shader = UsdShade.Shader.Define(stage, visual_path.AppendChild("Shader"))
        shader.CreateIdAttr("UsdPreviewSurface")
        for output in (material.CreateSurfaceOutput(), material.CreateDisplacementOutput()):
            output.ConnectToSource(shader.CreateOutput(output.GetBaseName(), Sdf.ValueTypeNames.Token))
        inputs = {
            "diffuse_color": (0.18,) * 3,
            "emissive_color": (0.0,) * 3,
            "roughness": 0.5,
            "metallic": 0.0,
            "opacity": 1.0,
        }
        inputs.update(visual)
        for key, value in inputs.items():
            if value is None:
                continue
            name = key.replace("_color", "Color")
            if name.endswith("Color"):
                shader.CreateInput(name, Sdf.ValueTypeNames.Float3).Set(Gf.Vec3f(*value))
            else:
                shader.CreateInput(name, Sdf.ValueTypeNames.Float).Set(float(value))
        UsdShade.MaterialBindingAPI.Apply(prim).Bind(material, UsdShade.Tokens.strongerThanDescendants)

    physics = options.pop("physics_material", None)
    physics_path = options.pop("physics_material_path", "material")
    if physics is not None:
        physics_path = Sdf.Path(physics_path).MakeAbsolutePath(directory)
        material = UsdShade.Material.Define(stage, physics_path)
        properties = dict(static_friction=0.5, dynamic_friction=0.5, restitution=0.0)
        properties.update(physics)
        _set_physics_properties(material.GetPrim(), UsdPhysics.MaterialAPI, properties, "PhysxMaterialAPI")
        targets = iter(Usd.PrimRange(prim))
        for target in targets:
            if target.HasAPI(UsdPhysics.CollisionAPI):
                UsdShade.MaterialBindingAPI.Apply(target).Bind(
                    material, UsdShade.Tokens.strongerThanDescendants, "physics"
                )
                targets.PruneChildren()


def _spawn_light(stage, spec, options):
    from pxr import Gf, Sdf, UsdLux

    prim = stage.DefinePrim(spec.prim_path, options.pop("prim_type", "DistantLight"))
    light = UsdLux.LightAPI(prim)
    _set_spawn_pose(prim, spec.translation, spec.orientation)
    for key, default, attribute in (
        ("intensity", 1.0, light.CreateIntensityAttr),
        ("exposure", 0.0, light.CreateExposureAttr),
        ("normalize", False, light.CreateNormalizeAttr),
        ("enable_color_temperature", False, light.CreateEnableColorTemperatureAttr),
        ("color_temperature", 6500.0, light.CreateColorTemperatureAttr),
    ):
        value = options.pop(key, default)
        if value is not None:
            attribute(value)
    angle = options.pop("angle", 0.53)
    if angle is not None:
        prim.CreateAttribute("inputs:angle", Sdf.ValueTypeNames.Float, custom=False).Set(angle)
    color = options.pop("color", (1, 1, 1))
    if color is not None:
        light.CreateColorAttr(Gf.Vec3f(*color))
    return prim


def _spawn_reference(stage, spec, options):
    from pxr import Usd, UsdGeom

    path = spec.prim_path
    prim = stage.GetPrimAtPath(path)
    usd_path = options.pop("usd_path")
    scale = options.pop("scale", None)
    if not prim:
        if not stage.ResolveIdentifierToEditTarget(usd_path):
            raise FileNotFoundError(f"USD reference not found: {usd_path}")
        prim = UsdGeom.Xform.Define(stage, path).GetPrim()
        prim.GetReferences().AddReference(usd_path)
        _set_spawn_pose(prim, spec.translation, spec.orientation, scale)
    sets = prim.GetVariantSets()
    variants = options.pop("variants", None) or {}
    if isinstance(variants, str):
        # A material YAML also accepts a scalar color variant.
        names = sets.GetNames()
        if len(names) > 1:
            raise ValueError(f"Specify the variant set for {path}: {names}")
        variants = {names[0]: variants} if names else {}
    for name, selection in variants.items():
        if sets.HasVariantSet(name):
            variant = sets.GetVariantSet(name)
            if selection not in variant.GetVariantNames():
                raise ValueError(f"Unknown selection {selection!r} for {path} variant {name!r}")
            variant.SetVariantSelection(selection)
    if options.pop("make_uninstanceable", False):
        for child in Usd.PrimRange(prim):
            if child.IsInstance():
                child.SetInstanceable(False)
    return prim


def _spawn_prim(stage, spec):
    """Author one environment prim or referenced model and its spawn overrides."""
    from pxr import Sdf, Usd, UsdGeom, UsdPhysics, UsdShade

    path = spec.prim_path
    options = spec.kwargs.copy()
    if stage.GetPrimAtPath(path) and "usd_path" not in options:
        raise ValueError(f"A prim already exists at {path}")
    if spec.kind == "distant_light":
        prim = _spawn_light(stage, spec, options)
    else:
        procedural = "usd_path" not in options
        if procedural:
            prim = UsdGeom.Xform.Define(stage, path).GetPrim()
            _set_spawn_pose(prim, spec.translation, spec.orientation)
            directory = prim.GetPath().AppendChild("geometry")
            mesh = UsdGeom.Cube.Define(stage, directory.AppendChild("mesh"))
            dimensions = options.pop("size", (50.0, 50.0, 0.1))
            size = min(dimensions)
            mesh.CreateSizeAttr(size)
            target = mesh.GetPrim()
            _set_spawn_pose(target, (0, 0, 0), (1, 0, 0, 0), tuple(d / size for d in dimensions))
            options.setdefault("collision_props", {})
        else:
            prim = _spawn_reference(stage, spec, options)
            target = prim
            directory = prim.GetPath()

        for key, schema, physx_schema, anchor, mobility in (
            ("collision_props", UsdPhysics.CollisionAPI, "PhysxCollisionAPI", target, ("dynamic", "static")),
            ("rigid_props", UsdPhysics.RigidBodyAPI, "PhysxRigidBodyAPI", prim, ("dynamic",)),
            ("mass_props", UsdPhysics.MassAPI, None, prim, ("dynamic",)),
        ):
            if spec.mobility in mobility:
                schema.Apply(anchor)
            props = options.pop(key, None)
            if props is None:
                continue
            if procedural:
                _set_physics_properties(anchor, schema, props, physx_schema)
                continue
            children = iter(Usd.PrimRange(anchor))
            for child in children:
                if child.HasAPI(schema):
                    _set_physics_properties(child, schema, props, physx_schema)
                    children.PruneChildren()

        _bind_spawn_materials(target, directory, options)
        if options.pop("activate_contact_sensors", False):
            bodies = [child for child in Usd.PrimRange(prim) if child.HasAPI(UsdPhysics.RigidBodyAPI)]
            if not bodies:
                raise ValueError(f"No rigid bodies for contact reporting at {path}")
            for body in bodies:
                body.AddAppliedSchema("PhysxRigidBodyAPI")
                body.CreateAttribute("physxRigidBody:sleepThreshold", Sdf.ValueTypeNames.Float, False).Set(0)
                body.AddAppliedSchema("PhysxContactReportAPI")
                body.CreateAttribute("physxContactReport:threshold", Sdf.ValueTypeNames.Float, False).Set(0)

        for part, material in options.pop("visual_material_bindings", {}).items():
            part_prim = stage.GetPrimAtPath(prim.GetPath().AppendPath(part))
            material_path = Sdf.Path(material.removeprefix("./")).MakeAbsolutePath(prim.GetPath())
            UsdShade.MaterialBindingAPI.Apply(part_prim).Bind(
                UsdShade.Material.Get(stage, material_path), UsdShade.Tokens.strongerThanDescendants
            )

    imageable = UsdGeom.Imageable(prim)
    if options.pop("visible", True):
        imageable.MakeVisible()
    else:
        imageable.MakeInvisible()
    for kind, value in options.pop("semantic_tags", None) or ():
        from pxr import UsdSemantics

        labels = UsdSemantics.LabelsAPI.Apply(prim, kind.replace(" ", "_")).CreateLabelsAttr()
        existing = list(labels.Get() or [])
        value = value.replace(" ", "_")
        if value not in existing:
            labels.Set(existing + [value])
    # These options only affect cloning across regex paths. Each spec has one concrete path.
    options.pop("copy_from_source", None)
    options.pop("spawn_path", None)
    if options:
        raise ValueError(f"Unsupported spawn overrides for {path}: {', '.join(options)}")


def build_scene(scene, stage, repo_root):
    """Author the scene specs and set up sensors on the given or active stage."""
    if stage is None:
        import omni.usd

        stage = omni.usd.get_context().get_stage()
    if stage is None:
        raise ValueError("build_scene requires a USD stage")

    for spec in to_scene_specs(scene, repo_root):
        _spawn_prim(stage, spec)

    sensor_paths = resolve_sensor_configs(scene, repo_root)
    if sensor_paths:
        from isaac_devkit.sensors import load_config, setup_sensor

        for path in sensor_paths:
            setup_sensor(load_config(path), stage)


def resolve_joint_drive_gains(stiffness, damping):
    """Return a validated pair of gains, or None when both are omitted."""
    if stiffness is None and damping is None:
        return None
    if stiffness is None or damping is None:
        raise ValueError(
            "joint drive needs BOTH stiffness and damping (got "
            f"stiffness={stiffness!r}, damping={damping!r}); supply both for "
            "a position drive or neither for the fixed-joint-safe default"
        )
    stiffness = float(stiffness)
    damping = float(damping)
    if stiffness < 0.0 or damping < 0.0:
        raise ValueError(
            f"joint drive gains must be non-negative (got stiffness="
            f"{stiffness}, damping={damping})"
        )
    return (stiffness, damping)


def apply_joint_drive(prim_path, stiffness, damping, *, drive_type="force", stage=None):
    """Set a joint's drive and verify its authored gains on the resolved stage.

    Revolute gains are supplied per radian and stored per degree. Prismatic
    gains use linear units. Return False for a missing stage or undriveable joint.
    """
    gains = resolve_joint_drive_gains(stiffness, damping)
    if gains is None:
        raise ValueError("apply_joint_drive needs both stiffness and damping")
    stiffness, damping = gains

    if stage is None:
        import omni.usd

        stage = omni.usd.get_context().get_stage()
    if stage is None:
        return False
    from pxr import UsdPhysics

    prim = stage.GetPrimAtPath(prim_path)
    if not prim or prim.IsInstanceProxy() or prim.IsInPrototype():
        return False
    schemas = {name.partition(":")[0] for name in prim.GetAppliedSchemas()}
    if "PhysxTendonAxisAPI" in schemas and "PhysxTendonAxisRootAPI" not in schemas:
        return False
    if prim.IsA(UsdPhysics.RevoluteJoint):
        axis = "angular"
        stiffness, damping = math.radians(stiffness), math.radians(damping)
    elif prim.IsA(UsdPhysics.PrismaticJoint):
        axis = "linear"
    else:
        return False
    drive = UsdPhysics.DriveAPI(prim, axis) or UsdPhysics.DriveAPI.Apply(prim, axis)
    drive.CreateTypeAttr().Set(drive_type)
    drive.CreateStiffnessAttr().Set(stiffness)
    drive.CreateDampingAttr().Set(damping)
    drive = UsdPhysics.DriveAPI(stage.GetPrimAtPath(prim_path), axis)
    return (
        bool(drive)
        and drive.GetTypeAttr().Get() == drive_type
        and math.isclose(drive.GetStiffnessAttr().Get(), stiffness, rel_tol=1e-6)
        and math.isclose(drive.GetDampingAttr().Get(), damping, rel_tol=1e-6)
    )
