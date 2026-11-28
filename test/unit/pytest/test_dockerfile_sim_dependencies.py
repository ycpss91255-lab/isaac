"""Keep NVIDIA's bundled simulation dependencies intact."""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

_DOCKERFILE = Path(__file__).resolve().parents[3] / "Dockerfile"


def test_dockerfile_does_not_add_optional_simulation_packages():
    assert not re.search(r"isaaclab|torch|xa" r"cro", _DOCKERFILE.read_text(), re.I)


def test_dockerfile_does_not_replace_bundled_numpy():
    dockerfile = _DOCKERFILE.read_text().replace("\\\n", " ")
    assert not re.search(r"pip install[^\n]*numpy", dockerfile)
