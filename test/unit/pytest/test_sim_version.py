"""Hosted tests for ``isaac_devkit.sim_version`` (isaac#295).

Every experiment driver records which Isaac Sim produced its numbers in an
``isaac_variant`` field. Until the 6.2.0 upgrade that field was the string
literal ``"6.0.1"`` in every driver script, so re-running the physics re-validation on
a new base image would have written 6.2.0 results labelled 6.0.1 -- exactly
the comparison the re-validation exists to make. The version now comes from
the image itself (``/isaac-sim/VERSION``), and the last test stops a literal
from coming back.
"""

import ast
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "framework"))

from isaac_devkit import sim_version  # noqa: E402

pytestmark = pytest.mark.core


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        # What NGC's nvcr.io/nvidia/isaac-sim:6.2.0.1 ships.
        ("6.2.0-rc.15+release.53422.03030206.gl", "6.2.0"),
        # What nvcr.io/nvidia/isaac-sim:6.0.1 ships.
        ("6.0.1-rc.7+release.42383.32955d8d.gl\n", "6.0.1"),
        # A bare release number, as a source build may write it.
        ("5.1.0\n", "5.1.0"),
    ],
)
def test_release_is_read_from_the_version_file(tmp_path, content, expected):
    version_file = tmp_path / "VERSION"
    version_file.write_text(content, encoding="utf-8")
    assert sim_version.isaac_sim_version(version_file) == expected


def test_missing_version_file_reports_unknown(tmp_path):
    # A hosted box has no Isaac Sim. The driver must still write its JSON, and
    # "unknown" is honest where a guessed version would not be.
    assert sim_version.isaac_sim_version(tmp_path / "absent") == "unknown"


def test_empty_version_file_reports_unknown(tmp_path):
    version_file = tmp_path / "VERSION"
    version_file.write_text("\n", encoding="utf-8")
    assert sim_version.isaac_sim_version(version_file) == "unknown"


def test_default_reads_the_image_install():
    assert sim_version.DEFAULT_VERSION_FILE == Path("/isaac-sim/VERSION")


def _is_variant_key(node):
    return isinstance(node, ast.Constant) and node.value == "isaac_variant"


def _is_string_literal(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _hardcodes_variant(node):
    if isinstance(node, ast.Dict):
        return any(
            _is_variant_key(key) and _is_string_literal(value)
            for key, value in zip(node.keys, node.values)
        )
    if isinstance(node, ast.keyword):
        return node.arg == "isaac_variant" and _is_string_literal(node.value)
    if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        return _is_string_literal(node.value) and any(
            isinstance(target, ast.Subscript) and _is_variant_key(target.slice)
            for target in targets
        )
    return False


def _find_hardcoded_variants(root: Path) -> list[str]:
    """Return repo-relative paths of driver scripts with an isaac_variant literal."""
    scripts = []
    # isaac#360: an empty glob would make the scan pass checking nothing. The
    # test/verify_*.py family moved to isaac_physics_test, so only src/script
    # remains in scope.
    for base, pattern in (("src/script", "*.py"),):
        matched = sorted((root / base).glob(pattern))
        assert matched, f"scan glob matched nothing: {base}/{pattern}"
        scripts += matched
    offenders = []
    for path in scripts:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if any(_hardcodes_variant(node) for node in ast.walk(tree)):
            offenders.append(str(path.relative_to(root)))
    return offenders


def test_no_driver_hardcodes_the_isaac_variant():
    offenders = _find_hardcoded_variants(_REPO_ROOT)
    assert not offenders, (
        "isaac_variant must come from isaac_sim_version(), not a literal: "
        + ", ".join(offenders)
    )


def _plant(root: Path, rel: str, text: str = "x = 1\n") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    "present",
    [
        [],
        ["test/verify_a.py"],
    ],
    ids=["no-script", "only-moved-verify-family"],
)
def test_scan_fails_when_a_script_glob_matches_nothing(tmp_path, present):
    # isaac#360: a scan over an empty file set used to pass vacuously, so
    # moving a script family away would leave the guard green and checking
    # nothing. Each glob must be non-empty on its own, not just the union.
    for rel in present:
        _plant(tmp_path, rel)
    with pytest.raises(AssertionError):
        _find_hardcoded_variants(tmp_path)


def test_scan_reports_a_planted_variant_literal(tmp_path):
    # isaac#360: pin the detection itself, not only "passes on the real repo".
    _plant(tmp_path, "src/script/clean.py")
    _plant(tmp_path, "src/script/bad.py", '{"isaac_variant": "6.0.1"}\n')
    assert _find_hardcoded_variants(tmp_path) == ["src/script/bad.py"]


@pytest.mark.parametrize(
    ("source", "should_report"),
    [
        pytest.param('d = {"isaac_variant": ("x")}', True, id="dict-display"),
        pytest.param('d = dict(isaac_variant="x")', True, id="dict-keyword"),
        pytest.param('f(isaac_variant="x")', True, id="function-keyword"),
        pytest.param('d["isaac_variant"] = "x"', True, id="subscript-store"),
        pytest.param('d = {"isaac_variant": isaac_sim_version()}', False, id="call-value"),
        pytest.param('v = "x"\nd = {"isaac_variant": v}', False, id="variable-value"),
    ],
)
def test_scan_recognizes_direct_variant_literals(tmp_path, source, should_report):
    _plant(tmp_path, "src/script/clean.py")
    script = "src/script/driver.py"
    _plant(tmp_path, script, source + "\n")
    assert _find_hardcoded_variants(tmp_path) == ([script] if should_report else [])
