"""OutputHub: per-kind callbacks, copy only when wanted (isaac#365)."""

import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

_FRAMEWORK_DIR = Path(__file__).resolve().parents[3] / "framework"
sys.path.insert(0, str(_FRAMEWORK_DIR))

from isaac_devkit.output_hub import KINDS, Frame, OutputHub  # noqa: E402

pytestmark = pytest.mark.core

_H, _W = 4, 6


class _Source:
    """Fake source: counts reader() calls, returns a canned reading."""

    def __init__(self, name, kind, value):
        self.name = name
        self.kind = kind
        self._value = value
        self.calls = 0

    def reader(self):
        self.calls += 1
        return self._value

    def as_tuple(self):
        return (self.name, self.kind, self.reader)


def _rgba():
    return np.arange(_H * _W * 4, dtype=np.uint8).reshape(_H, _W, 4)


def _joint():
    return {
        "names": ["left", "right"],
        "positions": [0.1, 0.2],
        "velocities": [1.0, 2.0],
        "efforts": [0.0, 0.5],
    }


def _imu():
    return {
        "lin_acc": [0.0, 0.0, 9.81],
        "ang_vel": [0.1, 0.2, 0.3],
        "orientation": [1.0, 0.0, 0.0, 0.0],
    }


def _all_sources():
    points = np.arange(15, dtype=np.float64).reshape(3, 5).T
    scan = {"ranges": [2.5, 4.0], "angles": [-0.5, 0.5]}
    return [
        _Source("cam", "rgb", _rgba()),
        _Source("depth", "depth", np.ones((_H, _W), np.float64)),
        _Source("js", "joint_state", _joint()),
        _Source("imu", "imu", _imu()),
        _Source("cloud", "lidar_3d", points),
        _Source("scan", "lidar_2d", scan),
    ]


def test_kinds_are_the_documented_ones():
    assert set(KINDS) == {
        "rgb", "depth", "joint_state", "imu", "lidar_3d", "lidar_2d",
    }


def test_delivery_of_all_kinds():
    hub = OutputHub()
    got = {}
    hub.register(lambda f: got.setdefault(f.kind, f))
    sources = _all_sources()
    hub.emit(1.5, [s.as_tuple() for s in sources])

    assert set(got) == set(KINDS)
    rgb = got["rgb"].data
    assert rgb.dtype == np.uint8 and rgb.shape == (_H, _W, 3)
    assert np.array_equal(rgb, _rgba()[:, :, :3])  # alpha dropped
    assert rgb.flags["C_CONTIGUOUS"]
    depth = got["depth"].data
    assert depth.dtype == np.float32 and depth.shape == (_H, _W)
    assert depth.flags["C_CONTIGUOUS"]
    joint = got["joint_state"].data
    assert set(joint) == {"names", "positions", "velocities", "efforts"}
    assert joint["names"] == ["left", "right"]
    imu = got["imu"].data
    assert set(imu) == {"lin_acc", "ang_vel", "orientation"}
    assert list(imu["orientation"]) == [1.0, 0.0, 0.0, 0.0]  # w, x, y, z
    assert got["rgb"].stamp == 1.5 and got["rgb"].name == "cam"


def _receive_one_kind(kind):
    hub = OutputHub()
    sources = _all_sources()
    got = []
    hub.register(got.append, kinds=[kind])
    hub.emit(1.5, [s.as_tuple() for s in sources])

    assert [s.kind for s in sources if s.calls] == [kind]
    (frame,) = got
    assert isinstance(frame, Frame)
    assert (frame.kind, frame.stamp) == (kind, 1.5)
    return frame


def test_lidar_3d_subscription_delivers_contiguous_float32_points():
    frame = _receive_one_kind("lidar_3d")
    assert frame.name == "cloud"
    points = frame.data
    assert points.dtype == np.float32 and points.shape == (5, 3)
    assert points.flags.c_contiguous
    np.testing.assert_array_equal(points, np.arange(15).reshape(3, 5).T)


def test_lidar_2d_subscription_delivers_paired_float32_vectors():
    frame = _receive_one_kind("lidar_2d")
    assert frame.name == "scan"
    assert isinstance(frame.data, dict)
    assert set(frame.data) == {"ranges", "angles"}
    for key, values in (("ranges", [2.5, 4.0]), ("angles", [-0.5, 0.5])):
        vector = frame.data[key]
        assert vector.dtype == np.float32 and vector.shape == (2,)
        np.testing.assert_array_equal(vector, values)


