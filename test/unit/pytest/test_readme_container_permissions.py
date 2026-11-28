"""Check local privilege override instructions in each README (isaac#549)."""

import re
from pathlib import Path

import pytest

from test_readme_multi_instance import _headings

pytestmark = pytest.mark.docs

_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("readme", "permission_terms"),
    [
        pytest.param("README.md", r"permission|privilege|security|capabilit", id="en"),
        pytest.param("doc/README.zh-TW.md", r"權限|特權|安全", id="zh-TW"),
        pytest.param("doc/README.zh-CN.md", r"权限|特权|安全", id="zh-CN"),
        pytest.param("doc/README.ja.md", r"権限|特権|セキュリティ", id="ja"),
    ],
)
def test_container_permissions_document_local_override(readme, permission_terms):
    lines = (_ROOT / readme).read_text(encoding="utf-8").splitlines()
    headings = list(_headings(lines))
    for index, (start, level, title) in enumerate(headings):
        if re.search(permission_terms, title, re.IGNORECASE):
            end = next(
                (i for i, depth, _ in headings[index + 1:] if depth <= level),
                len(lines),
            )
            section = "\n".join(lines[start:end])
            if "setup.local.toml" in section and re.search(r"\bprivileged\b", section, re.ASCII):
                return
    pytest.fail(
        f"{readme} needs a container permissions section covering setup.local.toml and privileged"
    )
