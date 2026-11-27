"""Check the sim_asset paths documented for moved models."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.docs

_REPO_ROOT = Path(__file__).resolve().parents[3]
_README = _REPO_ROOT / "src" / "model" / "README.md"


@pytest.mark.parametrize("path", [
    "urdf/omwr/",
    "usd/omwr/",
    "urdf/openbase/",
    "usd/openbase/",
    "usd/forklift_blocky/",
])
def test_model_readme_omits_stale_path(path):
    assert path not in _README.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", [
    "model/robot/guiritter/openbase/",
    "usd/robot/guiritter/openbase/",
    "model/robot/custom/omwr/",
    "usd/robot/custom/omwr/",
    "usd/temp/forklift_blocky/",
])
def test_model_readme_lists_sim_asset_path(path):
    assert path in _README.read_text(encoding="utf-8")


def test_model_readme_cites_sim_asset_readme():
    source = "https://github.com/ycpss91255-lab/sim_asset/blob/main/README.md"
    assert source in _README.read_text(encoding="utf-8")

