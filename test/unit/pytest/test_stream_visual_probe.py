"""Browser-side collection and evidence expected alongside the Python verdict."""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.stream

_PROBE = Path(__file__).resolve().parents[3] / "script/ci/visual_e2e/probe.mjs"


def _probe():
    assert _PROBE.is_file(), "missing the real viewer's Playwright probe"
    return _PROBE.read_text()


def test_probe_samples_the_remote_video_and_delegates_the_verdict():
    probe = _probe()
    for api in ("chromium.launch(", "RTCPeerConnection", "connectionstatechange",
                "getVideoPlaybackQuality(", "remote-video", "videoWidth", "drawImage(",
                "getImageData(", "verdict.py"):
        assert api in probe, api
    assert re.search(r"""addEventListener\(\s*['"]track['"]""", probe)


def test_probe_retries_with_fresh_navigation_and_writes_failure_evidence():
    probe = _probe()
    assert re.search(r"(?:MAX_ATTEMPTS|MAXA|maxAttempts)[^\n;]*\b4\b", probe)
    assert re.search(r"\b(?:for|while)\s*\([^{}]*\)\s*\{[^}]*?page\.(?:goto|reload)\(",
                     probe, re.DOTALL), "retry with a fresh viewer session"
    for evidence in ("result.json", ".png", "screenshot(", "tracing.start(", "tracing.stop(", ".zip"):
        assert evidence in probe, evidence
