"""Hosted checks for sensor config compatibility and USD prim creation."""

import sys
from pathlib import Path
from unittest.mock import Mock, call

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "framework"))
from isaac_devkit import sensor_prim, sensors as sensor_setup

pytestmark = pytest.mark.core


class TestBackwardCompatReexports:
    """The sensors module must still expose load_config, get_category,
    validate_camera for backward compatibility with scene.py and
    external callers."""

    def test_has_load_config(self):
        assert callable(sensor_setup.load_config)

    def test_has_get_category(self):
        assert callable(sensor_setup.get_category)

    def test_has_validate_camera(self):
        assert callable(sensor_setup.validate_camera)

    def test_has_setup_sensor(self):
        assert callable(sensor_setup.setup_sensor)

    def test_has_setup_sensors(self):
        assert callable(sensor_setup.setup_sensors)


class TestSetupSensorsStillRaises:
    """setup_sensors is a stub until #131."""

    def test_raises_not_implemented(self):
        with pytest.raises(NotImplementedError):
            sensor_setup.setup_sensors(None, None)


class TestLoadConfigRosOptionalViaBackcompat:
    """load_config accessed through the sensors module also accepts
    missing ros: section (the new optional behavior)."""

    def test_no_ros_section(self, tmp_path):
        cfg = {
            "mount": {
                "parent_prim": "/World/Robot/base_link",
                "pose": {"xyz": [0, 0, 0.1], "rpy": [0, 0, 0]},
            },
            "sensor": {"category": "imu", "type": "imu"},
        }
        path = tmp_path / "imu_no_ros.yaml"
        path.write_text(yaml.dump(cfg))
        loaded = sensor_setup.load_config(path)
        assert loaded["ros"] is None

    def test_with_ros_section(self, tmp_path):
        cfg = {
            "mount": {
                "parent_prim": "/World/Robot/base_link",
                "pose": {"xyz": [0, 0, 0.1], "rpy": [0, 0, 0]},
            },
            "sensor": {"category": "imu", "type": "imu"},
            "ros": {"topic_prefix": "/imu", "frame_id_prefix": "imu"},
        }
        path = tmp_path / "imu.yaml"
        path.write_text(yaml.dump(cfg))
        loaded = sensor_setup.load_config(path)
        assert loaded["ros"] is not None


@pytest.mark.parametrize("with_ros", [False, True])
def test_custom_camera_dispatch_returns_mount_and_creates_camera_prims(monkeypatch, with_ros):
    config = Path(__file__).resolve().parents[3] / "src/config/camera/custom.yaml"
    cfg = sensor_setup.load_config(config)
    if not with_ros:
        cfg["ros"] = None

    stage = Mock()
    stage.GetPrimAtPath.return_value.IsValid.return_value = True
    enabled = []
    monkeypatch.setattr(sensor_setup, "_enable_extensions", lambda *names: enabled.extend(names))
    monkeypatch.setattr(sensor_prim, "set_xform_pose", Mock())
    monkeypatch.setattr(sensor_prim, "set_camera_intrinsics", Mock())
    monkeypatch.setitem(sys.modules, "omni.graph.core", None)
    monkeypatch.setitem(sys.modules, "isaac_devkit.sensor_ros", None)

    mount = sensor_setup.setup_sensor(cfg, stage)
    assert mount.startswith(cfg["mount"]["parent_prim"] + "/")
    assert stage.DefinePrim.call_args_list == [
        call(mount, "Xform"),
        call(f"{mount}/color", "Camera"),
        call(f"{mount}/depth", "Camera"),
    ]
    assert "isaacsim.ros2.bridge" not in enabled
