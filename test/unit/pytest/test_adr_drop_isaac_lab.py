"""Documentation contract for the decision to drop Isaac Lab from isaac."""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.docs

_ADR_DIR = Path(__file__).resolve().parents[3] / "src" / "doc" / "adr"


def _read_adr(number):
    matches = list(_ADR_DIR.glob(f"{number}-*.md"))
    assert len(matches) == 1, f"Expected one {number}-*.md in {_ADR_DIR}, found {matches}"
    return matches[0].read_text(encoding="utf-8")


def test_0026_names_the_replaced_adr_and_repositories():
    decision = _read_adr("0026")
    for reference in ("0018", "asset_converter", "isaac_lab"):
        assert reference in decision, f"ADR-0026 must mention {reference}"


def test_0018_status_names_the_superseding_adr_near_the_top():
    for line in _read_adr("0018").splitlines()[:15]:
        if re.match(r"status\b", line.lstrip(" \t>#*-_"), re.IGNORECASE):
            assert re.search(r"\bsuperseded\b", line, re.IGNORECASE), line
            assert re.search(r"\b0026\b", line), line
            return
    pytest.fail("ADR-0018 needs a Status line in its first 15 lines")


def test_0020_names_the_urdf_import_repository():
    assert "asset_converter" in _read_adr("0020")


def test_0017_isaac_lab_amendment_points_to_0026():
    sections = re.split(r"^## ", _read_adr("0017"), flags=re.MULTILINE)
    assert any(
        "ADR-0026" in section
        for section in sections
        if section.startswith("Amendment: Isaac Lab")
    ), "The Isaac Lab amendment in ADR-0017 must reference ADR-0026"
