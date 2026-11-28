"""Gate the official script-level JUnit and selected Kit unittest results."""

import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


MINIMUM = {"asset": 17, "deprecated": 2, "core": 18, "sensors": 14}
RTX_EXTENSION = "isaacsim.sensors.experimental.rtx"
ACTUATORS_EXTENSION = "isaacsim.core.experimental.actuators"

# Isaac Sim 6.2.0.1 official image reproduces Warp CUDA error 700 on this
# case. The shell runner excludes only that unittest ID.
TILED_CASE = "test_tiled_camera_sensor.TestTiledCameraSensor.test_tiled_data"
RTX_REGRESSIONS = (
    "test_rtx_camera.TestRtxCamera.test_camera_property",
    "test_rtx_camera.TestRtxCamera.test_wrap_regex_multiple_prims",
    "test_camera_sensor.TestCameraSensor.test_data",
    "test_single_view_depth_camera_sensor.TestSingleViewDepthCameraSensor.test_data",
)
# Both cases skip with this reason in the official 6.2.0.1 image, which lacks
# torch. They may pass when torch is present, but failures still fail the gate.
ACTUATOR_SKIP_REASON = "torch not installed"
ACTUATOR_SKIPS = {
    f"test_usd_authoring.TestUsdAuthoring.test_neural_{kind}_controller_authored_and_discovered"
    for kind in ("mlp", "lstm")
}


def kit_results(output_dir, extension):
    prefix = f"exttest_{extension.replace('.', '_')}"
    for report in output_dir.glob(f"{prefix}*/report.jsonl"):
        for line in report.read_text().splitlines():
            result = json.loads(line)
            if result["event"] == "stop" and result["test_type"] == "unittest":
                yield result["test_id"].split(".tests.", 1)[-1], result


def check_kit(bucket, output_dir):
    if bucket == "core":
        results = dict(kit_results(output_dir, ACTUATORS_EXTENSION))
        for case, result in results.items():
            if result["skipped"]:
                reason = result["skip_reason"]
                if case not in ACTUATOR_SKIPS or reason != ACTUATOR_SKIP_REASON:
                    raise ValueError(f"unexpected actuator skip: {case}: {reason}")
                print(f"allowed actuator skip: {case}: {reason}")
        missing = ACTUATOR_SKIPS - results.keys()
        if missing:
            raise ValueError(f"missing actuator cases: {', '.join(sorted(missing))}")
    if bucket == "sensors":
        results = dict(kit_results(output_dir, RTX_EXTENSION))
        if TILED_CASE in results:
            raise ValueError("RTX tiled-data exclusion did not take effect")
        for case in RTX_REGRESSIONS:
            result = results.get(case)
            if result is None or not result["passed"] or result["skipped"]:
                raise ValueError(f"missing RTX regression pass: {case}")
            print(f"RTX regression passed: {case}")


def check_report(bucket, path):
    suite = ET.parse(path).getroot()
    if suite.tag != "testsuite" or suite.get("name") != f"pythontests.{bucket}":
        raise ValueError(f"expected testsuite pythontests.{bucket}")
    total = int(suite.attrib["tests"])
    cases = suite.findall("testcase")
    minimum = MINIMUM[bucket]
    if total != len(cases) or total < minimum:
        raise ValueError(f"expected at least {minimum} cases with matching totals, got {total}/{len(cases)}")
    failures = int(suite.attrib["failures"])
    errors = int(suite.attrib["errors"])
    skipped = int(suite.get("skipped", "0"))
    for tag, count in (("failure", failures), ("error", errors), ("skipped", skipped)):
        if len(suite.findall(f"testcase/{tag}")) != count:
            raise ValueError(f"inconsistent {tag} count")
    seconds = float(suite.attrib["time"])
    print(f"{bucket}: {total - failures - errors - skipped}/{total} passed in {seconds:.1f}s"
          f" (failures={failures}, errors={errors}, skipped={skipped})")
    return not any((failures, errors, skipped))


if __name__ == "__main__":
    bucket, path, output_dir = sys.argv[1:]
    try:
        if not check_report(bucket, path):
            sys.exit(1)
        check_kit(bucket, Path(output_dir))
    except (OSError, ET.ParseError, ValueError, KeyError) as exc:
        sys.exit(f"Invalid pythontests report for {bucket}: {exc}")
