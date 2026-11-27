"""Offline contracts for the Isaac Sim version and test inventory tracker (#442)."""

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

_SCRIPT = Path(__file__).resolve().parents[3] / "script/ci/track_isaac_sim.py"
_STARTUP = "tests-startup.headless.sh"
_STREAM = "tests-startup.streaming.sh"
_CAMERA = "tests-sensor.camera.sh"


@pytest.fixture(scope="module")
def tracker():
    spec = importlib.util.spec_from_file_location("track_isaac_sim", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ngc_tags():
    path = Path(__file__).resolve().parents[2] / "fixtures/ngc_isaac_sim_tags.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_parse_stable_tags_excludes_year_tags(tracker, ngc_tags):
    assert set(tracker.parse_stable_tags(ngc_tags)) == {
        "6.0.1", "6.1.0", "6.2.0", "6.2.0.1",
    }


def test_latest_stable_from_ngc_tags(tracker, ngc_tags):
    assert tracker.latest_stable(tracker.parse_stable_tags(ngc_tags)) == "6.2.0.1"


def test_ngc_tags_list_keeps_only_three_or_four_numeric_components(tracker):
    digest = "sha256-" + "a" * 64
    tags = [
        "6.2.0.1", "6.2.1", "latest", "6.2", "6.2.0.1.2", "v6.2.1",
        "7.0.0-rc.15", "7.0.0-beta.1", "7.0.0-dev",
        digest + ".sig", digest + ".sbom", digest + ".vex",
    ]
    payload = {"name": "nvidia/isaac-sim", "tags": tags}
    assert set(tracker.parse_stable_tags(payload)) == {"6.2.0.1", "6.2.1"}


def test_latest_stable_compares_numeric_components_in_any_tag_order(tracker):
    assert tracker.latest_stable(["6.2.0.10", "6.2.0.9", "6.1.9"]) == "6.2.0.10"
    assert tracker.latest_stable(["6.2.1", "6.2.0.1"]) == "6.2.1"


@pytest.mark.parametrize(
    "current,latest,expected",
    [("6.2.0.1", "6.2.1", True), ("6.2.0.1", "6.2.0.1", False),
     ("6.2.1", "6.2.0.1", False)],
    ids=["upgrade", "same-pin", "never-downgrade"],
)
def test_should_bump_only_for_a_newer_version(tracker, current, latest, expected):
    assert tracker.should_bump(current, latest) is expected


def test_should_bump_rejects_year_tag(tracker):
    with pytest.raises(ValueError):
        tracker.should_bump("6.2.0.1", "2022.2.1")


# The image's run_tests.py matches script basenames against each suite's
# include patterns, then assigns a matching bucket or its default bucket.
def _suite(name, pattern):
    return {"name": name, "include": [pattern], "default_bucket": "default"}


_STARTUP_SUITE = _suite("startuptests", "tests-startup.*")
_SENSOR_SUITE = _suite("sensortests", "tests-sensor.*")


def _inventory(tracker, suites, scripts):
    return tracker.parse_test_config(json.dumps({"suites": suites}), scripts)


def test_added_suite_and_new_script_in_an_existing_suite(tracker):
    old = _inventory(tracker, [_STARTUP_SUITE], [_STARTUP])
    new = _inventory(tracker, [_STARTUP_SUITE, _SENSOR_SUITE], [_STARTUP, _STREAM, _CAMERA])
    diff = tracker.diff_inventory(old, new)
    assert diff["added"] == {"startuptests": [_STREAM], "sensortests": [_CAMERA]}
    assert not diff["removed"]
    assert not diff["renamed"]


def test_removed_suite_and_missing_script_in_a_retained_suite(tracker):
    old = _inventory(tracker, [_STARTUP_SUITE, _SENSOR_SUITE], [_STARTUP, _STREAM, _CAMERA])
    new = _inventory(tracker, [_STARTUP_SUITE], [_STARTUP])
    diff = tracker.diff_inventory(old, new)
    assert diff["removed"] == {"startuptests": [_STREAM], "sensortests": [_CAMERA]}
    assert not diff["added"]
    assert not diff["renamed"]


def test_reordered_scripts_leave_inventory_unchanged(tracker):
    old = _inventory(tracker, [_STARTUP_SUITE], [_STARTUP, _STREAM])
    new = _inventory(tracker, [_STARTUP_SUITE], [_STREAM, _STARTUP])
    diff = tracker.diff_inventory(old, new)
    assert not diff["added"]
    assert not diff["removed"]
    assert not diff["renamed"]


def test_same_suite_contents_under_a_new_name_are_reported_as_a_rename(tracker):
    scripts = [_STARTUP, _STREAM]
    old = _inventory(tracker, [_STARTUP_SUITE], scripts)
    new = _inventory(tracker, [_suite("boot", "tests-startup.*")], scripts)
    diff = tracker.diff_inventory(old, new)
    assert diff["renamed"] == {"startuptests": "boot"}
    assert not diff["added"]
    assert not diff["removed"]


def test_pr_body_describes_the_inventory_diff_in_traditional_chinese(tracker, monkeypatch):
    fake_token = "ghs_" + "a" * 36
    monkeypatch.setenv("GH_TOKEN", fake_token)
    monkeypatch.setenv("NGC_TOKEN", "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ0ZXN0In0.fixture")
    old = _inventory(tracker, [_STARTUP_SUITE, _SENSOR_SUITE], [_STARTUP, _CAMERA])
    new = _inventory(
        tracker,
        [_STARTUP_SUITE, _suite("vision", "tests-sensor.*")],
        [_STREAM, _CAMERA, f"tests-startup.{fake_token}.sh"],
    )
    body = tracker.render_pr_body("6.2.0.1", "6.2.1", tracker.diff_inventory(old, new))
    for value in ("6.2.0.1", "6.2.1", _STARTUP, _STREAM, "sensortests", "vision"):
        assert value in body
    for label in (r"測試清單|測試列表", r"新增|加入", r"刪除|移除", r"改名|更名|重新命名"):
        assert re.search(label, body)
    assert not re.search(r"gh[pousr]_\w+|github_pat_\w+|eyJ[\w-]+\.[\w-]+\.[\w-]+", body)
    assert not re.search(r"\bBearer\s+\S+", body, re.I)


@pytest.mark.parametrize(
    "prs,issues,expected",
    [
        ([{"headRefName": "bot/isaac-sim-6.2.1", "title": "更新映像"}], [], False),
        ([], [{"title": "追蹤 Isaac Sim 6.2.1 官方測試清單"}], False),
        ([{"headRefName": "update-sim", "title": "更新 Isaac Sim 至 6.2.1"}], [], True),
        ([], [{"title": "Dockerfile 仍寫 6.2.1"}], True),
        ([], [{"title": "追蹤 6.2.1.1 測試清單"}], True),
        ([{"headRefName": "bot/isaac-sim-6.2.10", "title": "更新至 6.2.10"}], [], True),
        ([], [], True),
    ],
    ids=["bot-branch", "bot-issue", "pr-title-only", "unrelated-issue",
         "other-issue-version", "other-branch-version", "first-run"],
)
def test_should_open_checks_open_prs_and_issues_for_exact_version(tracker, prs, issues, expected):
    assert tracker.should_open("6.2.1", open_prs=prs, open_issues=issues) is expected


def test_read_and_update_only_the_base_image_pin(tracker, tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    old_pin = 'ARG BASE_IMAGE="nvcr.io/nvidia/isaac-sim:6.2.0.1"'
    new_pin = 'ARG BASE_IMAGE="nvcr.io/nvidia/isaac-sim:6.2.1"'
    lines = [
        "# Previous image: nvcr.io/nvidia/isaac-sim:6.2.0.1",
        old_pin,
        "FROM ${BASE_IMAGE} AS sys",
        "ARG BASE_IMAGE",
        "",
    ]
    dockerfile.write_text("\n".join(lines))
    assert tracker.read_base_version(dockerfile) == "6.2.0.1"
    tracker.update_base_version(dockerfile, "6.2.1")
    assert dockerfile.read_text() == "\n".join(lines).replace(old_pin, new_pin)
    assert tracker.read_base_version(dockerfile) == "6.2.1"


def test_read_base_version_rejects_year_pin(tracker, tmp_path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text('ARG BASE_IMAGE="nvcr.io/nvidia/isaac-sim:2022.2.1"\n')
    with pytest.raises(ValueError):
        tracker.read_base_version(dockerfile)


@pytest.mark.parametrize(
    "current,target",
    [("2022.2.1", "6.2.0.1"), ("6.2.0.1", "2022.2.1")],
    ids=["year-pin", "year-target"],
)
def test_update_base_version_rejects_year_pin(tracker, tmp_path, current, target):
    dockerfile = tmp_path / "Dockerfile"
    original = f'ARG BASE_IMAGE="nvcr.io/nvidia/isaac-sim:{current}"\n'
    dockerfile.write_text(original)
    with pytest.raises(ValueError):
        tracker.update_base_version(dockerfile, target)
    assert dockerfile.read_text() == original
