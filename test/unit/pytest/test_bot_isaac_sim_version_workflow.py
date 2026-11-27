"""Workflow contract for the weekly official Isaac Sim version check (#442)."""

import re
import subprocess
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


def test_header_documents_repository_setting_for_creating_prs():
    comments = []
    for line in _BOT.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#"):
            comments.append(line[1:].strip())
        elif line:
            break
    assert "Allow GitHub Actions to create and approve pull requests" in " ".join(comments)


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


def test_manual_dry_run_input_is_an_optional_boolean(workflow):
    events = workflow.get("on", workflow.get(True))
    dry_run = events["workflow_dispatch"]["inputs"]["dry_run"]
    assert dry_run["type"] == "boolean"
    assert dry_run.get("required", False) is False


@pytest.mark.parametrize("dry_run", [False, True])
def test_tracker_receives_dry_run_flag_only_when_requested(workflow, tmp_path, dry_run):
    [step] = [
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if _TRACKER in step.get("run", "")
    ]

    def render(text):
        # The step can select the flag in an Actions expression or in Bash.
        text = re.sub(
            r"\$\{\{\s*inputs\.dry_run\s*&&\s*'--dry-run'\s*\|\|\s*''\s*\}\}",
            "--dry-run" if dry_run else "", text,
        )
        return re.sub(
            r"\$\{\{\s*(?:github\.event\.)?inputs\.dry_run(?:\s*\|\|\s*false)?\s*\}\}",
            str(dry_run).lower(), text,
        )

    tracker = tmp_path / _TRACKER
    tracker.parent.mkdir(parents=True)
    tracker.write_text(
        "import sys\n"
        "with open('args.txt', 'x') as output:\n"
        "    print(*sys.argv[1:], sep='\\n', file=output)\n",
        encoding="utf-8",
    )
    env = {key: render(value) for key, value in step.get("env", {}).items()}
    subprocess.run(["bash", "-e", "-c", render(step["run"])], cwd=tmp_path, env=env, check=True)
    args = (tmp_path / "args.txt").read_text(encoding="utf-8").splitlines()
    assert args[0] == "run"
    assert ("--dry-run" in args) == dry_run


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


def test_main_accepts_manual_dispatch_with_groups():
    main = yaml.safe_load((_WORKFLOWS / "main.yaml").read_text(encoding="utf-8"))
    events = main.get("on", main.get(True))
    assert "groups" in events["workflow_dispatch"]["inputs"]


def test_workflow_and_job_permissions_are_limited_to_tracking_releases(workflow):
    allowed = {"contents", "pull-requests", "issues", "actions"}
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


def test_tracker_has_permission_to_dispatch_main(workflow):
    for job in workflow["jobs"].values():
        if any(_TRACKER in step.get("run", "") for step in job.get("steps", [])):
            grants = job.get("permissions", workflow.get("permissions", {}))
            assert grants.get("actions") == "write"


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
