"""Python-mode output hub (isaac#365).

The hub fans simulation data out to registered callbacks. Each source is a
``(name, kind, reader)`` tuple; ``reader()`` performs the (GPU to CPU)
copy and is called **only** when at least one registered consumer wants
that ``kind``. The reading is then normalised to the documented payload
shape and delivered as a :class:`Frame`.

Payloads by kind:

* ``rgb``: ``uint8`` ``(H, W, 3)`` C-contiguous, alpha dropped.
* ``depth``: ``float32`` ``(H, W)`` C-contiguous.
* ``joint_state``: ``{"names", "positions", "velocities", "efforts"}``.
* ``imu``: ``{"lin_acc", "ang_vel", "orientation"}``, orientation order
  ``w, x, y, z``.
* ``lidar_3d``: C-contiguous ``float32`` ``(N, 3)`` XYZ points in meters.
* ``lidar_2d``: Paired ``float32`` ``(N,)`` vectors of ``ranges`` in meters
  and ``angles`` in radians.

Pure: no Isaac or ROS import at module top (ADR-0017 section 8 /
ADR-0023); numpy is imported inside the normalisers.
"""

from collections import namedtuple

KINDS = ("rgb", "depth", "joint_state", "imu", "lidar_3d", "lidar_2d")

Frame = namedtuple("Frame", "name kind stamp data")


def _normalize_rgb(data):
    import numpy as np

    arr = np.asarray(data)
    if arr.ndim != 3 or arr.shape[2] not in (3, 4):
        raise ValueError(
            f"rgb reading must be (H, W, 3|4), got shape {arr.shape}"
        )
    return np.ascontiguousarray(arr[:, :, :3], dtype=np.uint8)


def _normalize_depth(data):
    import numpy as np

    arr = np.asarray(data)
    if arr.ndim == 3 and arr.shape[2] == 1:
        arr = arr[:, :, 0]
    if arr.ndim != 2:
        raise ValueError(
            f"depth reading must be (H, W) or (H, W, 1), got {arr.shape}"
        )
    return np.ascontiguousarray(arr, dtype=np.float32)


def _normalize_joint_state(data):
    out = {}
    for key in ("names", "positions", "velocities", "efforts"):
        if key not in data:
            raise ValueError(f"joint_state reading is missing {key!r}")
        out[key] = list(data[key])
    sizes = {len(v) for v in out.values()}
    if len(sizes) != 1:
        raise ValueError(f"joint_state fields differ in length: {sizes}")
    return out


def _normalize_imu(data):
    sizes = {"lin_acc": 3, "ang_vel": 3, "orientation": 4}
    out = {}
    for key, size in sizes.items():
        if key not in data:
            raise ValueError(f"imu reading is missing {key!r}")
        values = [float(v) for v in data[key]]
        if len(values) != size:
            raise ValueError(
                f"imu {key!r} needs {size} values, got {len(values)}"
            )
        out[key] = values
    return out


def _normalize_lidar_3d(data):
    import numpy as np

    points = np.asarray(data, dtype=np.float32)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError(f"lidar_3d points must be (N, 3), got {points.shape}")
    if not np.isfinite(points).all():
        raise ValueError("lidar_3d points must be finite")
    return np.ascontiguousarray(points)


def _normalize_lidar_2d(data):
    import numpy as np

    scan = {}
    for key in ("ranges", "angles"):
        if key not in data:
            raise ValueError(f"lidar_2d reading is missing {key!r}")
        vector = np.asarray(data[key], dtype=np.float32)
        if vector.ndim != 1 or not np.isfinite(vector).all():
            raise ValueError(f"lidar_2d {key} must be a finite (N,) vector")
        scan[key] = vector
    if scan["ranges"].shape != scan["angles"].shape:
        raise ValueError("lidar_2d ranges and angles must have equal lengths")
    return scan


_NORMALIZERS = {
    "rgb": _normalize_rgb,
    "depth": _normalize_depth,
    "joint_state": _normalize_joint_state,
    "imu": _normalize_imu,
    "lidar_3d": _normalize_lidar_3d,
    "lidar_2d": _normalize_lidar_2d,
}


class OutputHub:
    """Register callbacks per kind; emit one tick of sources."""

    def __init__(self):
        self._subs = []  # list of (callback, frozenset(kinds) or None)

    def register(self, callback, kinds=None):
        """Register *callback*; ``kinds=None`` means every kind.

        Raises:
            ValueError: *kinds* contains a name not in :data:`KINDS`.
        """
        if kinds is not None:
            unknown = [k for k in kinds if k not in KINDS]
            if unknown:
                raise ValueError(
                    f"unknown output kind(s) {unknown}; allowed: {list(KINDS)}"
                )
            kinds = frozenset(kinds)
        self._subs.append((callback, kinds))

    def unregister(self, callback):
        """Remove every registration of *callback* (no-op if absent)."""
        self._subs = [(cb, ks) for cb, ks in self._subs if cb != callback]

    def emit(self, stamp, sources):
        """Deliver one tick.

        Args:
            stamp: Time in seconds attached to every frame of this tick.
            sources: Iterable of ``(name, kind, reader)``.

        Raises:
            ValueError: A wanted source has an unknown kind or a
                malformed reading.
        """
        for name, kind, reader in sources:
            callbacks = [
                cb for cb, ks in self._subs if ks is None or kind in ks
            ]
            if not callbacks:
                continue  # no consumer: no GPU to CPU copy
            if kind not in _NORMALIZERS:
                raise ValueError(
                    f"unknown output kind {kind!r}; allowed: {list(KINDS)}"
                )
            raw = reader()
            if raw is None:
                continue
            frame = Frame(name, kind, stamp, _NORMALIZERS[kind](raw))
            for cb in callbacks:
                cb(frame)
