"""The official Python buckets use the existing scoped GPU workflow."""

import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.core

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "script/ci/official_pythontests.sh"


def test_official_buckets_share_the_core_gpu_job_and_always_upload_reports():
    workflow = yaml.safe_load((ROOT / ".github/workflows/main.yaml").read_text())
    job = workflow["jobs"]["core-gpu"]
    assert "needs.changes.outputs.core == 'true'" in job["if"]
    inputs = job["with"]
    assert HELPER.name in (ROOT / inputs["run-script"]).read_text()
    assert inputs["artifact-path"].splitlines() == [
        "artifacts/startuptests", "artifacts/pythontests",
    ]
    assert inputs["artifact-when"] == "always"
    assert inputs["timeout-minutes"] >= 180


@pytest.mark.parametrize(
    ("mode", "success", "diagnostic"),
    [
        ("pass", True, "sensors: 14/14 passed"),
        ("missing-rtx", False, "missing RTX regression"),
        ("unexpected-actuator-skip", False, "unexpected actuator skip"),
        ("failure", False, "failures=1"),
        ("error", False, "errors=1"),
        ("skip", False, "skipped=1"),
        ("missing", False, "Invalid pythontests report"),
        ("truncated", False, "Invalid pythontests report"),
        ("short", False, "expected at least 17"),
        ("docker", False, "Docker exited with status 23"),
    ],
)
def test_runs_buckets_serially_and_checks_reports(
    tmp_path, monkeypatch, mode, success, diagnostic,
):
    (tmp_path / ".env.generated").write_text("DOCKER_HUB_USER=fixture\nIMAGE_NAME=isaac\n")
    docker = tmp_path / "docker"
    docker.write_text(
        """#!/usr/bin/env python3
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

args = sys.argv[1:]
bucket = args[args.index("--bucket") + 1]
output = args[args.index("--output") + 1]
with Path("calls").open("a") as calls:
    print(bucket, file=calls)
assert args[:2] == ["run", "--rm"]
assert args[args.index("--workdir") + 1] == "/tmp"
assert Path(output).parent == Path("/artifacts")
assert args[args.index("--label") + 1] == "com.docker.compose.project=test-project"
assert args[args.index("--entrypoint") + 1] == "python3"
logs_mount = next(arg for arg in args if arg.endswith(":/artifacts/kit-logs"))
logs = Path(logs_mount.split(":", 1)[0])
(logs / "kit.log").write_text("fixture Kit log")
mount = next(arg for arg in args if arg.endswith(":" + output))
report = Path(mount.split(":", 1)[0])
parser = argparse.ArgumentParser()
parser.add_argument("--script-args", required=True)
settings = parser.parse_args(args[args.index("/isaac-sim/run_tests.py") + 7:]).script_args
mode = os.environ["MODE"] if bucket == "asset" else "pass"
if mode == "missing":
    sys.exit(0)
if mode == "truncated":
    report.write_text("<testsuite")
    sys.exit(0)
count = {"asset": 17, "deprecated": 2, "core": 18, "sensors": 14}[bucket]
if mode == "short":
    count -= 1
suite = ET.Element("testsuite", name=f"pythontests.{bucket}", tests=str(count),
                   failures=str(int(mode == "failure")), errors=str(int(mode == "error")),
                   skipped=str(int(mode == "skip")), time="3.0")
for index in range(count):
    case = ET.SubElement(suite, "testcase", name=f"test-{index}")
    if index == 0 and mode in ("failure", "error", "skip"):
        ET.SubElement(case, "skipped" if mode == "skip" else mode)

def write_kit_results(extension, names, *, skipped=False):
    records = [
        dict(event="stop", test_type="unittest", test_id=f"{extension}.tests.{name}",
             passed=True, skipped=skipped, skip_reason="torch not installed" if skipped else "")
        for name in names
    ]
    directory = logs / ("exttest_" + extension.replace(".", "_"))
    directory.mkdir()
    (directory / "report.jsonl").write_text(chr(10).join(map(json.dumps, records)))

if bucket == "core":
    assert "--/exts/omni.kit.test/testExtDefaultTimeout=600" in settings.split()
    names = [
        f"test_usd_authoring.TestUsdAuthoring.test_neural_{kind}_controller_authored_and_discovered"
        for kind in ("mlp", "lstm")
    ]
    if os.environ["MODE"] == "unexpected-actuator-skip":
        names.append("test_other")
    write_kit_results("isaacsim.core.experimental.actuators", names, skipped=True)
if bucket == "sensors":
    assert "excludeTests/2=" in settings
    assert "TestTiledCameraSensor.test_tiled_data'" in settings
    names = [
        "test_rtx_camera.TestRtxCamera.test_camera_property",
        "test_rtx_camera.TestRtxCamera.test_wrap_regex_multiple_prims",
        "test_camera_sensor.TestCameraSensor.test_data",
        "test_single_view_depth_camera_sensor.TestSingleViewDepthCameraSensor.test_data",
    ]
    if os.environ["MODE"] == "missing-rtx":
        names.pop()
    write_kit_results("isaacsim.sensors.experimental.rtx", names)
ET.ElementTree(suite).write(report)
sys.exit(23 if mode == "docker" else 0)
"""
    )
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")
    monkeypatch.setenv("BASELINE_PROJECT", "test-project")
    monkeypatch.setenv("MODE", mode)
    reports = tmp_path / "artifacts" / "pythontests"
    reports.mkdir(parents=True)
    (reports / "asset.xml").write_text("stale report")
    result = subprocess.run(
        ["bash", HELPER], cwd=tmp_path, capture_output=True, text=True,
    )

    assert (result.returncode == 0) == success, result.stdout + result.stderr
    assert (tmp_path / "calls").read_text().splitlines() == ["asset", "deprecated", "core", "sensors"]
    assert diagnostic in result.stdout + result.stderr
    assert (reports / "deprecated.xml").is_file()
    assert list(reports.glob("sensors.*/kit.log"))
    assert (reports / "asset.xml").read_text() != "stale report"
