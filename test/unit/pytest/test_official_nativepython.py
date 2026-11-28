"""Hosted contracts for the Isaac Sim standalone CI job."""
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
from textwrap import dedent
import time
import xml.etree.ElementTree as ET

import pytest
import yaml

pytestmark = pytest.mark.core
ROOT = Path(__file__).resolve().parents[3]
JOB = "official-nativepython"
WATCHDOG = ROOT / "script/ci/bucket_watchdog.py"


def test_scope_and_required_gate():
    jobs = yaml.safe_load((ROOT / ".github/workflows/main.yaml").read_text())["jobs"]
    job = jobs[f"core-{JOB}"]
    assert job["needs"] == ["changes", "core-unit"]
    assert "needs.changes.outputs.core == 'true'" in job["if"]
    assert "github.event.pull_request.head.repo.full_name == github.repository" in job["if"]
    assert f"core-{JOB}" in jobs["gate"]["needs"]


def test_gpu_workflow_uploads_results_even_on_failure():
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/ci-official-native-python.yaml").read_text()
    )
    assert set(workflow[True]) == {"workflow_call", "workflow_dispatch"}
    assert "concurrency" not in workflow
    job = workflow["jobs"][f"core-{JOB}"]
    assert "/gpu-self-hosted.yml@" in job["uses"]
    assert job["with"]["artifact-when"] == "always"
    assert job["with"]["artifact-path"] == f"artifacts/{JOB}"
    assert job["with"]["reap-container-filter"].startswith(
        "label=com.docker.compose.project=isaac-official-nativepython-"
    )


def test_gpu_workflow_step_timeout_leaves_time_for_artifacts():
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/ci-official-native-python.yaml").read_text()
    )
    inputs = workflow["jobs"][f"core-{JOB}"]["with"]
    assert inputs["timeout-minutes"] == 60
    assert 55 <= inputs["step-timeout-minutes"] < inputs["timeout-minutes"]


@pytest.fixture(scope="module")
def watchdog():
    """Load the watchdog from the script used by the workflow."""
    spec = importlib.util.spec_from_file_location("bucket_watchdog", WATCHDOG)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_watchdog_default_case_timeout(watchdog):
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/ci-official-native-python.yaml").read_text()
    )
    inputs = workflow["jobs"][f"core-{JOB}"]["with"]
    timeout = watchdog.DEFAULT_CASE_TIMEOUT_SECONDS
    assert timeout == 1500
    # Issue #437 recorded a 712-second Carter camera case under load.
    assert 2 * 712 <= timeout < inputs["step-timeout-minutes"] * 60


@pytest.mark.parametrize(
    "readme", ["README.md", "doc/README.zh-TW.md", "doc/README.zh-CN.md", "doc/README.ja.md"]
)
def test_readmes_state_watchdog_default_timeout(watchdog, readme):
    """Check the documented per-case timeout for the standalone CI job."""
    paragraphs = (ROOT / readme).read_text(encoding="utf-8").split("\n\n")
    paragraph = next((p for p in paragraphs if f"core-{JOB}" in p), "")
    assert f"{watchdog.DEFAULT_CASE_TIMEOUT_SECONDS}" in paragraph
    assert "600" not in paragraph


def test_watchdog_documents_runner_assumption(watchdog):
    assert "subprocess.run" in watchdog.__doc__
    assert "print_live_output" in watchdog.__doc__


def test_watchdog_times_out_one_case_and_finishes_bucket(tmp_path):
    runner = tmp_path / "run_tests.py"
    report = tmp_path / "testing.xml"
    runner.write_text(dedent("""\
        from pathlib import Path
        import subprocess
        import sys
        import xml.etree.ElementTree as ET

        if __name__ == "__main__":
            assert sys.argv == [__file__, "--output", str(Path.cwd() / "testing.xml")]
            suite = ET.Element("testsuite")
            cases = [
                ("hung", "echo $$ > hung.pid; sleep 60 & echo $! > sleep.pid; wait"),
                ("quick", "echo passed > quick.result"),
            ]
            for name, command in cases:
                case = ET.SubElement(suite, "testcase", name=name)
                try:
                    subprocess.run(["sh", "-c", command], check=True)
                except Exception as exc:
                    ET.SubElement(case, "failure", type=type(exc).__name__)
            ET.ElementTree(suite).write(sys.argv[2])
            sys.exit(17)
        """))

    start = time.monotonic()
    try:
        # The background sleep inherits stdout. A surviving descendant would
        # keep the capture pipe open even after the case shell exits.
        result = subprocess.run(
            [sys.executable, WATCHDOG, runner, "--output", report], cwd=tmp_path,
            env={**os.environ, "CASE_TIMEOUT_SECONDS": "1"},
            capture_output=True, text=True, timeout=20,
        )
    except subprocess.TimeoutExpired:
        # Clean up the fake case if the watchdog leaves the capture pipe open.
        for pid_file in tmp_path.glob("*.pid"):
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass
        raise

    assert time.monotonic() - start < 20
    assert result.returncode == 17, result.stdout + result.stderr
    suite = ET.parse(report).getroot()
    failure = suite.find("testcase[@name='hung']/failure")
    assert failure is not None and failure.get("type") == "TimeoutExpired"
    quick = suite.find("testcase[@name='quick']")
    assert quick is not None and quick.find("failure") is None
    assert (tmp_path / "quick.result").read_text().strip() == "passed"
    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / "hung.pid").read_text()), 0)