def test_depth_with_trailing_unit_axis_is_squeezed():
    hub = OutputHub()
    got = []
    hub.register(got.append, kinds=["depth"])
    hub.emit(0.0, [("d", "depth", lambda: np.ones((_H, _W, 1), np.float32))])
    assert got[0].data.shape == (_H, _W)


def test_reader_not_called_without_consumer():
    hub = OutputHub()
    sources = _all_sources()
    hub.emit(0.0, [s.as_tuple() for s in sources])
    assert all(s.calls == 0 for s in sources)


def test_reader_called_once_per_emit_with_consumer():
    hub = OutputHub()
    sources = _all_sources()
    cb = lambda frame: None  # noqa: E731
    hub.register(cb, ["depth"])
    hub.emit(0.0, [s.as_tuple() for s in sources])
    assert {s.kind: s.calls for s in sources} == {
        "rgb": 0, "depth": 1, "joint_state": 0, "imu": 0,
        "lidar_3d": 0, "lidar_2d": 0,
    }
    hub.emit(1.0, [s.as_tuple() for s in sources])
    assert {s.kind: s.calls for s in sources}["depth"] == 2

    hub.unregister(cb)
    hub.emit(2.0, [s.as_tuple() for s in sources])
    assert {s.kind: s.calls for s in sources}["depth"] == 2  # flat again


def test_two_consumers_share_one_copy():
    hub = OutputHub()
    src = _Source("cam", "rgb", _rgba())
    a, b = [], []
    hub.register(a.append, ["rgb"])
    hub.register(b.append)  # all kinds
    hub.emit(0.0, [src.as_tuple()])
    assert src.calls == 1
    assert len(a) == len(b) == 1


def test_none_reading_is_not_delivered():
    hub = OutputHub()
    got = []
    hub.register(got.append)
    hub.emit(0.0, [("js", "joint_state", lambda: None)])
    assert got == []


def test_unregister_unknown_callback_is_a_noop():
    OutputHub().unregister(lambda f: None)


def test_register_rejects_unknown_kind():
    with pytest.raises(ValueError, match="lidar"):
        OutputHub().register(lambda f: None, ["rgb", "lidar"])


def test_emit_rejects_unknown_source_kind_only_when_wanted():
    hub = OutputHub()
    hub.emit(0.0, [("x", "lidar", lambda: 1)])  # no consumer: not read
    hub.register(lambda f: None)
    with pytest.raises(ValueError, match="lidar"):
        hub.emit(0.0, [("x", "lidar", lambda: 1)])


@pytest.mark.parametrize(
    "kind, bad",
    [
        ("rgb", np.zeros((_H, _W), np.uint8)),
        ("depth", np.zeros((_H, _W, 3), np.float32)),
        ("joint_state", {"names": ["a"], "positions": [0.0]}),
        ("joint_state", {"names": ["a", "b"], "positions": [0.0],
                         "velocities": [0.0], "efforts": [0.0]}),
        ("imu", {"lin_acc": [0, 0, 0], "ang_vel": [0, 0, 0]}),
        ("depth", np.zeros((_H,), np.float32)),
        ("imu", {"lin_acc": [0, 0, 0], "ang_vel": [0, 0, 0],
                 "orientation": [1, 0, 0]}),
        pytest.param("lidar_3d", np.zeros(3), id="flat-point"),
        pytest.param("lidar_3d", np.zeros((3, 2)), id="wrong-coordinate-count"),
        pytest.param("lidar_3d", [[0, np.nan, 1]], id="nonfinite-point"),
        pytest.param("lidar_2d", {"ranges": [1]}, id="missing-angles"),
        pytest.param("lidar_2d", {"angles": [0]}, id="missing-ranges"),
        pytest.param("lidar_2d", {"ranges": [1, 2], "angles": [0]},
                     id="unequal-lengths"),
        pytest.param("lidar_2d", {"ranges": [[1]], "angles": [0]},
                     id="ranges-rank"),
        pytest.param("lidar_2d", {"ranges": [1], "angles": [[0]]},
                     id="angles-rank"),
        pytest.param("lidar_2d", {"ranges": [np.inf], "angles": [0]},
                     id="nonfinite-range"),
        pytest.param("lidar_2d", {"ranges": [1], "angles": [np.nan]},
                     id="nonfinite-angle"),
    ],
)
def test_malformed_payload_raises_value_error(kind, bad):
    hub = OutputHub()
    hub.register(lambda f: None, kinds=[kind])
    source = _Source("s", kind, bad)
    with pytest.raises(ValueError):
        hub.emit(0.0, [source.as_tuple()])
    assert source.calls == 1
