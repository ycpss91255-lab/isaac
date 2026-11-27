"""Drive the GPU job's real shell entry point against Tier A's fake stack.

run.sh records bring-up, docker supplies Kit output and browser bind-mount
writes, and curl supplies viewer readiness. Only the port checks use sockets.
"""

import errno
import os
import re
import runpy
import shutil
import socket
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

pytestmark = pytest.mark.stream

_ROOT = Path(__file__).resolve().parents[3]
_JOB = Path("script/ci/stream_visual_e2e_job.sh")
_VIEWER = "ghcr.io/ycpss91255-docker/omniverse_web_viewer:0.3.0"
_BROWSER = "mcr.microsoft.com/playwright:v1.62.1-noble"
_ARTIFACTS = Path("artifacts/stream-visual-e2e")

_DOCKER = r"""
if [[ "$1" == compose ]]; then
    printf 'docker %s profiles=%s\n' "$*" "${COMPOSE_PROFILES:-}" >> "$CALLS"
else
    printf 'docker %s\n' "$*" >> "$CALLS"
fi
case "$1" in
    compose)
        [[ " $* " != *" ps -q stream "* ]] || echo fake-stream
        ;;
    inspect)
        if [[ "$*" == *RestartCount* ]]; then echo "true 0"; else echo true; fi
        ;;
    exec)
        if [[ "$*" == *runheadless-host-config.sh* ]]; then
            # Same host mount used by Tier A when Kit redirects its stdout.
            if [[ "$*" =~ /isaac-sim/kit/logs/([a-zA-Z0-9._-]+\.log) ]]; then
                cat "$KIT" > "isaac-sim/kit/logs/${BASH_REMATCH[1]}"
            fi
        fi
        ;;
    logs) cat "$KIT" ;;
    run)
        if [[ "$*" == *mcr.microsoft.com/playwright:* ]]; then
            # The test starts the job in its own process group, like the runner.
            if [[ "$CASE" == terminate ]]; then kill -TERM 0; fi
            # The prototype writes OUT_DIR=/out through this bind mount.
            for arg do
                case "$arg" in *:/out|*:/out:rw) out="${arg%:/out*}" ;; esac
            done
            mkdir -p "${out:?browser must mount its output directory}"
            if [[ "$CASE" == bad-frame ]]; then
                echo '{"pass":false}' > "$out/result.json"
                echo trace-from-browser > "$out/trace.zip"
                echo screenshot-from-browser > "$out/frame.png"
                exit 1
            fi
            echo '{"pass":true}' > "$out/result.json"
            echo png-from-browser > "$out/frame.png"
        else
            echo fake-viewer
        fi
        ;;
esac
"""


def _stub(path, body):
    path.write_text("#!/usr/bin/env bash\nset -eu\n" + body + "\n")
    path.chmod(0o755)


