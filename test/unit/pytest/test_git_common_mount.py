"""Git metadata mounts for the hosted pytest containers (isaac#574)."""

import shlex
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "script/ci/git_common_mount.sh"


@pytest.fixture
def clone(tmp_path):
    origin = tmp_path / "origin"
    repo = tmp_path / "clone"
    subprocess.run(["git", "init", origin], check=True)
    subprocess.run(
        [
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.org",
            "commit", "--allow-empty", "-m", "Initial commit",
        ],
        cwd=origin,
        check=True,
    )
    subprocess.run(["git", "clone", origin, repo], check=True)
    return repo


def mount_output(repo):
    return subprocess.check_output(["bash", HELPER, repo], cwd=repo.parent, text=True)


def test_normal_clone_needs_no_extra_mount(clone):
    assert mount_output(clone) == ""


def test_worktree_mounts_common_git_dir_at_same_path(clone, tmp_path):
    worktree = tmp_path / "worktree"
    subprocess.run(["git", "worktree", "add", "--detach", worktree], cwd=clone, check=True)

    common_dir = (clone / ".git").resolve()
    mount = f"{common_dir}:{common_dir}"
    assert shlex.split(mount_output(worktree)) in (["-v", mount], ["-v", f"{mount}:ro"])


def test_both_baseline_docker_runs_reference_mount_helper():
    source = (ROOT / "test/assert_pytest_baseline.sh").read_text().replace("\\\n", " ")
    runs = [line for line in source.splitlines() if line.lstrip().startswith("docker run ")]
    assert sum(HELPER.name in run for run in runs) >= 2