@pytest.mark.parametrize(
    "failures, count, bucket_rc, example_rc, driver_marker, expected",
    [
        (0, 41, 0, 0, "1", 0),
        (1, 41, 0, 0, "1", 1),
        (0, 40, 0, 0, "1", 1),
        (0, 41, 17, 0, "1", 17),
        (0, 41, 0, 23, "1", 23),
        (0, 0, 0, 0, "1", 1),
        (0, 41, 0, 0, "None", 1),
    ],
)
def test_container_suite_and_examples(
    tmp_path, failures, count, bucket_rc, example_rc, driver_marker, expected
):
    sim = tmp_path / "sim"
    scripts = sim / "tests"
    scripts.mkdir(parents=True)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    log = tmp_path / "calls"
    runner = sim / "run_tests.py"
    runner.write_text(
        "import sys\nfrom pathlib import Path\n"
        "assert Path.cwd() != Path(__file__).resolve().parent\n"
        "Path('_out_motion_blur_probe').mkdir()\n"
        "assert sys.argv[1:5] == ['--suite', 'nativepythontests', '--bucket', 'testing']\n"
        "assert sys.argv[5] == '--output'\n"
        f"report = '<testsuite name=\"nativepythontests.testing\" tests=\"{count}\" "
        f"failures=\"{failures}\" errors=\"0\">'\n"
        f"report += '<testcase/>' * {count} + '</testsuite>'\n"
        f"Path(sys.argv[6]).write_text(report if {count} else '')\n"
        f"sys.exit({bucket_rc})\n"
    )
    for sample in ("livestream", "hello_world"):
        path = scripts / f"tests-nativepython-isaacsim.simulation_app.{sample}.sh"
        path.write_text(f'echo {sample} >> "$CALL_LOG"\nexit {example_rc if sample == "livestream" else 0}\n')
    python_sh = sim / "python.sh"
    python_sh.write_text(
        "#!/bin/bash\nset -eu\n"
        'test "$1" = /workspace/test/integration/pytest/_kit_extra_args_runner.py\n'
        'test "$2 $3 $4" = "--script-dir /workspace/framework --usd-path"\n'
        'test -s "$5"\n'
        'test "$ISAAC_LIVESTREAM" = ""\n'
        'test "$ISAAC_KIT_EXTRA_ARGS" = "--/app/isaac_test/marker=1"\n'
        f'echo "[MARKER] {driver_marker}"\n'
    )
    python_sh.chmod(0o755)
    # Resolve the Docker-only mount when the container script runs on the host.
    python3 = tmp_path / "python3"
    python3.write_text(
        '#!/bin/bash\nif [[ "$1" == /tmp/bucket_watchdog.py ]]; then\n'
        '  shift\n  set -- "$TEST_WATCHDOG" "$@"\nfi\n'
        'exec "$TEST_PYTHON" "$@"\n'
    )
    python3.chmod(0o755)
    result = subprocess.run(
        ["bash", ROOT / "script/ci/nativepython_in_container.sh", sim, artifacts],
        env={**os.environ, "CALL_LOG": str(log), "PATH": f"{tmp_path}:{os.environ['PATH']}",
             "TEST_WATCHDOG": str(WATCHDOG), "TEST_PYTHON": sys.executable},
        capture_output=True, text=True,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    assert log.read_text().splitlines() == ["livestream", "hello_world"]
    assert (artifacts / "testing.xml").is_file()
    assert (artifacts / "driver.log").read_text().strip() == f"[MARKER] {driver_marker}"
    for sample in ("livestream", "hello_world"):
        assert (artifacts / f"{sample}.log").is_file()


def test_docker_mounts_and_network(tmp_path):
    docker = tmp_path / "docker"
    log = tmp_path / "docker-args"
    docker.write_text('#!/bin/bash\nprintf "%s\\n" "$@" > "$DOCKER_ARGS"\n')
    docker.chmod(0o755)
    (tmp_path / ".env.generated").write_text("DOCKER_HUB_USER=example\nIMAGE_NAME=isaac\n")
    result = subprocess.run(
        ["bash", ROOT / "script/ci/official_nativepython.sh"], cwd=tmp_path,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
             "DOCKER_ARGS": str(log), "BASELINE_PROJECT": "isaac-official-nativepython-1-1"},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    args = log.read_text().splitlines()
    assert args[args.index("--network") + 1] == "bridge"
    assert "/isaac-sim/_testoutput:mode=1777" in args
    assert "com.docker.compose.project=isaac-official-nativepython-1-1" in args
    assert "example/isaac:headless" in args
    assert args[args.index("--gpus") + 1] == "all"
    assert f"{tmp_path}/artifacts/{JOB}:/artifacts" in args
    assert f"{tmp_path}/framework:/workspace/framework:ro" in args
    watchdog_mount = f"{tmp_path}/script/ci/bucket_watchdog.py:/tmp/bucket_watchdog.py:ro"
    assert ("-v", watchdog_mount) in zip(args, args[1:])
    probe = "test/integration/pytest/_kit_extra_args_runner.py"
    assert f"{tmp_path}/{probe}:/workspace/{probe}:ro" in args
