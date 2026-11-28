"""Unit tests for isaac_devkit.scene — host-runnable, no Isaac Sim required.

Tests cover: YAML loading, validation, model path resolution,
multi-instance generation, and sensor config reference resolution.
"""

import math
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "framework"))
from isaac_devkit import scene as scene_builder

pytestmark = pytest.mark.core

OPENBASE_MODEL = "usd/robot/guiritter/openbase/openbase.usda"
PREFIXED_OBJECT_MODEL = Path("model") / "usd" / "object/pallet/pallet.usd"


@pytest.fixture
def model_root(tmp_path, monkeypatch):
    """Mount a temporary model repository through MODEL_PATH."""
    root = tmp_path / "sim_asset"
    robot = root / OPENBASE_MODEL
    robot.parent.mkdir(parents=True)
    robot.write_text("#usda 1.0")

    obj_dir = root / "object" / "pallet"
    obj_dir.mkdir(parents=True)
    (obj_dir / "pallet.usd").write_text("#usda 1.0")

    monkeypatch.setenv("MODEL_PATH", str(root))
    return root


@pytest.fixture
def repo_root(tmp_path, model_root):
    """Create the scene repository alongside the mounted models."""
    root = tmp_path / "isaac"
    # Material YAML paths are relative to the scene repository.
    (root / "model" / "usd" / "object" / "pallet").mkdir(parents=True)
    sensor_dir = root / "config" / "camera"
    sensor_dir.mkdir(parents=True)
    sensor_cfg = {
        "mount": {"parent_prim": "/World/Robot/base_link", "pose": {"xyz": [0, 0, 0], "rpy": [0, 0, 0]}},
        "sensor": {"category": "camera", "type": "realsense", "asset_suffix": "x"},
        "ros": {"topic_prefix": "/cam", "frame_id_prefix": "cam"},
        "streams": {"color": True, "depth": True},
    }
    (sensor_dir / "realsense.yaml").write_text(yaml.dump(sensor_cfg))

    imu_dir = root / "config" / "imu"
    imu_dir.mkdir(parents=True)
    imu_cfg = {
        "mount": {"parent_prim": "/World/Robot/base_link", "pose": {"xyz": [0, 0, 0], "rpy": [0, 0, 0]}},
        "sensor": {"category": "imu", "type": "imu"},
        "ros": {"topic_prefix": "/imu", "frame_id_prefix": "imu"},
    }
    (imu_dir / "default.yaml").write_text(yaml.dump(imu_cfg))

    return root


@pytest.fixture
def minimal_scene(repo_root):
    cfg = {
        "robot": {
            "model": OPENBASE_MODEL,
            "pose": {"xyz": [0, 0, 0], "rpy": [0, 0, 0]},
        },
    }
    path = repo_root / "scene" / "minimal.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(cfg))
    return path


@pytest.fixture
def full_scene(repo_root):
    cfg = {
        "robot": {
            "model": OPENBASE_MODEL,
            "pose": {"xyz": [0, 0, 0], "rpy": [0, 0, 0]},
        },
        "objects": [
            {
                "model": "object/pallet/pallet.usd",
                "pose": {"xyz": [3.0, 0.5, 0.8], "rpy": [0, 0, 0]},
                "variant": {"color": "blue"},
            },
            {
                "model": "object/pallet/pallet.usd",
                "pose": {"xyz": [3.0, 1.0, 0.8], "rpy": [0, 0, 0]},
                "count": 3,
                "spacing": [0, 0.2, 0],
            },
        ],
        "sensors": [
            "config/camera/realsense.yaml",
            "config/imu/default.yaml",
        ],
    }
    path = repo_root / "scene" / "full.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(cfg))
    return path


def test_sensor_test_bench_robot_model_is_mount_relative():
    repo_root = Path(__file__).resolve().parents[3]
    scene_path = repo_root / "src/scene/sensor_test_bench.yaml"
    scene = yaml.safe_load(scene_path.read_text(encoding="utf-8"))
    assert scene["robot"]["model"] == "usd/robot/guiritter/openbase/openbase_l2.usda"


