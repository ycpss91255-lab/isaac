"""Declarative scene composition from YAML config.

Reads a Scene YAML that lists robot + objects + sensors, resolves model
paths relative to repo root, and assembles the scene via Isaac Sim Core
Experimental. The pure ``to_spawn_specs`` adapter returns JSON-serializable
records. Runtime imports stay inside the stage authoring functions.

Usage from an IsaacDriver subclass:

    from isaac_devkit.scene import load_scene, build_scene
    scene = load_scene("scene/sensor_test_bench.yaml", repo_root)
    build_scene(scene, stage, repo_root)
"""

import logging
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
        kwargs: Spawn options (incl. any
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

    _spawn_options(robot.get("spawn_overrides", {}), "usd")
    environment = scene.get("environment") or {}
    _spawn_options(environment.get("ground_overrides", {}), "ground")
    light = environment.get("light")
    if isinstance(light, dict):
        _spawn_options(light.get("spawn_overrides", {}), "light")

    for i, obj in enumerate(scene.get("objects", [])):
        if "model" not in obj:
            raise ValueError(f"{source}: objects[{i}] needs 'model'")
        if "pose" not in obj:
            raise ValueError(f"{source}: objects[{i}] needs 'pose'")
        for key in obj:
            _reject_material_key(key)
        _spawn_options(obj.get("spawn_overrides", {}), "usd")


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
    'variant', 'mobility', and 'spawn_overrides' from the original entry.
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
        for key in ("mobility", "spawn_overrides"):
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


def _usd_spec(prim_path, entry, usd_abs, mobility=None):
    """Build a "usd" SpawnSpec from a curated entry + resolved USD path.

    Curated -> kwargs: ``model`` -> ``usd_path`` (the absolute path str),
    ``pose.xyz`` -> ``translation``, ``pose.rpy`` (deg) -> ``orientation``
    quaternion, ``variant`` -> ``variants`` kwarg (structurally-distinct
    variant selection, ADR-0018 decision 7).
    """
    pose = entry["pose"]
    kwargs = {"usd_path": str(usd_abs)}

    variant = entry.get("variant")
    if variant is not None:
        kwargs["variants"] = variant

    kwargs.update(_spawn_options(entry.get("spawn_overrides", {}), "usd"))

    return SpawnSpec(
        prim_path=prim_path,
        kind="usd",
        kwargs=kwargs,
        translation=tuple(float(c) for c in pose["xyz"]),
        orientation=rpy_to_quat(pose["rpy"]),
        mobility=mobility,
    )


def to_spawn_specs(scene, repo_root):
    """Map a validated scene dict to a neutral list of ``SpawnSpec``.

    PURE: imports no Isaac module. Emits, in order:

    1. environment ground plane (if ``environment.ground_plane`` truthy)
       at ``/World/ground``;
    2. a distant light at ``/World/light`` from ``environment.light``
       (curated optional ``intensity`` / ``color`` / ``angle``); if
       ``environment.light`` is absent a sensible default SunLight is
       still emitted so "ground + light spawn via the adapter" holds
       (DoD) -- the driver's ``_ensure_scene_defaults`` defers to this;
    3. the robot USD at ``/World/Robot``;
    4. one USD spec per object instance at
       ``/World/Objects/<modelstem>_<idx>_<instidx>``, carrying mobility.

    """
    specs = []

    environment = scene.get("environment", {}) or {}
    ground_kwargs = _spawn_options(environment.get("ground_overrides", {}), "ground")
    if environment.get("ground_plane"):
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
        light_kwargs.update(_spawn_options(light.get("spawn_overrides", {}), "light"))
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
    specs.append(_usd_spec("/World/Robot", robot, robot_usd))

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
                    mobility=inst.get("mobility"),
                )
            )

    return specs


_SHARED_SPAWN_OPTIONS = {"visible", "labels", "taxonomy"}
_SPAWN_OPTIONS = {
    "usd": {"scales"},
    "light": {"angles", "colors", "intensities"},
    "ground": {"size", "usd_path"},
}


def _reject_material_key(key):
    if isinstance(key, str) and key.startswith(("material", "visual_material")):
        raise ValueError(
            f"{key}: configure materials in URDF/sim_asset so asset_converter writes them into USD"
        )


