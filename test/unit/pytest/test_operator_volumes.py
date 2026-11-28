"""Exercise the run hook with real base TOML parsing and stubbed host setup."""

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

REPO = Path(__file__).resolve().parents[3]
REPO_VOLUMES = """\
[[volumes]]
source = "${WS_PATH}"
target = "/work"

[[volumes]]
source = "${WS_PATH}/cache dir"
target = "/cache"

[[volumes]]
source = "${WS_PATH}/logs"
target = "/logs"
"""
MODEL_VOLUME = """\
[[volumes]]
source = "./models"
target = "/models"
mode = "ro"
"""


@pytest.fixture
def run_hook(tmp_path):
    (tmp_path / "setup.toml").write_text(REPO_VOLUMES, encoding="utf-8")
    (tmp_path / ".base").symlink_to(REPO / ".base", target_is_directory=True)
    script = tmp_path / "script"
    script.mkdir()
    (script / "checkout_identity.sh").write_text("exit 0\n", encoding="utf-8")
    init_dirs = script / "init_isaac_dirs.sh"
    init_dirs.write_text(
        '#!/usr/bin/env bash\ntouch "${FILE_PATH}/init-ran"\n', encoding="utf-8"
    )
    init_dirs.chmod(0o755)
    bridge = tmp_path / "toml-bridge"
    bridge.write_text(
        f'#!/usr/bin/env bash\nexec {shlex.join([sys.executable, str(REPO / ".base/dockerfile/toml_bridge.py")])} "$@"\n',
        encoding="utf-8",
    )
    bridge.chmod(0o755)

    def run(local):
        if local is not None:
            (tmp_path / "setup.local.toml").write_text(local, encoding="utf-8")
        result = subprocess.run(
            [REPO / "script/hooks/pre/run.sh", "-t", "headless", "-d"],
            env={
                **os.environ,
                "FILE_PATH": str(tmp_path),
                "ISAAC_IDENTITY_LIB": str(script / "checkout_identity.sh"),
                "PATH": f"{tmp_path}:{os.environ['PATH']}",
                "TOML_BRIDGE_FORCE_DOCKER": "0",
            },
            text=True,
            capture_output=True,
            check=True,
        )
        assert (tmp_path / "init-ran").is_file()
        assert result.stdout == ""
        return result.stderr

    return run


def test_lists_every_missing_mount_and_continues(run_hook):
    workspace_only = REPO_VOLUMES.split("\n\n", 1)[0] + "\n\n"
    warning = run_hook(workspace_only + MODEL_VOLUME)
    assert "setup.local.toml" in warning
    assert "${WS_PATH}/cache dir:/cache" in warning
    assert "${WS_PATH}/logs:/logs" in warning
    assert "${WS_PATH}:/work" not in warning
    assert "./models:/models" not in warning


def test_changed_source_at_same_target_does_not_cover_repo_mount(run_hook):
    warning = run_hook(REPO_VOLUMES.replace("${WS_PATH}/logs", "./other-logs"))
    assert "${WS_PATH}/logs:/logs" in warning


def test_complete_list_with_extra_mount_and_custom_mode_is_silent(run_hook):
    workspace, cache, logs = REPO_VOLUMES.strip().split("\n\n")
    local = "\n\n".join([workspace, logs, cache + '\nmode = "ro"', MODEL_VOLUME])
    assert run_hook(local) == ""


@pytest.mark.parametrize("local", [None, '[project]\nname = "isolated"\n'])
def test_inherited_volumes_are_silent(run_hook, local):
    assert run_hook(local) == ""


def test_explicit_empty_list_warns_for_every_repo_mount(run_hook):
    warning = run_hook("volumes = [\n]\n")
    assert "${WS_PATH}:/work" in warning
    assert "${WS_PATH}/cache dir:/cache" in warning
    assert "${WS_PATH}/logs:/logs" in warning


def test_advisory_parse_failure_warns_without_listing_unverified_mounts(run_hook):
    warning = run_hook("[[volumes]")
    assert "could not check setup.local.toml volume coverage" in warning
    assert "${WS_PATH}:/work" not in warning