class TestLoadScene:
    def test_loads_minimal_scene(self, minimal_scene, repo_root):
        scene = scene_builder.load_scene(minimal_scene, repo_root=repo_root)
        assert "robot" in scene
        assert scene["robot"]["model"] == OPENBASE_MODEL

    def test_loads_full_scene(self, full_scene, repo_root):
        scene = scene_builder.load_scene(full_scene, repo_root=repo_root)
        assert "robot" in scene
        assert len(scene["objects"]) == 2
        assert len(scene["sensors"]) == 2

    def test_rejects_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            scene_builder.load_scene(tmp_path / "nope.yaml", repo_root=tmp_path)

    def test_rejects_missing_robot(self, repo_root):
        cfg = {"objects": []}
        path = repo_root / "scene" / "bad.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump(cfg))
        with pytest.raises(ValueError, match="robot"):
            scene_builder.load_scene(path, repo_root=repo_root)


class TestValidateScene:
    def test_rejects_robot_without_model(self, repo_root):
        cfg = {"robot": {"pose": {"xyz": [0, 0, 0], "rpy": [0, 0, 0]}}}
        path = repo_root / "scene" / "bad.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump(cfg))
        with pytest.raises(ValueError, match="model"):
            scene_builder.load_scene(path, repo_root=repo_root)

    def test_rejects_robot_without_pose(self, repo_root):
        cfg = {"robot": {"model": OPENBASE_MODEL}}
        path = repo_root / "scene" / "bad.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump(cfg))
        with pytest.raises(ValueError, match="pose"):
            scene_builder.load_scene(path, repo_root=repo_root)

    def test_rejects_object_without_model(self, repo_root):
        cfg = {
            "robot": {"model": OPENBASE_MODEL, "pose": {"xyz": [0, 0, 0], "rpy": [0, 0, 0]}},
            "objects": [{"pose": {"xyz": [0, 0, 0], "rpy": [0, 0, 0]}}],
        }
        path = repo_root / "scene" / "bad.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump(cfg))
        with pytest.raises(ValueError, match="model"):
            scene_builder.load_scene(path, repo_root=repo_root)


class TestResolveModelPath:
    def test_resolves_sim_asset(self, repo_root, model_root):
        resolved = scene_builder.resolve_model_path(OPENBASE_MODEL, repo_root)
        assert resolved == model_root / OPENBASE_MODEL

    def test_resolves_object_model(self, repo_root, model_root):
        resolved = scene_builder.resolve_model_path("object/pallet/pallet.usd", repo_root)
        assert resolved == model_root / "object/pallet/pallet.usd"

    def test_missing_prefixed_model_does_not_match_unprefixed_file(self, repo_root):
        # Only object/pallet/pallet.usd exists under the mount.
        with pytest.raises(FileNotFoundError):
            scene_builder.resolve_model_path(PREFIXED_OBJECT_MODEL, repo_root)

    def test_resolves_literal_prefixed_model(self, repo_root, model_root):
        model = model_root / PREFIXED_OBJECT_MODEL
        model.parent.mkdir(parents=True)
        model.write_text("#usda 1.0")
        assert scene_builder.resolve_model_path(PREFIXED_OBJECT_MODEL, repo_root) == model

    def test_rejects_missing_model(self, repo_root):
        with pytest.raises(FileNotFoundError, match="not found"):
            scene_builder.resolve_model_path("robot/nope/nope.usd", repo_root)


