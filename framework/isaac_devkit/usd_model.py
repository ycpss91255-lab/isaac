"""Structural summaries and runtime joint drives for USD robot models."""

import math
from typing import NamedTuple


class PrimSummary(NamedTuple):
    """Counts, link paths, and root prim for a robot in a USD stage."""

    prim_count: int
    joint_count: int
    link_paths: list
    root_prim: str
    usd_path: str


def _summarize_prim_records(prim_records, usd_path):
    """Fold ``(prim_path, type_name)`` records into a ``PrimSummary`` (pure).

    Classification rules:

    * ``root_prim`` = the first record at the minimum path depth;
    * joints = records whose USD type name contains ``"Joint"`` (e.g.
      ``PhysicsRevoluteJoint``);
    * ``link_paths`` = Xform-typed records that are direct children of
      ``root_prim``;
    * ``prim_count`` = total number of records.

    Args:
        prim_records: Iterable of ``(prim_path, type_name)`` pairs, in
            stage traversal order. Each pair describes a USD prim.
        usd_path: Filesystem path recorded in ``PrimSummary.usd_path``.

    Returns:
        The actual ``PrimSummary``.

    Raises:
        ValueError: If ``prim_records`` is empty.
    """
    records = [(str(path), str(type_name)) for path, type_name in prim_records]
    if not records:
        raise ValueError("empty prim record list; stage has no prims")

    min_depth = min(path.count("/") for path, _ in records)
    root_prim = next(
        path for path, _ in records if path.count("/") == min_depth
    )
    child_depth = root_prim.count("/") + 1
    link_paths = [
        path
        for path, type_name in records
        if type_name == "Xform"
        and path.startswith(f"{root_prim}/")
        and path.count("/") == child_depth
    ]
    joint_count = sum(1 for _, type_name in records if "Joint" in type_name)

    return PrimSummary(
        prim_count=len(records),
        joint_count=joint_count,
        link_paths=link_paths,
        root_prim=root_prim,
        usd_path=str(usd_path),
    )


def _resolve_joint_drive_gains(stiffness, damping):
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


def apply_joint_drive(
    prim_path, stiffness, damping, *, drive_type="force", stage=None
):
    """Author default gains and drive mode on a revolute or prismatic joint."""
    gains = _resolve_joint_drive_gains(stiffness, damping)
    if gains is None:
        raise ValueError("apply_joint_drive needs both stiffness and damping")

    from isaacsim.core.experimental.prims import Articulation
    from isaacsim.core.experimental.utils import backend, stage as stage_utils
    from pxr import UsdPhysics

    if stage is None:
        try:
            stage = stage_utils.get_current_stage(backend="usd")
        except ValueError:
            return False
    joint = stage.GetPrimAtPath(prim_path)
    if not joint or joint.IsInstanceProxy() or joint.IsInPrototype():
        return False
    if joint.IsA(UsdPhysics.RevoluteJoint):
        axis = "angular"
    elif joint.IsA(UsdPhysics.PrismaticJoint):
        axis = "linear"
    else:
        return False

    schemas = joint.GetAppliedSchemas()
    if any(schema.startswith("PhysxTendonAxisAPI:") for schema in schemas) and not any(
        schema.startswith("PhysxTendonAxisRootAPI:") for schema in schemas
    ):
        return joint.HasAPI(UsdPhysics.DriveAPI, axis)

    if joint.HasAPI(UsdPhysics.DriveAPI, axis):
        with stage_utils.use_stage(stage), backend.use_backend("usd"):
            ancestor = joint.GetParent()
            while ancestor and not ancestor.IsPseudoRoot():
                root, = Articulation.fetch_articulation_root_api_prim_paths(
                    [str(ancestor.GetPath())]
                )
                if root is not None:
                    articulation = Articulation(root)
                    paths = articulation.dof_paths
                    if paths and prim_path in paths[0]:
                        index = paths[0].index(prim_path)
                        articulation.set_dof_drive_types(drive_type, dof_indices=index)
                        articulation.set_dof_gains(*gains, dof_indices=index, update_default_gains=False)
                        return True
                    break
                ancestor = ancestor.GetParent()

    # Articulation has no joint-path authoring API for standalone joints or
    # DOFs without a drive (the metadata query infers the axis from DriveAPI).
    drive = UsdPhysics.DriveAPI.Apply(joint, axis)
    if not drive:
        return False
    factor = math.pi / 180 if axis == "angular" else 1.0
    return all((
        drive.CreateTypeAttr().Set(drive_type),
        drive.CreateStiffnessAttr().Set(gains[0] * factor),
        drive.CreateDampingAttr().Set(gains[1] * factor),
    ))
