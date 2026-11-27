"""Offline tests for the Isaac Sim version bot's run and CLI entry points."""

import importlib.util
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.core

_SCRIPT = Path(__file__).resolve().parents[3] / "script/ci/track_isaac_sim.py"
_PIN = "6.2.0.1"
_LATEST = "6.2.1"
_OVERRIDE = "6.0.1"
_DOCKERFILE = f'ARG BASE_IMAGE="nvcr.io/nvidia/isaac-sim:{_PIN}"\n'
_BRANCH = f"bot/isaac-sim-{_LATEST}"
_REF = f"refs/heads/{_BRANCH}"
_COMMIT = "b" * 40
_LS_REMOTE = ("git", "ls-remote", "--heads", "origin", _REF)
_GH_API = ("gh", "api", "--paginate", "--slurp")
_DISPATCH = ("gh", "workflow", "run", "main.yaml", "--ref", _BRANCH, "-f", "groups=all")
_TOKEN = "fixture-token"
_DIFF = {"added": {"startup": ["tests-startup.sh"]}, "removed": {}, "renamed": {}}


@pytest.fixture(scope="module")
def tracker():
    spec = importlib.util.spec_from_file_location("track_isaac_sim", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeRepository:
    """Record commands and supply the remote branch and open GitHub items."""

    def __init__(self):
        self.calls = []
        self.remote_head = ""
        self.open_items = {"pulls": [], "issues": []}
        self.pr_body = ""
        self.fail_pr_create = False
        self.pr_appears_on_failure = False
        self.fail_dispatch = False

    def command(self, *args):
        self.calls.append(args)
        if args == _DISPATCH and self.fail_dispatch:
            raise subprocess.CalledProcessError(1, args)
        if args[:2] == ("git", "ls-remote"):
            return self.remote_head
        if args == ("git", "rev-parse", "HEAD"):
            return _COMMIT
        if args[:4] == _GH_API:
            for endpoint, items in self.open_items.items():
                if args[4] == f"repos/{{owner}}/{{repo}}/{endpoint}?state=open&per_page=100":
                    return json.dumps([items])
            pytest.fail(f"Unexpected GitHub API request: {args!r}")
        if args[:2] == ("gh", "api"):
            pytest.fail(f"Expected a paginated, slurped GitHub API request: {args!r}")
        if args[:3] == ("gh", "pr", "create"):
            if self.fail_pr_create:
                if self.pr_appears_on_failure:
                    self.open_items["pulls"].append({"head": {"ref": _BRANCH}, "title": "更新映像"})
                raise subprocess.CalledProcessError(1, args)
            # The tracker removes the temporary body file after creating the PR.
            path = Path(args[args.index("--body-file") + 1])
            self.pr_body = path.read_text(encoding="utf-8")
        return ""


@pytest.fixture
def repo(tracker, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    Path("Dockerfile").write_text(_DOCKERFILE, encoding="utf-8")
    monkeypatch.setenv("BASE_BRANCH", "release")

    def auth_response(url, timeout):
        assert url == tracker.AUTH
        return io.BytesIO(json.dumps({"token": _TOKEN}).encode())

    monkeypatch.setattr(tracker, "urlopen", auth_response)
    monkeypatch.setattr(tracker, "stable_release", Mock(return_value=_LATEST))
    monkeypatch.setattr(tracker, "inventory_diff", Mock(return_value=(_DIFF, False)))
    repository = FakeRepository()
    monkeypatch.setattr(tracker, "command", repository.command)
    return repository


def _assert_no_writes(repo):
    assert not any(call[:3] == ("gh", "workflow", "run") for call in repo.calls)
    git_reads = {("git", "ls-remote"), ("git", "rev-parse")}
    for call in repo.calls:
        assert call[:2] in git_reads or call[:4] == _GH_API, call
    assert Path("Dockerfile").read_text(encoding="utf-8") == _DOCKERFILE


def test_current_pin_skips_writes(tracker, repo):
    tracker.stable_release.return_value = _PIN
    tracker.run("")
    _assert_no_writes(repo)


def test_older_override_at_latest_pin_skips_writes(tracker, repo):
    tracker.stable_release.return_value = _PIN
    tracker.run(_OVERRIDE)

    tracker.inventory_diff.assert_not_called()
    _assert_no_writes(repo)


def test_override_equal_to_latest_with_older_pin_skips_writes(tracker, repo):
    tracker.stable_release.return_value = _LATEST
    # Nothing is newer than the override, so leave the pin for the scheduled run.
    tracker.run(_LATEST)

    tracker.inventory_diff.assert_not_called()
    _assert_no_writes(repo)


def test_new_release_pushes_bump_and_opens_pr_and_inventory_issue(tracker, repo):
    tracker.run("")

    assert ("git", "switch", "-c", _BRANCH) in repo.calls
    assert Path("Dockerfile").read_text(encoding="utf-8") == _DOCKERFILE.replace(_PIN, _LATEST)
    assert any(call[0] == "git" and "commit" in call for call in repo.calls)
    [push] = [call for call in repo.calls if call[:2] == ("git", "push")]
    assert f"--force-with-lease={_REF}:" in push
    assert "--force" not in push
    [pr] = [call for call in repo.calls if call[:3] == ("gh", "pr", "create")]
    assert pr[pr.index("--title") + 1] == f"更新 Isaac Sim 至 {_LATEST}"
    assert pr[pr.index("--head") + 1] == _BRANCH
    assert pr[pr.index("--base") + 1] == "release"
    assert [call for call in repo.calls if call[:3] == ("gh", "workflow", "run")] == [_DISPATCH]
    assert repo.calls.index(pr) < repo.calls.index(_DISPATCH)
    assert sum(call[:3] == ("gh", "issue", "create") for call in repo.calls) == 1


def test_unchanged_inventory_opens_pr_without_issue(tracker, repo):
    tracker.inventory_diff.return_value = ({"added": {}, "removed": {}, "renamed": {}}, False)
    tracker.run("")

    assert any(call[:3] == ("gh", "pr", "create") for call in repo.calls)
    assert not any(call[:3] == ("gh", "issue", "create") for call in repo.calls)


def test_pr_create_failure_deletes_orphan_branch_and_raises(tracker, repo):
    repo.fail_pr_create = True
    repo.open_items["pulls"].append({"head": {"ref": "another-branch"}, "title": "其他更新"})
    with pytest.raises(subprocess.CalledProcessError) as error:
        tracker.run("")

    assert error.value.cmd[:3] == ("gh", "pr", "create")
    after_create = repo.calls[repo.calls.index(error.value.cmd) + 1:]
    [cleanup] = [call for call in after_create if call[:2] == ("git", "push")]
    assert f"--force-with-lease={_REF}:{_COMMIT}" in cleanup
    assert f":{_REF}" in cleanup
    assert "--force" not in cleanup


def test_pr_create_failure_keeps_branch_when_pr_appears(tracker, repo):
    repo.fail_pr_create = True
    repo.pr_appears_on_failure = True
    tracker.run("")

    [pr] = [call for call in repo.calls if call[:3] == ("gh", "pr", "create")]
    after_create = repo.calls[repo.calls.index(pr) + 1:]
    assert not any(call[:2] == ("git", "push") for call in after_create)


def test_dispatch_failure_keeps_created_pr_and_prints_recovery_steps(tracker, repo, capsys):
    repo.fail_dispatch = True
    tracker.run("")

    [pr] = [call for call in repo.calls if call[:3] == ("gh", "pr", "create")]
    after_create = repo.calls[repo.calls.index(pr) + 1:]
    assert _DISPATCH in after_create
    assert not any(call[:3] == ("gh", "pr", "close") for call in after_create)
    assert not any(call[:2] == ("git", "push") for call in after_create)
    captured = capsys.readouterr()
    warning = captured.out + captured.err
    assert re.search(r"\bPR\b|pull request|拉取請求", warning, re.I | re.ASCII)
    assert re.search(
        r"(?:請|需|必須|擁有者|維護者).*?關閉.*?(?:重新開啟|重新打開|重新開放|重開|再開啟)",
        warning, re.S,
    )


def test_existing_remote_branch_skips_writes(tracker, repo):
    repo.remote_head = f"{'a' * 40}\t{_REF}\n"
    tracker.run("")
    assert _LS_REMOTE in repo.calls
    _assert_no_writes(repo)


@pytest.mark.parametrize(
    "endpoint,item",
    [
        ("pulls", {"head": {"ref": "another-branch"}, "title": f"更新映像至 {_LATEST}"}),
        ("issues", {"title": f"追蹤 Isaac Sim {_LATEST} 官方測試清單的討論"}),
    ],
)
def test_unrelated_open_item_with_version_in_title_allows_bump(tracker, repo, endpoint, item):
    repo.open_items[endpoint].append(item)
    tracker.run("")

    assert any(call[:2] == ("git", "push") for call in repo.calls)
    assert any(call[:3] == ("gh", "pr", "create") for call in repo.calls)


@pytest.mark.parametrize(
    "endpoint,item",
    [
        ("pulls", {"head": {"ref": _BRANCH}, "title": "更新映像"}),
        ("issues", {"title": f"追蹤 Isaac Sim {_LATEST} 官方測試清單"}),
    ],
)
def test_existing_bot_pr_or_issue_skips_writes(tracker, repo, endpoint, item):
    repo.open_items[endpoint].append(item)
    tracker.run("")
    _assert_no_writes(repo)


def test_second_run_on_base_branch_skips_existing_pr(tracker, repo):
    tracker.run("")
    [pr] = [call for call in repo.calls if call[:3] == ("gh", "pr", "create")]
    repo.open_items["pulls"].append({
        "head": {"ref": pr[pr.index("--head") + 1]},
        "title": pr[pr.index("--title") + 1],
    })

    # A new checkout of the base branch still contains the old pin.
    Path("Dockerfile").write_text(_DOCKERFILE, encoding="utf-8")
    repo.calls.clear()
    tracker.run("")
    _assert_no_writes(repo)


def test_override_selects_inventory_comparison_in_pr_heading(tracker, repo):
    tracker.run(_OVERRIDE)

    tracker.inventory_diff.assert_called_once_with(_OVERRIDE, _LATEST, _TOKEN)
    assert f"## 官方測試清單（比較 `{_OVERRIDE}` 與 `{_LATEST}`）" in repo.pr_body.splitlines()


def test_dry_run_prints_planned_pr_without_writes(tracker, repo, capsys):
    tracker.run("", dry_run=True)

    _assert_no_writes(repo)
    output = capsys.readouterr().out
    assert f"更新 Isaac Sim 至 {_LATEST}" in output
    assert tracker.render_pr_body(_PIN, _LATEST, _DIFF).strip() in output


def test_dry_run_at_latest_pin_prints_override_comparison(tracker, repo, capsys):
    tracker.stable_release.return_value = _PIN
    tracker.run(_OVERRIDE, dry_run=True)

    _assert_no_writes(repo)
    tracker.inventory_diff.assert_called_once_with(_OVERRIDE, _PIN, _TOKEN)
    output = capsys.readouterr().out
    assert f"更新 Isaac Sim 至 {_PIN}" in output
    assert any(_OVERRIDE in line and _PIN in line for line in output.splitlines())
    assert "官方測試清單" in output
    assert "tests-startup.sh" in output


def test_main_passes_current_version_and_dry_run_to_run(tracker, monkeypatch):
    calls = []

    def record_run(override, dry_run):
        calls.append((override, dry_run))

    monkeypatch.setattr(tracker, "run", record_run)
    tracker.main(["run", "--dry-run", "--current-version=6.0.1"])
    assert calls == [(_OVERRIDE, True)]