class TestModelPathSearch:
    """MODEL_PATH env var: colon-separated search roots for models."""

    def test_model_path_search_order(self, tmp_path, monkeypatch):
        """First matching root in MODEL_PATH wins."""
        root_a = tmp_path / "a"
        root_b = tmp_path / "b"
        (root_a / "bot").mkdir(parents=True)
        (root_a / "bot" / "bot.usd").write_text("#usda 1.0")
        (root_b / "bot").mkdir(parents=True)
        (root_b / "bot" / "bot.usd").write_text("#usda 1.0 (second)")
        monkeypatch.setenv("MODEL_PATH", f"{root_a}:{root_b}")
        resolved = scene_builder.resolve_model_path("bot/bot.usd", tmp_path)
        assert resolved == root_a / "bot" / "bot.usd"

    def test_model_path_second_root_found(self, tmp_path, monkeypatch):
        """Model in the second root is found when not in the first."""
        root_a = tmp_path / "a"
        root_a.mkdir()
        root_b = tmp_path / "b"
        (root_b / "bot").mkdir(parents=True)
        (root_b / "bot" / "bot.usd").write_text("#usda 1.0")
        monkeypatch.setenv("MODEL_PATH", f"{root_a}:{root_b}")
        resolved = scene_builder.resolve_model_path("bot/bot.usd", tmp_path)
        assert resolved == root_b / "bot" / "bot.usd"

    def test_model_path_absolute_bypasses_search(self, tmp_path, monkeypatch):
        """An absolute model path is used as-is, ignoring MODEL_PATH."""
        abs_model = tmp_path / "direct" / "my.usd"
        abs_model.parent.mkdir(parents=True)
        abs_model.write_text("#usda 1.0")
        monkeypatch.setenv("MODEL_PATH", "/nonexistent")
        resolved = scene_builder.resolve_model_path(str(abs_model), tmp_path)
        assert resolved == abs_model

    @pytest.mark.parametrize("model_path", [None, ""], ids=["unset", "empty"])
    def test_relative_model_requires_model_path(self, tmp_path, monkeypatch, model_path):
        legacy_dir = tmp_path / "model" / "usd"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "bot.usd").write_text("#usda 1.0")
        if model_path is None:
            monkeypatch.delenv("MODEL_PATH", raising=False)
        else:
            monkeypatch.setenv("MODEL_PATH", model_path)
        with pytest.raises(ValueError, match="MODEL_PATH"):
            scene_builder.resolve_model_path("bot.usd", tmp_path)

    def test_model_path_error_lists_all_roots(self, tmp_path, monkeypatch):
        """The error for a missing model names every root that was searched."""
        root_a = tmp_path / "a"
        root_b = tmp_path / "b"
        root_a.mkdir()
        root_b.mkdir()
        monkeypatch.setenv("MODEL_PATH", f"{root_a}:{root_b}")
        with pytest.raises(FileNotFoundError, match=str(root_a)) as exc_info:
            scene_builder.resolve_model_path("no/such.usd", tmp_path)
        assert str(root_b) in str(exc_info.value)


class TestPackageUriResolve:
    """package:// URIs resolved by scanning package.xml under MODEL_PATH."""

    @staticmethod
    def _make_pkg(root, pkg_name, model_rel="urdf/robot.usd"):
        """Create a minimal ROS package with a model file under *root*."""
        pkg_dir = root / pkg_name
        model = pkg_dir / model_rel
        model.parent.mkdir(parents=True, exist_ok=True)
        model.write_text("#usda 1.0")
        (pkg_dir / "package.xml").write_text(
            f"<package><name>{pkg_name}</name></package>"
        )
        return pkg_dir

    def test_package_uri_resolved_from_model_path(self, tmp_path, monkeypatch):
        """package://pkg/rel resolves to <root>/pkg/rel."""
        root = tmp_path / "models"
        self._make_pkg(root, "my_robot", "urdf/robot.usd")
        monkeypatch.setenv("MODEL_PATH", str(root))
        resolved = scene_builder.resolve_model_path(
            "package://my_robot/urdf/robot.usd", tmp_path
        )
        assert resolved == root / "my_robot" / "urdf" / "robot.usd"

    def test_package_uri_requires_package_xml(self, tmp_path, monkeypatch):
        """A directory without package.xml is not treated as a package."""
        root = tmp_path / "models"
        pkg_dir = root / "fake_pkg"
        (pkg_dir / "urdf").mkdir(parents=True)
        (pkg_dir / "urdf" / "robot.usd").write_text("#usda 1.0")
        # No package.xml!
        monkeypatch.setenv("MODEL_PATH", str(root))
        with pytest.raises(FileNotFoundError):
            scene_builder.resolve_model_path(
                "package://fake_pkg/urdf/robot.usd", tmp_path
            )

    def test_package_uri_searches_multiple_roots(self, tmp_path, monkeypatch):
        """package:// scans each MODEL_PATH root in order."""
        root_a = tmp_path / "a"
        root_a.mkdir()
        root_b = tmp_path / "b"
        self._make_pkg(root_b, "bot_desc", "meshes/bot.usd")
        monkeypatch.setenv("MODEL_PATH", f"{root_a}:{root_b}")
        resolved = scene_builder.resolve_model_path(
            "package://bot_desc/meshes/bot.usd", tmp_path
        )
        assert resolved == root_b / "bot_desc" / "meshes" / "bot.usd"

    def test_package_uri_error_names_package(self, tmp_path, monkeypatch):
        """The error for an unresolved package:// URI names the package."""
        root = tmp_path / "models"
        root.mkdir()
        monkeypatch.setenv("MODEL_PATH", str(root))
        with pytest.raises(FileNotFoundError, match="no_such_pkg"):
            scene_builder.resolve_model_path(
                "package://no_such_pkg/model.usd", tmp_path
            )


