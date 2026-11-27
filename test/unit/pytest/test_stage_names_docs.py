"""Check Docker stage names in the driver and workflow guides (isaac#86)."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.docs

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_driver_has_no_retired_stream_stage():
    driver = _REPO_ROOT / "framework/isaac_devkit/driver.py"
    assert "headless-stream" not in driver.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "guide_path",
    (
        "src/doc/standalone_livestream_workflow.md",
        "src/doc/action_graph_setup.md",
        "src/doc/zed_install.md",
    ),
)
def test_docs_use_current_stage_names(guide_path):
    guide = _REPO_ROOT / guide_path
    forbidden_phrases = (
        "-t standalone",
        "headless-stream",
        "isaac-headless",
        "headless stage",
        "headless container",
        "for the headless",
        "啟 headless kit",
        "把 `headless` container",
        "舊 SOP 寫 headless",
    )
    for number, line in enumerate(guide.read_text(encoding="utf-8").splitlines(), 1):
        location = f"{guide.name}:{number}: {line}"
        for phrase in forbidden_phrases:
            assert phrase not in line, location
        if "runheadless" in line:
            assert "-t headless" not in line, location
            assert "run -t stream" not in line, location
