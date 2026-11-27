"""Structural summaries and runtime joint drives for USD robot models."""

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
    """Apply a per-joint drive to a USD joint prim (runtime).

    The "set Kp/Kd on an existing joint" path the driver / scene adapter
    can call on a USD stage. Delegates to Isaac Lab's
    ``isaaclab.sim.schemas.modify_joint_drive_properties`` -- its typed
    wrapper over ``UsdPhysics.DriveAPI`` (ADR-0020 decision 3 / #168 survey).
    That function operates **stage-only**: it applies the ``DriveAPI`` to the
    joint prim (auto-detecting the ``"angular"`` axis for a revolute joint /
    ``"linear"`` for a prismatic one from the prim's USD type) and writes the
    gains -- no ``Articulation``, no PhysX view, no ``SimulationContext``, so
    it does NOT touch the #151 shutdown-hang surface. (Do NOT reach for
    ``ImplicitActuatorCfg`` here: its gains only reach sim through
    ``Articulation.write_joint_*_to_sim``, which needs a playing
    ``SimulationContext``.)

    The ``isaaclab`` import is function-local (ADR-0017 section 8): this
    module still imports cleanly on a host without Isaac Sim.

    NOTE: this CONFIGURES the drive (applies the DriveAPI + sets gains). A
    joint physically reaching / holding a commanded target needs stepped
    physics (a ``SimulationContext``, deferred #151) and is out of scope
    here -- the structural "DriveAPI present with the right gains" check is
    what is verified.

    Return contract (why we re-read the prim instead of trusting the
    delegate's return): ``modify_joint_drive_properties`` is wrapped by
    Isaac Lab's ``@apply_nested`` decorator, whose wrapper returns ``None``
    unconditionally -- it never propagates the inner function's success
    bool (Isaac Lab ``sim/utils/prims.py``). Trusting that return therefore
    always reads as falsy even on success. Instead we apply the drive and
    then VERIFY by reading the joint prim's ``DriveAPI`` back from the stage,
    returning that verified boolean. (``apply_nested`` also silently skips
    prims inside an instanced/prototype subtree -- the joint prim must be a
    defining prim, not an instance proxy, for the DriveAPI to land; the
    read-back surfaces that case as ``False`` too.)

    Stage binding (A4, Isaac Lab 3.0 API change): 3.0's ``get_current_stage``
    reads a thread-local stage populated ONLY by ``sim_utils.use_stage(...)``
    (``sim/utils/stage.py:496-524``); opening a stage on the ``omni.usd``
    context (the driver / runner path) no longer populates it, so it returns
    ``None`` and ``modify_joint_drive_properties`` crashes at
    ``GetPrimAtPath`` on ``None`` (2.3 resolved the stage internally). We
    resolve the stage explicitly -- caller-supplied, else ``get_current_stage``,
    else the ``omni.usd`` context stage -- and pass it through both the modify
    call and the read-back (mirroring the scene adapter's use_stage fix).

    Args:
        prim_path: USD prim path of the joint to drive. The angular /
            linear DriveAPI axis is auto-detected from the prim's joint
            type by Isaac Lab.
        stiffness: Position-control Kp.
        damping: Velocity Kd.
        drive_type: ``UsdPhysics`` drive mode, ``"force"`` (default) or
            ``"acceleration"`` -- how the joint effort is applied (NOT the
            angular/linear axis, which is auto-detected).
        stage: The ``Usd.Stage`` holding the joint prim. Defaults to
            ``None``, in which case it is resolved from Isaac Lab's current
            stage, then the ``omni.usd`` context stage.

    Returns:
        ``True`` when the ``DriveAPI`` is present on the joint prim after
        the apply (verified by re-reading the prim from the resolved stage),
        ``False`` otherwise (no stage, prim invalid, not a
        revolute/prismatic joint, or skipped as an instance proxy).

    Raises:
        ValueError: If a gain is missing/negative (validated host-side
            first).
    """
    gains = _resolve_joint_drive_gains(stiffness, damping)
    if gains is None:
        raise ValueError(
            "apply_joint_drive needs both stiffness and damping"
        )
    from isaaclab.sim.schemas import (
        JointDrivePropertiesCfg,
        modify_joint_drive_properties,
    )
    from isaaclab.sim.utils import get_current_stage
    from pxr import UsdPhysics

    # Resolve the stage the 3.0 way (see docstring): caller arg, then Isaac
    # Lab's thread-local current stage, then the omni.usd context stage.
    if stage is None:
        stage = get_current_stage()
    if stage is None:
        import omni.usd

        stage = omni.usd.get_context().get_stage()
    if stage is None:
        return False

    cfg = JointDrivePropertiesCfg(
        drive_type=drive_type,
        stiffness=gains[0],
        damping=gains[1],
    )
    # modify_joint_drive_properties is @apply_nested-wrapped and returns
    # None even on success (it does NOT forward the inner bool), so we
    # cannot trust its return. It applies the DriveAPI itself when absent
    # (it is "modify" but does DriveAPI.Apply when none exists), so a
    # joint without a drive is fine. Pass the resolved stage explicitly (3.0's
    # get_current_stage would otherwise be None) and verify by read-back.
    modify_joint_drive_properties(prim_path, cfg, stage=stage)

    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        return False
    # The axis is angular for a revolute joint, linear for a prismatic one;
    # Isaac Lab applies the matching named DriveAPI. Accept either so the
    # helper works for both joint kinds without re-deriving the type.
    for axis in ("angular", "linear"):
        if prim.HasAPI(UsdPhysics.DriveAPI, axis):
            return True
    return False