class TestGenerateInstances:
    def test_single_instance(self):
        entry = {
            "model": "object/pallet/pallet.usd",
            "pose": {"xyz": [1.0, 2.0, 3.0], "rpy": [0, 0, 0]},
        }
        instances = scene_builder.generate_instances(entry)
        assert len(instances) == 1
        assert instances[0]["pose"]["xyz"] == [1.0, 2.0, 3.0]

    def test_multi_instance_with_spacing(self):
        entry = {
            "model": "object/pallet/pallet.usd",
            "pose": {"xyz": [1.0, 0.0, 0.0], "rpy": [0, 0, 0]},
            "count": 3,
            "spacing": [0, 0.5, 0],
        }
        instances = scene_builder.generate_instances(entry)
        assert len(instances) == 3
        assert instances[0]["pose"]["xyz"] == [1.0, 0.0, 0.0]
        assert instances[1]["pose"]["xyz"] == pytest.approx([1.0, 0.5, 0.0])
        assert instances[2]["pose"]["xyz"] == pytest.approx([1.0, 1.0, 0.0])

    def test_multi_instance_preserves_variant(self):
        entry = {
            "model": "object/pallet/pallet.usd",
            "pose": {"xyz": [0, 0, 0], "rpy": [0, 0, 0]},
            "variant": {"color": "blue"},
            "count": 2,
            "spacing": [1, 0, 0],
        }
        instances = scene_builder.generate_instances(entry)
        assert all(i.get("variant") == {"color": "blue"} for i in instances)

    def test_count_defaults_to_one(self):
        entry = {
            "model": "x",
            "pose": {"xyz": [0, 0, 0], "rpy": [0, 0, 0]},
        }
        instances = scene_builder.generate_instances(entry)
        assert len(instances) == 1


class TestResolveSensorConfigs:
    def test_resolves_sensor_paths(self, full_scene, repo_root):
        scene = scene_builder.load_scene(full_scene, repo_root=repo_root)
        resolved = scene_builder.resolve_sensor_configs(scene, repo_root)
        assert len(resolved) == 2
        assert all(Path(p).exists() for p in resolved)

    def test_rejects_missing_sensor_config(self, repo_root):
        scene = {"sensors": ["config/lidar/nonexistent.yaml"]}
        with pytest.raises(FileNotFoundError):
            scene_builder.resolve_sensor_configs(scene, repo_root)

    def test_empty_sensors_ok(self, repo_root):
        scene = {}
        resolved = scene_builder.resolve_sensor_configs(scene, repo_root)
        assert resolved == []


class TestRpyToQuat:
    """Pure rpy(deg) -> (w,x,y,z) quaternion, XYZ intrinsic order."""

    def test_identity(self):
        w, x, y, z = scene_builder.rpy_to_quat([0, 0, 0])
        assert (w, x, y, z) == pytest.approx((1.0, 0.0, 0.0, 0.0))

    def test_yaw_90(self):
        # 90 deg about Z -> (cos45, 0, 0, sin45).
        w, x, y, z = scene_builder.rpy_to_quat([0, 0, 90])
        s = math.sqrt(2) / 2
        assert (w, x, y, z) == pytest.approx((s, 0.0, 0.0, s))

    def test_roll_90(self):
        # 90 deg about X -> (cos45, sin45, 0, 0).
        w, x, y, z = scene_builder.rpy_to_quat([90, 0, 0])
        s = math.sqrt(2) / 2
        assert (w, x, y, z) == pytest.approx((s, s, 0.0, 0.0))

    def test_pitch_90(self):
        # 90 deg about Y -> (cos45, 0, sin45, 0).
        w, x, y, z = scene_builder.rpy_to_quat([0, 90, 0])
        s = math.sqrt(2) / 2
        assert (w, x, y, z) == pytest.approx((s, 0.0, s, 0.0))

    def test_unit_norm(self):
        w, x, y, z = scene_builder.rpy_to_quat([30, 45, 60])
        norm = math.sqrt(w * w + x * x + y * y + z * z)
        assert norm == pytest.approx(1.0)