@pytest.fixture
def run_job(tmp_path):
    def run(run_id=17301, attempt=1, case="good", **overrides):
        assert (_ROOT / _JOB).is_file(), "missing stream visual GPU job entry point"
        root = tmp_path / f"{run_id}-{attempt}-{case}"
        shutil.copytree(_ROOT / "script/ci", root / "script/ci")
        shutil.copy(_ROOT / "script/host_yaml.sh", root / "script")
        bin_dir = root / "bin"
        bin_dir.mkdir()
        _stub(root / "script/setup.sh", """
echo "setup $*" >> "$CALLS"
printf 'IMAGE_NAME=isaac\nUSER_NAME=alice\nPROJECT_NAME=alice-isaac\nWS_PATH=/wrong\n' > .env.generated
echo 'name: ${PROJECT_NAME}' > compose.yaml
""")
        _stub(root / "script/build.sh", 'echo "build $* shared=${ISAAC_ALLOW_SHARED_IDENTITY:-}" >> "$CALLS"')
        _stub(root / "script/run.sh", """
source .env.generated
echo "up $* project=$PROJECT_NAME" >> "$CALLS"
test "$WS_PATH" = "$GITHUB_WORKSPACE" && test -w isaac-sim/kit/logs
""")
        _stub(bin_dir / "docker", _DOCKER)
        _stub(bin_dir / "curl", "exit 0")
        kit = root / "fake-kit-stdout"
        markers = ["kit-output-from-this-run", "Started primary stream server", "App is loaded."]
        if case != "timeout":
            markers.append("[SBF] scene ready")
        kit.write_text("\n".join(markers) + "\n")
        calls = root / "calls"
        calls.touch()
        env = dict(PATH=f"{bin_dir}:{os.environ['PATH']}", HOME=str(root),
                   DOCKER_HOST="unix:///nonexistent-visual-test.sock",
                   CALLS=str(calls), CASE=case, KIT=str(kit), GITHUB_WORKSPACE=str(root),
                   GITHUB_RUN_ID=str(run_id), GITHUB_RUN_ATTEMPT=str(attempt),
                   SMOKE_TIMEOUT="1", SMOKE_POLL="1", **overrides)
        result = subprocess.run(["bash", str(_JOB)], cwd=root, env=env, timeout=12, start_new_session=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return result, calls.read_text().splitlines(), root / _ARTIFACTS
    return run


def _one(lines, prefix, contains=""):
    found = [line for line in lines if line.startswith(prefix) and contains in line]
    assert len(found) == 1, (prefix, contains, lines)
    return found[0]


def _value(line, key):
    match = re.search(r"(?:^|\s)" + re.escape(key) + r"(\S+)", line)
    assert match, (key, line)
    return match[1]


def _ports(lines):
    viewer = _one(lines, "docker run ", _VIEWER)
    return int(_value(viewer, "SIGNALING_PORT=")), int(_value(viewer, "SERVE_PORT="))


def _check_cleanup(lines):
    project = _value(_one(lines, "up "), "project=")
    down = _one(lines, "docker compose ", " down ")
    assert f"-p {project} " in down and "--remove-orphans" in down
    assert any(profile in down.split() for profile in ("profiles=*", "profiles=stream")) or (
        "--profile stream " in down or "--profile * " in down
    ), "profile-blind compose down leaves the producer running"
    assert f"-p {project} " in _one(lines, "docker compose ", " ps -q stream")
    for image in (_VIEWER, _BROWSER):
        launch = _one(lines, "docker run ", image)
        name = _value(launch, "--name ")
        assert name.startswith(project + "-")
        assert any(line.startswith("docker rm -f ") and name in line.split()
                   for line in lines[lines.index(launch) + 1:]), (name, lines)
    assert lines.index(down) > lines.index(_one(lines, "docker run ", _BROWSER))
    return project


def test_job_uses_gpu_lib_and_tier_a_stream_bringup(run_job):
    result, lines, artifacts = run_job()
    assert result.returncode == 0, result.stdout
    assert "gpu_job_lib.sh" in (_ROOT / _JOB).read_text()
    assert lines.index("setup apply") < lines.index("build -t stream shared=1")
    assert lines.index("build -t stream shared=1") < lines.index(_one(lines, "up -t stream -d"))
    producer = _one(lines, "docker exec ", "runheadless-host-config.sh")
    assert "fake-stream" in producer and "--exec" in producer and "min_scene.py" in producer
    viewer = _one(lines, "docker run ", _VIEWER)
    assert "VIEWER_UI_MODE=stream-only" in viewer
    signal, serve = _ports(lines)
    assert 0 < signal <= 65535 and 0 < serve <= 65535 and signal != serve
    assert f"ISAAC_SIGNAL_PORT={signal}" in producer.split()
    browser = _one(lines, "docker run ", _BROWSER)
    assert f"http://127.0.0.1:{serve}" in browser and "probe.mjs" in browser
    assert (artifacts / "result.json").is_file() and (artifacts / "frame.png").is_file()
    _check_cleanup(lines)


def test_ports_and_resource_names_are_per_run(run_job):
    projects = []
    ports = []
    for run_id, attempt in ((17301, 1), (17302, 1), (17301, 2)):
        result, lines, _ = run_job(run_id, attempt)
        assert result.returncode == 0, result.stdout
        project = _check_cleanup(lines)
        assert project.endswith(f"-{run_id}-{attempt}")
        projects.append(project)
        ports.append(_ports(lines))
    assert len(set(projects)) == 3
    prefixes = {p.rsplit("-", 2)[0] for p in projects}
    assert len(prefixes) == 1 and prefixes.pop().startswith("isaac-")
    assert ports[0][0] != ports[1][0], "signal port cannot be a fixed 49100"
    assert ports[0][1] != ports[1][1], "viewer port must also change between runs"


def test_browser_failure_reaches_ci_with_all_evidence_and_teardown(run_job):
    result, lines, artifacts = run_job(case="bad-frame")
    assert result.returncode != 0
    _check_cleanup(lines)
    assert any("kit-output-from-this-run" in p.read_text() for p in artifacts.glob("*.log"))
    assert (artifacts / "trace.zip").read_text().strip() == "trace-from-browser"
    assert (artifacts / "frame.png").read_text().strip() == "screenshot-from-browser"
    assert (artifacts / "result.json").read_text().strip() == '{"pass":false}'


def test_term_during_probe_removes_viewer_browser_and_compose_project(run_job):
    result, lines, _ = run_job(case="terminate")
    assert result.returncode != 0
    _check_cleanup(lines)


def test_scene_timeout_preserves_current_kit_log_and_stops_before_probe(run_job):
    result, lines, artifacts = run_job(case="timeout")
    assert result.returncode != 0
    _one(lines, "docker exec ", "runheadless-host-config.sh")
    assert not any(_BROWSER in line for line in lines)
    project = _value(_one(lines, "up "), "project=")
    assert f"-p {project} " in _one(lines, "docker compose ", " down ")
    assert any("kit-output-from-this-run" in p.read_text() for p in artifacts.glob("*.log"))


@contextmanager
def _occupied(port, kind):
    # A pre-existing listener supplies the same occupied-port condition.
    with socket.socket(socket.AF_INET, kind) as sock:
        try:
            sock.bind(("0.0.0.0", port))
        except OSError as error:
            if error.errno != errno.EADDRINUSE:
                raise
        else:
            if kind == socket.SOCK_STREAM:
                sock.listen()
        yield


@pytest.mark.parametrize("key, index, kind", [
    ("ISAAC_SIGNAL_PORT", 0, socket.SOCK_STREAM),
    ("SERVE_PORT", 1, socket.SOCK_DGRAM),
    ("ISAAC_MEDIA_PORT", None, socket.SOCK_DGRAM),
])
def test_occupied_port_is_reselected_or_fails_before_bringup(run_job, key, index, kind):
    result, lines, _ = run_job()
    assert result.returncode == 0, result.stdout
    # Kit's default media port is UDP 47998 unless the stream launcher
    # explicitly passes ISAAC_MEDIA_PORT. Hold that port over the second run.
    port = 47998 if index is None else _ports(lines)[index]
    with _occupied(port, kind):
        result, lines, _ = run_job(case="occupied", **{key: str(port)})
    if result.returncode:
        assert not any(line.startswith("up ") for line in lines)
        assert str(port) in result.stdout, result.stdout
    elif index is None:
        producer = _one(lines, "docker exec ", "runheadless-host-config.sh")
        assert int(_value(producer, "ISAAC_MEDIA_PORT=")) != port
    else:
        assert _ports(lines)[index] != port


def test_port_preflight_handles_both_protocols_on_the_same_candidate():
    # Force the actual preflight predicate to examine an occupied candidate.
    # A bind(0) chooser might otherwise dodge the collision by chance.
    helper = _ROOT / "script/ci/visual_e2e/ports.py"
    assert helper.is_file(), "missing visual job port preflight"
    available = runpy.run_path(str(helper))["port_available"]
    for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
        with socket.socket(socket.AF_INET, kind) as sock:
            sock.bind(("0.0.0.0", 0))
            if kind == socket.SOCK_STREAM:
                sock.listen()
            assert not available(sock.getsockname()[1])


def test_visual_driver_shares_one_playwright_version():
    ci = _ROOT / "script/ci"
    driver = ci / "stream_visual_e2e.sh"
    assert driver.is_file(), "missing visual stream driver"
    sources = [driver, _ROOT / _JOB, *(ci / "visual_e2e").rglob("*")]
    # The resolved browser image is checked at launch above. A shared pin
    # can also live in the existing Tier A helpers.
    versions = sum(p.read_text().count("1.62.1") for p in sources
                   if p.suffix in {".sh", ".mjs", ".py"} and p.is_file())
    assert versions <= 1, "derive the image and npm version from the same pin"
