"""Regression tests for the tracked-file naming scan and its hosted CI step."""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.core

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = "script/ci/check_stale_naming.py"
TEST = "test/unit/pytest/test_check_stale_naming.py"
BATS_SPEC = "test/bats/smoke/stale_naming_spec.bats"


@pytest.fixture(scope="module")
def scanner():
    spec = importlib.util.spec_from_file_location("check_stale_naming", ROOT / SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reports_original_lines_and_respects_name_boundaries(scanner):
    clean = [
        "Use setup.toml with script/run.sh or ./script/run.sh",
        "A .setup.conf-free example with make builder",
        "Keep my_setup.conf, make build-all and ./run.sh.old",
    ]
    stale = [
        "Read setup.conf first",
        "make build",
        "Try ./run.sh.",
        "Then ./build.sh",
        "make\trun",
        "make exec",
        "make stop",
        "make test",
        "./exec.sh",
        "./stop.sh",
    ]
    assert scanner.find_stale({"guide.md": "\n".join(clean + stale)}) == [
        f"guide.md:{n}:{line}" for n, line in enumerate(stale, start=len(clean) + 1)
    ]


NEGATIVE_ASSERTIONS = (
    'refute_output --partial "./build.sh"',
    'refute_output --partial "./run.sh"',
    "no removed ./build.sh hint",
    "not the removed ./build.sh / ./run.sh",
    "not the removed `./build.sh`",
    "and no `.setup.conf.local`",
)


@pytest.mark.parametrize(("path", "phrases"), [
    ("script/checkout_identity.sh", ("base rc6 moved it from `.setup.conf.local`",)),
    ("test/bats/smoke/checkout_identity_spec.bats", ('[ ! -e "${REPO}/.setup.conf.local" ]',)),
    ("test/bats/smoke/init_isaac_dirs_spec.bats", NEGATIVE_ASSERTIONS),
    ("doc/test/TEST.md", NEGATIVE_ASSERTIONS),
    ("src/doc/adr/0011-ci-architecture-with-self-hosted-gpu-runner.md",
     ("compose, `.setup.conf`, config, the base subtree",)),
    ("src/doc/adr/0022-conform-bats-smoke-to-base-canonical-layout.md",
     ("+ `.setup.conf` relocation",)),
    ("src/doc/adr/0025-output-mode-ros-or-python.md", (
        "key in `.setup.conf` `[environment]` (section-replaced by",
        "`.setup.conf.local`).",
        "UNVERIFIED; avoided by not defining the key in `.setup.conf`",
    )),
])
def test_removes_only_one_copy_of_each_allowed_phrase_in_its_own_file(scanner, path, phrases):
    text = "\n".join(phrases)
    assert scanner.find_stale({path: text}) == []
    assert scanner.find_stale({"other.md": text}) == [
        f"other.md:{i}:{phrase}" for i, phrase in enumerate(phrases, 1)
    ]
    for line in (f"{phrases[0]} and make build", f"{phrases[0]} {phrases[0]}"):
        assert scanner.find_stale({path: line}) == [f"{path}:1:{line}"]


def test_excluded_paths(scanner):
    # The scanner and its regression tests contain retired names as pattern data.
    excluded = (
        ".base/nested/run.sh", "CHANGELOG", "doc/CHANGELOG.md",
        ".gitignore", "nested/.gitignore", ".dockerignore", "nested/.dockerignore",
        "src/doc/adr/0005-standalone-with-livestream-as-default-dev-entrypoint.md",
        "src/doc/adr/0007-custom-streaming-experience-for-simulationapp.md",
        "src/doc/adr/0014-sim-runtime-stage-taxonomy-stream-vs-headless.md",
        SCRIPT, TEST,
    )
    for path in excluded:
        assert scanner.is_excluded(path), path
    for path in (".base-copy/run.sh", "src/doc/adr/0005-other.md", BATS_SPEC):
        assert not scanner.is_excluded(path), path


@pytest.mark.parametrize("hide_git", [False, True], ids=["no-checkout", "no-git"])
def test_main_reports_unavailable_checkout(scanner, tmp_path, monkeypatch, capsys, hide_git):
    if hide_git:
        monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    assert scanner.main([str(tmp_path)]) == 2
    assert "git" in capsys.readouterr().err.lower()
    with pytest.raises(scanner.NotAGitCheckout):
        scanner.tracked_files(tmp_path)


@pytest.mark.skipif(shutil.which("git") is None, reason="requires git to create a checkout")
def test_main_scans_tracked_working_tree_text(scanner, tmp_path, capsys):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    guide = tmp_path / "quick start.md"
    guide.write_text("Build with\nmake build\n")
    (tmp_path / "untracked.md").write_text("make build\n")
    (tmp_path / "link").symlink_to("untracked.md")
    (tmp_path / "binary").write_bytes(b"make build\n\x00")
    (tmp_path / "CHANGELOG").write_text("make build\n")
    subprocess.run(["git", "add", "--", guide.name, "link", "binary", "CHANGELOG"],
                   cwd=tmp_path, check=True)

    assert scanner.main([str(tmp_path)]) == 1
    assert capsys.readouterr().out.splitlines() == ["quick start.md:2:make build"]
    guide.write_text("Use setup.toml\n")
    assert scanner.main([str(tmp_path)]) == 0


def test_core_unit_runs_stale_naming_scan_after_checkout():
    workflow = yaml.safe_load((ROOT / ".github/workflows/main.yaml").read_text())
    steps = workflow["jobs"]["core-unit"]["steps"]
    checkout = next(i for i, step in enumerate(steps)
                    if step.get("uses", "").startswith("actions/checkout@"))
    assert any(step.get("name") == "Stale naming scan"
               and step.get("run", "").strip() == f"python3 {SCRIPT}"
               for step in steps[checkout + 1:])


def test_old_bats_scan_is_removed():
    assert not (ROOT / BATS_SPEC).exists()