@pytest.mark.parametrize(("rpy", "expected"), [
    ([0, 0, 0], (1, 0, 0, 0)),
    ([90, 0, 0], (math.sqrt(0.5), math.sqrt(0.5), 0, 0)),
    ([0, 0, 90], (math.sqrt(0.5), 0, 0, math.sqrt(0.5))),
    ([90, 90, 0], (0.5, 0.5, 0.5, -0.5)),
])
def test_spawn_spec_orientation_is_scalar_first(repo_root, rpy, expected):
    scene = _scene_dict(robot={"pose": {"xyz": [0, 0, 0], "rpy": rpy}})
    assert scene_builder.to_spawn_specs(scene, repo_root)[-1].orientation == pytest.approx(expected)


def _scene_dict(robot=None, objects=None, environment=None):
    base_robot = {
        "model": OPENBASE_MODEL,
        "pose": {"xyz": [0, 0, 0], "rpy": [0, 0, 0]},
    }
    if robot:
        base_robot.update(robot)
    scene = {"robot": base_robot}
    if objects is not None:
        scene["objects"] = objects
    if environment is not None:
        scene["environment"] = environment
    return scene


class TestToSpawnSpecs:
    """Pure YAML -> SpawnSpec mapping; asserted without a live stage."""

    def test_default_environment_emits_light_only(self, repo_root):
        # No environment block -> no ground, but a default light is emitted.
        specs = scene_builder.to_spawn_specs(_scene_dict(), repo_root)
        kinds = [s.kind for s in specs]
        assert "ground_plane" not in kinds
        assert kinds[0] == "distant_light"

    def test_ground_plane_spec(self, repo_root):
        specs = scene_builder.to_spawn_specs(
            _scene_dict(environment={"ground_plane": True}), repo_root
        )
        ground = next(s for s in specs if s.kind == "ground_plane")
        assert ground.prim_path == "/World/ground"
        assert ground.mobility is None

    def test_default_light_when_absent(self, repo_root):
        specs = scene_builder.to_spawn_specs(
            _scene_dict(environment={"ground_plane": True}), repo_root
        )
        light = next(s for s in specs if s.kind == "distant_light")
        assert light.prim_path == "/World/light"
        assert light.kwargs.get("intensity") == 3000.0

    def test_curated_light_fields(self, repo_root):
        specs = scene_builder.to_spawn_specs(
            _scene_dict(
                environment={
                    "light": {
                        "intensity": 1500.0,
                        "color": [0.5, 0.5, 0.5],
                        "angle": 0.3,
                    }
                }
            ),
            repo_root,
        )
        light = next(s for s in specs if s.kind == "distant_light")
        assert light.kwargs["intensity"] == 1500.0
        assert light.kwargs["color"] == [0.5, 0.5, 0.5]
        assert light.kwargs["angle"] == 0.3

    def test_emits_specs_in_order(self, repo_root):
        specs = scene_builder.to_spawn_specs(
            _scene_dict(
                environment={"ground_plane": True},
                objects=[
                    {
                        "model": "object/pallet/pallet.usd",
                        "pose": {"xyz": [1, 0, 0], "rpy": [0, 0, 0]},
                    }
                ],
            ),
            repo_root,
        )
        kinds = [s.kind for s in specs]
        # ground, light, robot usd, object usd -- in that order.
        assert kinds == ["ground_plane", "distant_light", "usd", "usd"]

    def test_robot_usd_spec(self, repo_root):
        specs = scene_builder.to_spawn_specs(
            _scene_dict(robot={"pose": {"xyz": [1.0, 2.0, 3.0], "rpy": [0, 0, 0]}}),
            repo_root,
        )
        robot = next(s for s in specs if s.prim_path == "/World/Robot")
        assert robot.kind == "usd"
        assert robot.kwargs["usd_path"].endswith(OPENBASE_MODEL)
        assert robot.translation == pytest.approx((1.0, 2.0, 3.0))
        assert robot.orientation == pytest.approx((1.0, 0.0, 0.0, 0.0))
        assert robot.mobility is None

    def test_object_usd_spec_translation_and_path(self, repo_root):
        specs = scene_builder.to_spawn_specs(
            _scene_dict(
                objects=[
                    {
                        "model": "object/pallet/pallet.usd",
                        "pose": {"xyz": [3.0, 0.5, 0.8], "rpy": [0, 0, 0]},
                        "mobility": "dynamic",
                    }
                ]
            ),
            repo_root,
        )
        obj = next(
            s for s in specs if s.prim_path.startswith("/World/Objects/")
        )
        assert obj.prim_path == "/World/Objects/pallet_0_0"
        assert obj.kwargs["usd_path"].endswith("pallet.usd")
        assert obj.translation == pytest.approx((3.0, 0.5, 0.8))
        assert obj.mobility == "dynamic"

    def test_object_static_mobility(self, repo_root):
        specs = scene_builder.to_spawn_specs(
            _scene_dict(
                objects=[
                    {
                        "model": "object/pallet/pallet.usd",
                        "pose": {"xyz": [0, 0, 0], "rpy": [0, 0, 0]},
                        "mobility": "static",
                    }
                ]
            ),
            repo_root,
        )
        obj = next(
            s for s in specs if s.prim_path.startswith("/World/Objects/")
        )
        assert obj.mobility == "static"

    def test_object_rpy_to_orientation(self, repo_root):
        specs = scene_builder.to_spawn_specs(
            _scene_dict(
                objects=[
                    {
                        "model": "object/pallet/pallet.usd",
                        "pose": {"xyz": [0, 0, 0], "rpy": [0, 0, 90]},
                    }
                ]
            ),
            repo_root,
        )
        obj = next(
            s for s in specs if s.prim_path.startswith("/World/Objects/")
        )
        s = math.sqrt(2) / 2
        assert obj.orientation == pytest.approx((s, 0.0, 0.0, s))

    def test_instance_expansion_flows_through(self, repo_root):
        specs = scene_builder.to_spawn_specs(
            _scene_dict(
                objects=[
                    {
                        "model": "object/pallet/pallet.usd",
                        "pose": {"xyz": [3.0, 1.0, 0.8], "rpy": [0, 0, 0]},
                        "count": 3,
                        "spacing": [0, 0.2, 0],
                        "mobility": "dynamic",
                    }
                ]
            ),
            repo_root,
        )
        objs = [
            s for s in specs if s.prim_path.startswith("/World/Objects/")
        ]
        assert len(objs) == 3
        assert objs[0].prim_path == "/World/Objects/pallet_0_0"
        assert objs[2].prim_path == "/World/Objects/pallet_0_2"
        assert objs[1].translation == pytest.approx((3.0, 1.2, 0.8))
        assert objs[2].translation == pytest.approx((3.0, 1.4, 0.8))
        assert all(o.mobility == "dynamic" for o in objs)

    def test_spawn_overrides_spread_onto_kwargs(self, repo_root):
        specs = scene_builder.to_spawn_specs(
            _scene_dict(
                robot={
                    "pose": {"xyz": [0, 0, 0], "rpy": [0, 0, 0]},
                    "spawn_overrides": {"scales": (2.0, 2.0, 2.0)},
                }
            ),
            repo_root,
        )
        robot = next(s for s in specs if s.prim_path == "/World/Robot")
        assert robot.kwargs["scales"] == (2.0, 2.0, 2.0)

    def test_spawn_overrides_reject_unknown_options(self, repo_root):
        scene = _scene_dict(robot={"spawn_overrides": {"usd_path": "/override/path.usd"}})
        with pytest.raises(ValueError, match="Unsupported usd spawn override: usd_path"):
            scene_builder.to_spawn_specs(scene, repo_root)

    def test_variant_carried_as_variants_kwarg(self, repo_root):
        specs = scene_builder.to_spawn_specs(
            _scene_dict(
                objects=[
                    {
                        "model": "object/pallet/pallet.usd",
                        "pose": {"xyz": [0, 0, 0], "rpy": [0, 0, 0]},
                        "variant": {"shape": "tall"},
                    }
                ]
            ),
            repo_root,
        )
        obj = next(
            s for s in specs if s.prim_path.startswith("/World/Objects/")
        )
        assert obj.kwargs["variants"] == {"shape": "tall"}

    def test_specs_are_json_serializable(self, repo_root):
        import json

        specs = scene_builder.to_spawn_specs(
            _scene_dict(environment={"ground_plane": True}), repo_root
        )
        # NamedTuple -> list of fields; every field is plain data.
        json.dumps([list(s) for s in specs])

    def test_material_diffuse_recorded(self, repo_root, tmp_path):
        # A material YAML referenced by an object records a diffuse color
        # under visual_material_diffuse so build_scene can attach it.
        material = {
            "materials": {
                "/Looks/Body": {
                    "shader": "OmniPBR",
                    "diffuse_color": [0.1, 0.2, 0.3],
                }
            }
        }
        mat_path = repo_root / "model" / "usd" / "object" / "pallet" / "mat.yaml"
        mat_path.write_text(yaml.dump(material))
        specs = scene_builder.to_spawn_specs(
            _scene_dict(
                objects=[
                    {
                        "model": "object/pallet/pallet.usd",
                        "pose": {"xyz": [0, 0, 0], "rpy": [0, 0, 0]},
                        "material": "model/usd/object/pallet/mat.yaml",
                    }
                ]
            ),
            repo_root,
        )
        obj = next(
            s for s in specs if s.prim_path.startswith("/World/Objects/")
        )
        assert obj.kwargs["visual_material_diffuse"] == pytest.approx(
            (0.1, 0.2, 0.3)
        )

    def test_no_material_no_diffuse_key(self, repo_root):
        specs = scene_builder.to_spawn_specs(
            _scene_dict(
                objects=[
                    {
                        "model": "object/pallet/pallet.usd",
                        "pose": {"xyz": [0, 0, 0], "rpy": [0, 0, 0]},
                    }
                ]
            ),
            repo_root,
        )
        obj = next(
            s for s in specs if s.prim_path.startswith("/World/Objects/")
        )
        assert "visual_material_diffuse" not in obj.kwargs


