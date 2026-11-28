"""Isaac-side readers for python output mode (isaac#365).

Every Isaac import is function-local (ADR-0017 section 8 / ADR-0023); the
readers only run against a live stage and are covered by the GPU suite.
Each reader returns the raw reading, or ``None`` while no valid data
exists; :class:`~isaac_devkit.output_hub.OutputHub` normalises it.
"""


def make_sources(cameras, joint, imu, lidars_3d=(), lidars_2d=()):
    """Create annotators / sensors; return ``[(name, kind, reader)]``."""
    sources = []
    if cameras:
        import omni.replicator.core as rep

        for cam in cameras:
            product = rep.create.render_product(
                cam.prim, (cam.width, cam.height)
            )
            kind = "depth" if cam.depth else "rgb"
            annotator = rep.AnnotatorRegistry.get_annotator(
                "distance_to_image_plane" if cam.depth else "rgb"
            )
            annotator.attach([product])
            sources.append((cam.name, kind, _annotator_reader(annotator)))
    if joint is not None:
        from isaacsim.sensors.experimental.physics import JointStateSensor

        sensor = JointStateSensor(joint.prim)
        sources.append(("joint_state", "joint_state", _joint_reader(sensor)))
    if imu is not None:
        from isaacsim.sensors.experimental.physics import IMUSensor

        sensor = IMUSensor(imu.prim)
        sources.append((imu.name, "imu", _imu_reader(sensor)))
    if lidars_3d or lidars_2d:
        from isaac_devkit.sensors import _enable_extensions

        _enable_extensions("isaacsim.sensors.experimental.rtx")
        from isaacsim.core.experimental.utils import stage as stage_utils
        from isaacsim.sensors.experimental.rtx import LidarSensor

        stage = stage_utils.get_current_stage(backend="usd")
        for kind, lidars in (("lidar_3d", lidars_3d), ("lidar_2d", lidars_2d)):
            for lidar in lidars:
                path = _resolve_lidar_path(stage, lidar.prim)
                sensor = LidarSensor(path, annotators=["generic-model-output"])
                sources.append((lidar.name, kind, _lidar_reader(sensor, kind)))
    return sources


def _annotator_reader(annotator):
    def read():
        data = annotator.get_data()
        if data is None or getattr(data, "size", 0) == 0:
            return None
        return data

    return read


def _joint_reader(sensor):
    def read():
        reading = sensor.get_sensor_reading()
        if not reading.is_valid:
            return None
        return {
            "names": list(reading.dof_names),
            "positions": list(reading.positions),
            "velocities": list(reading.velocities),
            "efforts": list(reading.efforts),
        }

    return read


def _imu_reader(sensor):
    def read():
        r = sensor.get_sensor_reading()
        if not r.is_valid:
            return None
        return {
            "lin_acc": [r.linear_acceleration_x, r.linear_acceleration_y,
                        r.linear_acceleration_z],
            "ang_vel": [r.angular_velocity_x, r.angular_velocity_y,
                        r.angular_velocity_z],
            "orientation": [r.orientation_w, r.orientation_x,
                            r.orientation_y, r.orientation_z],
        }

    return read


def _resolve_lidar_path(stage, path):
    """Return the path of the first OmniLidar at or below path."""
    from pxr import Usd

    root = stage.GetPrimAtPath(path)
    if root.IsValid():
        for prim in Usd.PrimRange(root):
            if prim.GetTypeName() == "OmniLidar":
                return str(prim.GetPath())
    raise ValueError(f"No OmniLidar prim found at or below {path}")


def _lidar_reader(sensor, kind):
    import numpy as np
    from isaacsim.sensors.experimental.rtx import parse_generic_model_output_data

    def read():
        data, _info = sensor.get_data("generic-model-output")
        if data is None:
            return None
        gmo = parse_generic_model_output_data(data)
        azimuth = np.deg2rad(gmo.x, dtype=np.float32)
        if kind == "lidar_2d":
            return {"ranges": np.array(gmo.z, dtype=np.float32), "angles": azimuth}

        elevation = np.deg2rad(gmo.y, dtype=np.float32)
        ranges = np.asarray(gmo.z, dtype=np.float32)
        horizontal = ranges * np.cos(elevation)
        return np.column_stack((
            horizontal * np.cos(azimuth),
            horizontal * np.sin(azimuth),
            ranges * np.sin(elevation),
        ))

    return read
