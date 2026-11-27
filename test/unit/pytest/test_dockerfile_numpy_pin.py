"""Hosted guard: numpy is restored to Isaac Sim's prebundled version (isaac#446).

``isaaclab.sh --install none`` pulls numpy 2.5.5 into Kit's site-packages,
which shadows the numpy 2.3.1 that Isaac Sim ships in ``pip_prebundle``.
Four official ``isaacsim.sensors.experimental.rtx`` cases then fail with
NumPy TypeErrors on our image only (isaac#435 comment 7056607290). The
Dockerfile must put numpy back to the version Isaac Sim itself ships, read
from the image instead of a hard-coded number, so a Sim bump keeps working.

No docker, no GPU: the guard reads the Dockerfile text.
"""

import pathlib
import re

import pytest

pytestmark = pytest.mark.core

_DOCKERFILE = pathlib.Path(__file__).resolve().parents[3] / "Dockerfile"


def _run_blocks():
    """Return each RUN instruction (backslash continuations joined)."""
    text = _DOCKERFILE.read_text(encoding="utf-8")
    text = re.sub(r"\\\n", " ", text)
    blocks = []
    for line in text.splitlines():
        if line.startswith("RUN "):
            blocks.append(line)
    return blocks


def _index_of(blocks, *needles):
    for i, block in enumerate(blocks):
        if all(needle in block for needle in needles):
            return i
    raise AssertionError(f"no RUN contains all of {needles!r}")


def _restore_block(blocks):
    lab_idx = _index_of(blocks, "isaaclab.sh --install")
    restore_idx = _index_of(blocks, "numpy==")
    return blocks[restore_idx], restore_idx, lab_idx


def test_numpy_restore_runs_after_isaaclab_install_and_before_prebundle_check():
    blocks = _run_blocks()
    _, restore_idx, lab_idx = _restore_block(blocks)
    check_idx = _index_of(blocks, "pip_prebundle", "-xtype l")
    assert lab_idx < restore_idx < check_idx, (
        f"numpy restore (RUN {restore_idx}) must run after the Isaac Lab install "
        f"(RUN {lab_idx}) and before the pip_prebundle integrity check (RUN {check_idx})"
    )


def test_pin_reads_version_from_isaac_sim_prebundle():
    block, _, _ = _restore_block(_run_blocks())
    assert "pip_prebundle" in block and "numpy-" in block, (
        "the pinned version must come from Isaac Sim's own pip_prebundle "
        "numpy dist-info, not a hard-coded number"
    )
    assert not re.search(r"numpy==\d", block), "numpy version is hard-coded"


def test_pin_asserts_the_result_at_build_time():
    block, _, _ = _restore_block(_run_blocks())
    assert "numpy.__version__" in block, (
        "the restore step must assert the numpy that Python imports equals "
        "the pinned version, so a silent no-op fails the build"
    )


def test_restore_has_no_shell_pipe():
    block, _, _ = _restore_block(_run_blocks())
    assert "|" not in block.replace("||", ""), (
        "a shell pipe in the numpy restore RUN triggers hadolint DL4006"
    )
