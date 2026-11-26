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


def _index_of(blocks, needle):
    for i, block in enumerate(blocks):
        if needle in block:
            return i
    raise AssertionError(f"no RUN contains {needle!r}")


def _restore_block():
    blocks = _run_blocks()
    lab = _index_of(blocks, "isaaclab.sh --install")
    after = [b for b in blocks[lab:] if "numpy==" in b]
    assert after, (
        "no RUN at or after the Isaac Lab install pins numpy; Isaac Lab's "
        "numpy 2.5.5 stays shadowing Isaac Sim's prebundled numpy"
    )
    return after[0], blocks.index(after[0]), lab


def test_numpy_is_pinned_at_or_after_isaaclab_install():
    _, restore_idx, lab_idx = _restore_block()
    assert restore_idx >= lab_idx


def test_pin_reads_version_from_isaac_sim_prebundle():
    block, _, _ = _restore_block()
    assert "pip_prebundle" in block and "numpy-" in block, (
        "the pinned version must come from Isaac Sim's own pip_prebundle "
        "numpy dist-info, not a hard-coded number"
    )
    assert not re.search(r"numpy==\d", block), "numpy version is hard-coded"


def test_pin_asserts_the_result_at_build_time():
    block, _, _ = _restore_block()
    assert "numpy.__version__" in block, (
        "the restore step must assert the numpy that Python imports equals "
        "the pinned version, so a silent no-op fails the build"
    )
