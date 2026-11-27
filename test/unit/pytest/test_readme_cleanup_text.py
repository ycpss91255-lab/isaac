"""Contract for the deleted-checkout cleanup instructions (isaac#381)."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.docs

_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("readme", "warning", "size_terms", "label_output", "layer_caveat"),
    [
        pytest.param(
            "README.md",
            ("kills running containers", "only", "checkout", "no longer exists"),
            ("nominal", "shared layers", "less"),
            "label output",
            ("shared layers", "frees nothing", "last tag"),
            id="en",
        ),
        pytest.param(
            "doc/README.zh-TW.md",
            ("強制終止", "執行中的容器", "僅", "checkout", "已不存在"),
            ("名義上", "共用層", "較少"),
            "標籤輸出",
            ("共用層", "不會釋放", "最後一個 tag"),
            id="zh-TW",
        ),
        pytest.param(
            "doc/README.zh-CN.md",
            ("强制终止", "运行中的容器", "仅", "checkout", "已不存在"),
            ("名义上", "共享层", "较少"),
            "标签输出",
            ("共享层", "不会释放", "最后一个 tag"),
            id="zh-CN",
        ),
        pytest.param(
            "doc/README.ja.md",
            ("強制終了", "実行中のコンテナ", "のみ", "checkout", "存在しない"),
            ("名目上", "共有レイヤー", "少な"),
            "ラベルの出力",
            ("共有レイヤー", "解放されない", "最後の tag"),
            id="ja",
        ),
    ],
)
def test_deleted_checkout_cleanup(readme, warning, size_terms, label_output, layer_caveat):
    text = (_REPO_ROOT / readme).read_text(encoding="utf-8")
    sections = [section for section in text.split("\n## ") if "docker rm -f" in section]
    assert sections, "Missing deleted-checkout cleanup procedure"
    section = sections[0]

    # A reader grepping for the command must see the warning on a matching line.
    assert any(
        "docker rm -f" in line and all(word in line.lower() for word in warning)
        for line in section.splitlines()
    ), f"Expected docker rm -f warning with {warning}"

    paragraphs = [
        " ".join(block.split()) for item in section.split("\n- ") for block in item.split("\n\n")
    ]
    assert any(
        all(word in block.lower() for word in ("31 gb", "tag", "docker images", *size_terms))
        for block in paragraphs
    ), "Explain why shared layers reduce the space reclaimed versus the nominal per-tag size"

    assert label_output in section and "PROJECT_NAME" in section
    assert any(
        "docker ps" in line and '.Label "com.docker.compose.project"' in line
        for line in section.splitlines()
    ), "Show how to read the compose project from container labels"
    filters = [
        line for line in section.splitlines() if "label=com.docker.compose.project=" in line
    ]
    assert filters and all("${HUB}-${SLUG}" not in line for line in filters)

    assert "docker rmi" in section
    assert any(
        all(word in block.lower() for word in layer_caveat) for block in paragraphs
    ), f"Explain when untagging reclaims space with {layer_caveat}"
