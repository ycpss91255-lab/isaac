"""Hosted contracts for the Isaac Sim standalone CI job."""
import os
from pathlib import Path
import subprocess

import pytest
import yaml

pytestmark = pytest.mark.core
ROOT = Path(__file__).resolve().parents[3]
JOB = "official-nativepython"


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
    result = subprocess.run(
        ["bash", ROOT / "script/ci/nativepython_in_container.sh", sim, artifacts],
        env={**os.environ, "CALL_LOG": str(log)}, capture_output=True, text=True,
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
    probe = "test/integration/pytest/_kit_extra_args_runner.py"
    assert f"{tmp_path}/{probe}:/workspace/{probe}:ro" in args
