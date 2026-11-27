"""Structural summaries and runtime joint drives for USD robot models."""

from typing import NamedTuple

from isaac_devkit.scene import apply_joint_drive as apply_joint_drive
from isaac_devkit.scene import resolve_joint_drive_gains


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
    """Return the gains accepted by the scene's joint drive."""
    return resolve_joint_drive_gains(stiffness, damping)