@pytest.mark.parametrize("key", [
    "rigid_props", "mass_props", "collision_props", "physics_material",
    "physics_material_path",
])
@pytest.mark.parametrize("entry", ["robot", "object", "light", "ground"])
def test_spawn_overrides_reject_asset_physics(repo_root, key, entry):
    overrides = {key: {}}
    scene = _scene_dict(environment={})
    if entry == "robot":
        scene["robot"]["spawn_overrides"] = overrides
    elif entry == "object":
        scene["objects"] = [{
            "model": "object/pallet/pallet.usd",
            "pose": {"xyz": [0, 0, 0], "rpy": [0, 0, 0]},
            "spawn_overrides": overrides,
        }]
    elif entry == "light":
        scene["environment"]["light"] = {"spawn_overrides": overrides}
    else:
        scene["environment"].update(ground_plane=True, ground_overrides=overrides)

    with pytest.raises(ValueError, match=rf"{key}.*sim_asset.*asset_converter"):
        scene_builder.to_spawn_specs(scene, repo_root)


def test_scene_runtime_uses_experimental_api(repo_root):
    root = Path(scene_builder.__file__).parent
    for filename in ("scene.py", "usd_model.py"):
        assert "isaaclab" not in (root / filename).read_text()
        assert "isaacsim.core.experimental" in (root / filename).read_text()


def test_load_scene_rejects_asset_physics_before_resolving_models(repo_root, tmp_path):
    path = tmp_path / "invalid.yaml"
    scene = _scene_dict(robot={
        "model": "unavailable.usd",
        "spawn_overrides": {"physics_material": None},
    })
    path.write_text(yaml.safe_dump(scene))
    with pytest.raises(ValueError, match="physics_material.*sim_asset.*asset_converter"):
        scene_builder.load_scene(path, repo_root)
