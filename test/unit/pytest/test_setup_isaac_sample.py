"""Guard the copyable Isaac setup layer and its README references."""

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SETUP = _REPO_ROOT / "setup.toml"
_SAMPLE = _REPO_ROOT / "setup.isaac_sample.toml"
_MODEL_SOURCE = "${WS_PATH}/sim_asset"
_MODEL_TARGET = "/home/${USER_NAME}/models/sim_asset"


def _read_toml(path):
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _mount_pairs(config):
    return {(volume["source"], volume["target"]) for volume in config["volumes"]}


def test_sample_exists():
    assert _SAMPLE.is_file()


def test_sample_parses_as_toml():
    _read_toml(_SAMPLE)


def test_sample_repeats_every_repo_mount():
    assert _mount_pairs(_read_toml(_SETUP)) <= _mount_pairs(_read_toml(_SAMPLE))


def test_sample_mounts_sim_asset_read_only():
    volumes = _read_toml(_SAMPLE)["volumes"]
    assert (_MODEL_SOURCE, _MODEL_TARGET, "ro") in {
        (volume["source"], volume["target"], volume.get("mode")) for volume in volumes
    }


def test_sample_model_path_points_to_sim_asset():
    assert _read_toml(_SAMPLE)["environment"]["env_10"] == f"MODEL_PATH={_MODEL_TARGET}"


def test_merged_layer_preserves_repo_and_model_mounts():
    result = subprocess.run(
        [
            sys.executable,
            _REPO_ROOT / ".base/dockerfile/toml_bridge.py",
            "--merge",
            _SETUP,
            _SAMPLE,
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    expected = _mount_pairs(_read_toml(_SETUP)) | {(_MODEL_SOURCE, _MODEL_TARGET)}
    assert expected <= _mount_pairs(json.loads(result.stdout))


def test_sample_excludes_personal_paths_email_and_urdf_references():
    sample = _SAMPLE.read_text(encoding="utf-8")
    assert not re.search(r"/home/[a-z]|/Users/|@|urdf", sample, re.IGNORECASE)


def test_sample_documents_each_table_and_key():
    lines = _SAMPLE.read_text(encoding="utf-8").splitlines()
    block_has_comment = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            block_has_comment = bool(stripped)
            continue
        # Ignore hash signs and equals signs inside quoted TOML strings.
        unquoted = re.sub(r'"(?:\\.|[^"\\])*"' r"|'[^']*'", "", line)
        code, comment, _ = unquoted.partition("#")
        if code.lstrip().startswith("["):
            block_has_comment = index > 0 and lines[index - 1].lstrip().startswith("#")
        if code.lstrip().startswith("[") or "=" in code:
            assert comment or block_has_comment, (
                f"Missing comment on line {index + 1}: {line}"
            )


@pytest.mark.parametrize(
    "readme",
    ["README.md", "doc/README.zh-TW.md", "doc/README.zh-CN.md", "doc/README.ja.md"],
)
def test_readme_mentions_sample(readme):
    assert _SAMPLE.name in (_REPO_ROOT / readme).read_text(encoding="utf-8")
