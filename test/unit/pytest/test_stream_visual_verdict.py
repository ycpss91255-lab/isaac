"""Exercise the same frame verdict as the Chromium probe, in hosted stream-unit."""

import runpy
from pathlib import Path

import pytest

pytestmark = pytest.mark.stream

_VERDICT = Path(__file__).resolve().parents[3] / "script/ci/visual_e2e/verdict.py"


def _verdict():
    assert _VERDICT.is_file(), "missing shared RGBA statistics and frame verdict"
    return runpy.run_path(str(_VERDICT))


def _passes(module, stats, **rtc):
    return module["frame_passes"](
        stats, **{"connected": True, "tracks": 1, "video_width": 1920, **rtc}
    )


@pytest.mark.parametrize(
    "rgba, mean, peak, bright, red, passed",
    [
        (bytes([0, 0, 0, 255]) * 100, 0, 0, 0, 0, False),
        # The default stage can meet EVERY luma check. Only colour rejects it.
        (bytes([18, 18, 18, 255, 40, 40, 40, 255]) * 350, 29, 40, 1, 0, False),
        ((bytes([240, 0, 0, 255]) * 7 + bytes([40, 40, 40, 255]) * 693),
         (240 * 0.2126 + 99 * 40) / 100, 240 * 0.2126, 1, 0.01, True),
    ],
    ids=["opaque-black", "default-grey-grid", "one-percent-red-cube"],
)
def test_rgba_frame_verdict(rgba, mean, peak, bright, red, passed):
    module = _verdict()
    stats = module["pixel_stats"](rgba)
    for key, expected in (("meanLuma", mean), ("maxLuma", peak),
                          ("brightFraction", bright), ("redFraction", red)):
        assert stats[key] == pytest.approx(expected), key
    assert _passes(module, stats) is passed


def test_pixel_classifiers_use_strict_cutoffs():
    pixels = [
        (120, 0, 0), (121, 55, 0), (121, 0, 55), (121, 54, 54),
        (16, 16, 16), (17, 17, 17), (0, 0, 0),
    ]
    # Seven copies of each colour also exercise the prototype's 1-in-7
    # luminance sampling. Alpha is opaque even in the black pixels.
    rgba = b"".join(bytes((*rgb, 255)) * 7 for rgb in pixels)
    stats = _verdict()["pixel_stats"](rgba)
    assert stats["redFraction"] == pytest.approx(1 / 7)
    assert stats["brightFraction"] == pytest.approx(5 / 7)


@pytest.mark.parametrize(
    "stats_change, rtc_change, passes",
    [
        ({}, {}, True),
        ({}, {"connected": False}, False),
        ({}, {"tracks": 0}, False),
        ({}, {"video_width": 0}, False),
        ({"meanLuma": 7.99}, {}, False),
        ({"maxLuma": 31.99}, {}, False),
        ({"brightFraction": 0.0499}, {}, False),
        ({"redFraction": 0.0099}, {}, False),
    ],
    ids=["at-all-thresholds", "disconnected", "no-track", "no-video",
         "dim-mean", "dim-peak", "too-few-bright", "too-little-red"],
)
def test_each_gate_is_required(stats_change, rtc_change, passes):
    stats = dict(meanLuma=8, maxLuma=32, brightFraction=0.05, redFraction=0.01)
    assert _passes(_verdict(), {**stats, **stats_change}, **rtc_change) is passes