def _spawn_options(options, kind):
    """Validate the small scene-specific set of spawn options."""
    if not isinstance(options, dict):
        raise ValueError(f"{kind} spawn overrides must be a mapping")
    for key in options:
        if key in {"rigid_props", "mass_props", "collision_props"} or (
            isinstance(key, str) and key.startswith("physics_material")
        ):
            raise ValueError(
                f"{key}: configure physics in sim_asset so asset_converter writes it into USD"
            )
        _reject_material_key(key)
        if key not in _SHARED_SPAWN_OPTIONS and key not in _SPAWN_OPTIONS[kind]:
            raise ValueError(f"Unsupported {kind} spawn override: {key}")
    return dict(options)


def build_scene(scene, stage, repo_root):
    """Assemble a scene and its sensors on the supplied or current USD stage."""
    specs = to_spawn_specs(scene, repo_root)

    from isaacsim.core.experimental.utils import backend, stage as stage_utils

    if stage is None:
        stage = stage_utils.get_current_stage(backend="usd")
    with stage_utils.use_stage(stage), backend.use_backend("usd"):
        for spec in specs:
            _spawn(spec)

    sensor_paths = resolve_sensor_configs(scene, repo_root)
    if sensor_paths:
        from isaac_devkit.sensors import load_config, setup_sensor

        for path in sensor_paths:
            setup_sensor(load_config(path), stage)


def _spawn(spec):
    """Author one spawn spec on the current USD stage."""
    from isaacsim.core.experimental.objects import Cube, DistantLight
    from isaacsim.core.experimental.prims import XformPrim
    from isaacsim.core.experimental.utils import prim as prim_utils, semantics, stage

    path = spec.prim_path
    options = dict(spec.kwargs)
    visible = options.pop("visible", None)
    labels = options.pop("labels", None)
    taxonomy = options.pop("taxonomy", "class")
    pose = {"translations": spec.translation, "orientations": spec.orientation}
    if spec.kind == "distant_light":
        prim = DistantLight(path, angles=options.get("angles", options.get("angle", 0.53)), **pose)
        prim.set_intensities(options.get("intensities", options.get("intensity", 1.0)))
        prim.set_colors(options.get("colors", options.get("color", (1.0, 1.0, 1.0))))
    elif spec.kind == "ground_plane" and "usd_path" not in options:
        stage.define_prim(path)
        prim = XformPrim(path, reset_xform_op_properties=True, **pose)
        dims = options.get("size", (50.0, 50.0, 0.1))
        size = min(dims)
        mesh_path = f"{path}/geometry/mesh"
        Cube(mesh_path, sizes=size, scales=[dim / size for dim in dims])
        _apply_mobility(mesh_path, dynamic=False)
    else:
        reference = stage.add_reference_to_stage(options["usd_path"], path)
        variants = options.get("variants")
        if isinstance(variants, dict):
            for name, selection in variants.items():
                if name in prim_utils.get_prim_variant_collection(reference):
                    prim_utils.set_prim_variants(reference, variants=[(name, selection)])
                else:
                    logging.getLogger(__name__).warning(
                        "Variant set %r does not exist on %s", name, path
                    )
        prim = XformPrim(
            path, reset_xform_op_properties=True, scales=options.get("scales"), **pose
        )
        if spec.mobility in {"dynamic", "static"}:
            _apply_mobility(path, dynamic=spec.mobility == "dynamic")
    if visible is not None:
        prim.set_visibilities(visible)
    if labels is not None:
        semantics.add_labels(prim.prims[0], labels=labels, taxonomy=taxonomy)


def _apply_mobility(path, *, dynamic):
    from isaacsim.core.experimental.prims import GeomPrim, RigidPrim

    geom = GeomPrim(path)
    prim = geom.prims[0]
    existing = set(prim.GetAppliedSchemas())
    if dynamic:
        RigidPrim(path)
    geom.apply_collision_apis()

    # The wrappers apply bundles and offer no selective removal API.
    # Keep the asset's own schemas and the existing scene schema contract.
    for schema in ("PhysxRigidBodyAPI", "PhysicsMeshCollisionAPI", "PhysxCollisionAPI"):
        if schema not in existing and schema in prim.GetAppliedSchemas():
            prim.RemoveAppliedSchema(schema)
