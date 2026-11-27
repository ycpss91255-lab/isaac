"""Hosted checks for the standalone smoke script's case matrix."""

import re
import shlex
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.core

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "src/script/test/standalone_smoke.sh"


@pytest.mark.parametrize("token", ["needs-usd", "needs_usd", "USD_HOST"])
def test_script_has_no_usd_gate(token):
    assert token not in _SCRIPT.read_text(encoding="utf-8")


def test_each_case_has_three_fields():
    source = _SCRIPT.read_text(encoding="utf-8")
    matrix = re.search(r"^CASES=\((.*?)^\s*\)", source, re.MULTILINE | re.DOTALL)
    assert matrix is not None, "Missing CASES array"
    entries = shlex.split(matrix.group(1), comments=True)
    assert entries, "Empty CASES array"
    for entry in entries:
        assert len(entry.split("|")) == 3, f"Expected basename|marker|timeout in {entry!r}"


def test_script_has_valid_bash_syntax():
    subprocess.run(["bash", "-n", _SCRIPT], check=True)
