"""Browser-side collection and evidence expected alongside the Python verdict."""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.stream

_PROBE = Path(__file__).resolve().parents[3] / "script/ci/visual_e2e/probe.mjs"


def _probe():
    assert _PROBE.is_file(), "missing the real viewer's Playwright probe"
    return _PROBE.read_text()


def _navigation_loop(probe):
    loop = re.search(
        r"^(?P<indent>[ \t]*)(?:for|while)\s*\((?P<header>[^{}]*)\)\s*\{"
        r"[^}]*?page\.(?:goto|reload)\(",
        probe, re.MULTILINE,
    )
    assert loop, "retry with a fresh viewer session"
    return loop


def test_probe_samples_the_remote_video_and_delegates_the_verdict():
    probe = _probe()
    for api in ("chromium.launch(", "RTCPeerConnection", "connectionstatechange",
                "getVideoPlaybackQuality(", "remote-video", "videoWidth", "drawImage(",
                "getImageData(", "verdict.py"):
        assert api in probe, api
    assert re.search(r"""addEventListener\(\s*['"]track['"]""", probe)


def test_probe_retries_with_fresh_navigation_and_writes_failure_evidence():
    probe = _probe()
    _navigation_loop(probe)
    for evidence in ("result.json", ".png", "screenshot(", "tracing.start(", "tracing.stop(", ".zip"):
        assert evidence in probe, evidence


def test_total_budget_defaults_to_600_seconds_and_reads_the_environment():
    assert re.search(
        r"""process\.env\.VISUAL_E2E_TOTAL_TIMEOUT_S\s*\)*\s*(?:\?\?|\|\|)\s*(?:600\b(?!\.)|'600'|"600")""",
        _probe(),
    ), "default VISUAL_E2E_TOTAL_TIMEOUT_S to 600 seconds"


def test_probe_container_forwards_the_total_timeout():
    driver = (_PROBE.parents[1] / "stream_visual_e2e.sh").read_text()
    run = re.search(
        r'^docker run (?P<options>[^\n]*?)\s+"?mcr\.microsoft\.com/playwright:',
        driver.replace("\\\n", ""), re.MULTILINE,
    )
    assert run, "locate the Playwright probe container"
    name = "VISUAL_E2E_TOTAL_TIMEOUT_S"
    # Bare -e inherits the host value and leaves the probe's 600 second default in effect when unset.
    assert re.search(
        rf'(?:^|\s)-e\s+(?P<quote>"?){name}(?:=\$\{{{name}:-600\}})?(?P=quote)(?:\s|$)',
        run["options"],
    ), f"forward {name} to the Playwright probe container"


def test_total_deadline_bounds_the_navigation_retry_loop():
    probe = _probe()
    retry = _navigation_loop(probe)
    header = retry["header"]
    clock_check = re.search(r"(?:Date|performance)\.now\(\)\s*<=?\s*(\w+)", header)
    assert clock_check, "check the total deadline before reconnecting"
    setup = probe[:retry.start()]
    budget = re.search(r"\b(\w+)\s*=\s*[^;=]*process\.env\.VISUAL_E2E_TOTAL_TIMEOUT_S\b[^;]*;", setup)
    assert budget, "read the total budget before the first attempt"
    deadline = re.search(rf"\b{clock_check[1]}\s*=\s*([^;]+);", setup)
    assert deadline and "+" in deadline[1], "add the budget to the start time"
    assert re.search(rf"\b{budget[1]}\b", deadline[1]), "derive the deadline from the budget"
    assert re.search(r"(?:\*\s*1_?000\b|\b1_?000\s*\*)", budget[0] + deadline[1]), "convert seconds to ms"
    assert not re.search(r"\b\w+\s*(?:<=?|>=?)\s*\w+", header), "remove the attempt count cap"


def test_each_navigation_keeps_a_30_second_frame_polling_window():
    probe = _probe()
    attempt = probe[_navigation_loop(probe).end():]
    window = re.search(r"\b(\w+)\s*=\s*[^;]*\b30_?000\b[^;]*;", attempt)
    assert window, "keep the 30000 ms window for each fresh viewer session"
    assert re.search(rf"while\s*\([^{{;]*\b{window[1]}\b", attempt[window.end():])


def test_failed_navigation_backs_off_and_caps_recorded_attempts():
    probe = _probe()
    retry = _navigation_loop(probe)
    body = re.split(rf"^{retry['indent']}\}}", probe[retry.end():], maxsplit=1, flags=re.M)[0]
    catch = re.search(r"\bcatch\s*\([^)]*\)\s*\{", body)
    assert catch, "handle a failed navigation inside the retry loop"
    tail = body[catch.end():]
    integer = r"[1-9][\d_]*"
    delay = rf"(?:{integer}|[A-Za-z_$][\w$]*)"
    # A refused connection skips the wait in the frame polling loop.
    remaining = r"deadline\s*-\s*Date\.now\(\)"
    assert re.search(
        rf"await\s+page\.waitForTimeout\(\s*Math\.min\(\s*"
        rf"(?:{delay}\s*,\s*{remaining}|{remaining}\s*,\s*{delay})\s*\)\s*\)", tail,
    ), "back off after a failed attempt within the remaining total budget"

    # Accept a literal cap or a named integer constant for either retention policy.
    constants = re.findall(rf"\bconst\s+(\w+)\s*=\s*{integer}\s*;", probe)
    cap = "(?:" + "|".join([integer, *constants]) + ")"
    attempts = r"result\.attempts"
    guard = r"\s*\)\s*\{?\s*"
    keep_first = rf"\bif\s*\(\s*(?:n|{attempts}\.length)\s*<=?\s*{cap}{guard}{attempts}\.push\("
    drop_oldest = rf"\bif\s*\(\s*{attempts}\.length\s*>=?\s*{cap}{guard}{attempts}\.shift\("
    keep_last = rf"{attempts}\s*=\s*{attempts}\.slice\(\s*-{cap}\s*\)"
    assert any(re.search(pattern, tail) for pattern in (keep_first, drop_oldest, keep_last)), (
        "limit recorded attempts to a constant number"
    )


@pytest.mark.parametrize("value", [
    pytest.param(r"elapsed\w*|waited\w*|totalWait\w*|Date\.now\(\)\s*-", id="total-wait"),
    pytest.param(r"last_?(?:frame_?)?verdict\b", id="last-frame-verdict"),
])
def test_failure_log_reports_total_wait_and_last_frame_verdict(value):
    probe = _probe()
    retry = _navigation_loop(probe)
    # Inspect output after the outer loop closes, skipping the per-attempt log.
    after_attempts = re.split(rf"^{retry['indent']}\}}", probe[retry.end():], maxsplit=1, flags=re.M)[-1]
    logs = re.findall(r"console\.(?:log|warn|error)\((.*?)\);[ \t]*$", after_attempts, re.M | re.S)
    expression = rf"""(?:^|\$\{{|[(:,{{])\s*[^"'`}};]*?(?:{value})"""
    assert any(re.search(expression, log, re.I) for log in logs), "include the value in the final log"
