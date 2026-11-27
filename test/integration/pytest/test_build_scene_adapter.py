"""L1 adapter GPU test (#152, ADR-0018 decisions 1 + 3).

The runner calls ``isaac_devkit.scene.build_scene`` and checks the prims
from ``to_scene_specs`` on the live stage. It uses the official NVIDIA
Jetbot (robot) and cube (``mobility: dynamic`` object) USDs fetched
through ``test/test_assets.py`` (#325).

The Kit side runs in ``_build_scene_runner.py`` (one ``SimulationApp`` per
process -- the singleton constraint); this module owns the subprocess
invocation and marker assertions. ``pxr`` is not importable in the bare
pytest process, so the runner emits marker lines parsed here.

Runtime: inside the Isaac Sim / Isaac Lab devel-test container
(``/isaac-sim/python.sh -m pytest``).
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

# ``test/`` hosts the shared asset helper (#341); make it importable.
_TEST_DIR = Path(__file__).resolve().parents[2]
if str(_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_TEST_DIR))

from test_assets import fetch_test_asset  # noqa: E402

pytestmark = pytest.mark.core

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_SCRIPT = Path(__file__).parent / "_build_scene_runner.py"
PYTHON_SH = "/isaac-sim/python.sh"
RUN_TIMEOUT_SEC = 600


@pytest.fixture(scope="module")
def adapter_run():
    """Spawn the Jetbot + cube scene via the framework adapter once."""
    robot_usd = fetch_test_asset("jetbot")
    object_usd = fetch_test_asset("nvidia_cube")
    result = subprocess.run(
        [
            PYTHON_SH,
            str(RUNNER_SCRIPT),
            "--repo-root",
            str(REPO_ROOT),
            "--robot-usd",
            str(robot_usd),
            "--object-usd",
            str(object_usd),
        ],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT_SEC,
    )
    if result.returncode != 0 or "[ADAPTER OK]" not in result.stdout:
        sys.stderr.write(
            f"\n--- build_scene_runner stdout ---\n{result.stdout}"
            f"\n--- stderr ---\n{result.stderr}\n"
        )
    return result


def test_adapter_runner_clean_exit(adapter_run):
    """The adapter spawn path runs end-to-end without raising."""
    assert adapter_run.returncode == 0, "build_scene_runner exited non-zero"
    assert "[EXIT CLEAN]" in adapter_run.stdout
    assert "[RAISED]" not in adapter_run.stdout


def test_adapter_spawns_ground_light_robot(adapter_run):
    """environment ground + light + robot USD spawn via the scene builder.

    Also asserts /World/Robot/chassis RESOLVES through the adapter
    reference: the Jetbot USD carries a defaultPrim (/jetbot), so the
    USD reference pulls in the referenced robot content and its
    articulation body lands at /World/Robot/chassis (the Jetbot has no
    base_link).
    """
    m = re.search(
        r"\[ADAPTER OK\] ground=(\w+) light=(\w+) robot=(\w+) objects=(\d+)",
        adapter_run.stdout,
    )
    assert m, f"no [ADAPTER OK] marker:\n{adapter_run.stdout}"
    assert m.group(1) == "True", "ground plane not spawned at /World/ground"
    assert m.group(2) == "True", "distant light not spawned at /World/light"
    assert m.group(3) == "True", "robot USD not spawned at /World/Robot"
    assert int(m.group(4)) >= 1, "no object instance spawned under /World/Objects"

    chassis = re.search(r"\[ADAPTER CHASSIS\] valid=(\w+)", adapter_run.stdout)
    assert chassis, f"no [ADAPTER CHASSIS] marker:\n{adapter_run.stdout}"
    assert chassis.group(1) == "True", (
        "/World/Robot/chassis did not resolve through the adapter "
        "reference (defaultPrim regression?)"
    )


def test_adapter_spawns_mobility_dynamic_object(adapter_run):
    """A mobility: dynamic object spawns AND carries RigidBodyAPI.

    The scene builder references the NVIDIA cube and applies the
    rigid-body schema to the prim marked ``mobility: dynamic``.
    """
    m = re.search(
        r"\[ADAPTER OBJECT\] path=(\S+) valid=True rigidbody=(\w+)",
        adapter_run.stdout,
    )
    assert m, f"no dynamic object spawned via the adapter:\n{adapter_run.stdout}"
    assert m.group(2) == "True", (
        f"dynamic object {m.group(1)} spawned without RigidBodyAPI; the "
        "defaultPrim reference did not resolve the rigid-body content"
    )


def test_adapter_authors_rest_offset_on_collision_mesh(adapter_run):
    """The NVIDIA cube's collision mesh receives the rest offset override."""
    match = re.search(
        r"\[ADAPTER COLLISION\] root_rest=(\S+) mesh_rest=(\S+)", adapter_run.stdout
    )
    assert match, f"no [ADAPTER COLLISION] marker:\n{adapter_run.stdout}"
    root_rest, mesh_rest = match.groups()
    assert root_rest == "None"
    assert mesh_rest != "None"
    assert float(mesh_rest) == pytest.approx(0.001)


def test_adapter_binds_spawn_override_diffuse_color(adapter_run):
    """The cube's own binding resolves to a surface shader with the override color."""
    m = re.search(
        r"\[ADAPTER MATERIAL\] path=(\S+) bound_on_object=(\w+) diffuse=(.*)",
        adapter_run.stdout,
    )
    assert m, f"no [ADAPTER MATERIAL] marker:\n{adapter_run.stdout}"
    assert m.group(2) == "True", f"no material binding on {m.group(1)}"
    assert m.group(3) != "None", f"bound surface shader has no diffuseColor on {m.group(1)}"
    color = tuple(float(v) for v in m.group(3).strip("()").split(","))
    assert color == pytest.approx((0.2, 0.4, 0.6))


def test_adapter_spawns_with_identity_orientation(adapter_run):
    """rpy [0,0,0] in the scene must reach the stage as an identity orient.

    Regression guard for the quaternion-order bug: ``rpy_to_quat`` returns
    (w,x,y,z) while the ``sim_utils`` spawners document ``orientation`` as
    (x,y,z,w). Passing it through unreordered sends identity as x=1, w=0 --
    a 180-degree rotation about X, so every scene spawns upside-down
    (authored z becomes -z, the robot ends up below the floor).

    The existing adapter tests assert prim STRUCTURE and cannot see this;
    a symmetric cube and a near-symmetric robot look plausible either way.
    """
    import re

    found = re.findall(
        r"\[ADAPTER ORIENT\] path=(\S+) quat=\(([^)]*)\)", adapter_run.stdout
    )
    assert found, f"no [ADAPTER ORIENT] marker:\n{adapter_run.stdout}"

    for path, quat_str in found:
        w, x, y, z = (float(v) for v in quat_str.split(","))
        assert (w, x, y, z) == pytest.approx((1.0, 0.0, 0.0, 0.0), abs=1e-6), (
            f"{path} spawned rotated: orient=({w}, {x}, {y}, {z}); the scene "
            "scene says rpy [0,0,0] so this must be identity. (0,1,0,0) means "
            "the (w,x,y,z) quaternion reached the spawner as (x,y,z,w)."
        )
