"""Check the published stream viewer image and its documentation (isaac#284)."""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.docs

ROOT = Path(__file__).resolve().parents[3]
IMAGE = "ghcr.io/ycpss91255-lab/omniverse_web_viewer"
READMES = ("README.md", "doc/README.zh-TW.md", "doc/README.zh-CN.md", "doc/README.ja.md")


def test_viewer_submodule_path_removed():
    assert not (ROOT / "web_viewer").exists()


def test_gitmodules_omits_viewer():
    gitmodules = ROOT / ".gitmodules"
    if gitmodules.exists():
        assert "web_viewer" not in gitmodules.read_text(encoding="utf-8")


def test_scripts_omit_legacy_viewer_image_tags():
    legacy_tag = re.compile(rb"omniverse_web_viewer:(latest|runtime)")
    for path in (ROOT / "script").rglob("*"):
        if path.is_file():
            for number, line in enumerate(path.read_bytes().splitlines(), 1):
                assert not legacy_tag.search(line), f"{path.relative_to(ROOT)}:{number}: {line!r}"


def test_post_run_hook_pins_published_viewer_image():
    hook = (ROOT / "script/hooks/post/run.sh").read_text(encoding="utf-8")
    assert re.search(re.escape(f"{IMAGE}:0.3.0") + r"(?![\w.-])", hook)


@pytest.mark.parametrize("readme", READMES)
def test_readme_documents_published_viewer_image(readme):
    text = (ROOT / readme).read_text(encoding="utf-8")
    assert "submodule update" not in text
    assert "owv:runtime" not in text
    assert not re.search(r"\bweb_viewer/", text, re.ASCII)
    assert IMAGE in text
    assert "OWV_IMAGE" in text
