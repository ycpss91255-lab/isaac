"""Workflow contract for the weekly official Isaac Sim version check (#442)."""

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.core

_WORKFLOWS = Path(__file__).resolve().parents[3] / ".github/workflows"
_BOT = _WORKFLOWS / "bot-isaac-sim-version.yaml"
_TRACKER = "script/ci/track_isaac_sim.py"


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(_BOT.read_text())


def test_bot_workflow_exists():
    assert _BOT.is_file(), f"Missing workflow: {_BOT.name}"


def test_display_name_matches_the_bot_filename(workflow):
    assert workflow["name"] == "Bot: Isaac Sim Version"


def test_only_weekly_schedule_and_manual_version_override_trigger_the_bot(workflow):
    events = workflow.get("on", workflow.get(True))
    assert set(events) == {"schedule", "workflow_dispatch"}
    [schedule] = events["schedule"]
    minute, hour, day, month, weekday = schedule["cron"].split()
    assert minute.isdigit() and 0 <= int(minute) < 60
    assert hour.isdigit() and 0 <= int(hour) < 24
    assert (day, month) == ("*", "*")
    assert re.fullmatch(r"[0-6]|sun|mon|tue|wed|thu|fri|sat", weekday, re.I)
    override = events["workflow_dispatch"]["inputs"]["current_version"]
    assert override.get("type", "string") == "string"
    assert not override.get("required", False)


def test_workflow_runs_the_tracker_and_does_not_call_main(workflow):
    jobs = workflow["jobs"].values()
    assert any(_TRACKER in step.get("run", "") for job in jobs for step in job.get("steps", []))
    for job in jobs:
        assert not job.get("uses", "").split("@")[0].endswith("/.github/workflows/main.yaml")


def test_main_gate_does_not_depend_on_the_version_bot():
    jobs = yaml.safe_load((_WORKFLOWS / "main.yaml").read_text())["jobs"]
    needs = jobs["gate"]["needs"]
    for dependency in ([needs] if isinstance(needs, str) else needs):
        assert dependency != _BOT.stem
        job = jobs[dependency]
        assert not job.get("uses", "").split("@")[0].endswith(f"/.github/workflows/{_BOT.name}")
        assert all(_TRACKER not in step.get("run", "") for step in job.get("steps", []))


def test_workflow_and_job_permissions_are_limited_to_tracking_releases(workflow):
    allowed = {"contents", "pull-requests", "issues"}
    permissions = [
        job.get("permissions", workflow.get("permissions"))
        for job in workflow["jobs"].values()
    ]
    if "permissions" in workflow:
        permissions.append(workflow["permissions"])
    for grants in permissions:
        assert isinstance(grants, dict), f"Expected explicit, scoped permissions: {grants!r}"
        assert set(grants) <= allowed
        assert set(grants.values()) <= {"none", "read", "write"}


def _expressions(node):
    if isinstance(node, str):
        yield from re.findall(r"\$\{\{(.*?)\}\}", node, re.S)
    elif isinstance(node, dict):
        for key, value in node.items():
            # An Actions "if" condition can omit the expression delimiters.
            if key == "if" and isinstance(value, str):
                yield value
            else:
                yield from _expressions(value)
    elif isinstance(node, list):
        for value in node:
            yield from _expressions(value)


def test_only_the_builtin_github_token_is_used(workflow):
    token = re.compile(
        r"""\b(?:secrets\s*(?:\.\s*GITHUB_TOKEN\b|\[\s*['"]GITHUB_TOKEN['"]\s*\])"""
        r"""|github\s*(?:\.\s*token\b|\[\s*['"]token['"]\s*\]))""",
        re.I,
    )
    expressions = list(_expressions(workflow))
    assert any(token.search(expr) for expr in expressions)
    for expr in expressions:
        assert not re.search(r"\bsecrets\b", token.sub("", expr), re.I)
    for job in workflow["jobs"].values():
        assert job.get("secrets") != "inherit"
