"""Check the multi-instance instructions in each localized README (isaac#289)."""

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.docs

_ROOT = Path(__file__).resolve().parents[3]
_ADR = Path("src/doc/adr/0019-remove-same-repo-multi-instance.md")
_ISSUE = "https://github.com/ycpss91255-lab/multi_run/issues/15"
_READMES = (
    (
        "README.md",
        "One image and one compose project per checkout",
        "multiple instances",
    ),
    (
        "doc/README.zh-TW.md",
        "每個 checkout 一個 image 與一個 compose project",
        "多個 instance",
    ),
    (
        "doc/README.zh-CN.md",
        "每个 checkout 一个 image 与一个 compose project",
        "多个 instance",
    ),
    (
        "doc/README.ja.md",
        "checkout ごとに 1 つの image と 1 つの compose project",
        "複数 instance",
    ),
)


def _headings(lines):
    """Yield line number, level and title for ATX headings outside code fences."""
    fence = ""
    for index, line in enumerate(lines):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1].startswith(fence) and not marker[2].strip():
                fence = ""
        elif marker:
            fence = marker[1]
        else:
            heading = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+)$", line)
            if heading:
                yield index, len(heading[1]), heading[2]


def _section_bounds(lines, phrase):
    """Find the matching heading and the first line outside its section."""
    headings = _headings(lines)
    for start, level, title in headings:
        if phrase.casefold() in title.casefold():
            end = next((i for i, depth, _ in headings if depth <= level), len(lines))
            return start, end
    pytest.fail(f"Missing README heading containing {phrase!r}")


@pytest.fixture(params=_READMES, ids=[row[0] for row in _READMES])
def readme(request):
    filename, checkout_title, multi_title = request.param
    path = _ROOT / filename
    lines = path.read_text(encoding="utf-8").splitlines()
    return path, lines, checkout_title, multi_title


def _section(readme):
    _, lines, _, title = readme
    start, end = _section_bounds(lines, title)
    return "\n".join(lines[start:end])


def test_heading_follows_checkout_section(readme):
    _, lines, checkout_title, multi_title = readme
    _, checkout_end = _section_bounds(lines, checkout_title)
    multi_start, _ = _section_bounds(lines, multi_title)
    assert multi_start >= checkout_end


def test_links_to_existing_adr(readme):
    path = readme[0]
    section = _section(readme)
    target = _ADR if path.parent == _ROOT else Path("..") / _ADR
    assert "ADR-0019" in section
    assert re.search(r"\[[^\]]+\]\(" + re.escape(target.as_posix()) + r"\)", section)
    assert (path.parent / target).resolve().is_file()


def test_mentions_multi_run_and_links_to_issue_15(readme):
    section = _section(readme)
    assert "multi_run#15" in section
    assert re.search(r"\[[^\]]+\]\(" + re.escape(_ISSUE) + r"\)", section)


def test_documents_per_instance_cache_cost_and_project(readme):
    section = _section(readme)
    per_instance = (
        r"\b(each|every|per|own|separate|distinct|unique|dedicated|isolated)\b"
        r"|每|各|獨立|独立|個別|个别|不同|分離|分离|ごと|別々|専用|異なる"
    )
    assert "isaac-sim/" in section
    assert "3.9 GiB" in section
    assert re.search(per_instance, section, re.IGNORECASE)
    assert "compose" in section.casefold()
    assert re.search(r"(?<![\w-])-p(?![\w-])", section, re.ASCII)


def test_headless_runs_need_no_port_overrides(readme):
    section = _section(readme)
    sentences = re.split(r"(?<=[.!?])\s+|[。！？]|\n\s*\n", section)
    port = r"ports?|埠|端口|ポート"
    unnecessary = (
        r"\b(no|without|unnecessary|unchanged|skip)\b|n[o’']t\b"
        r"|不必|不用|不需|無需|无需|不須|不须|無須|无须|毋須|免|不要"
        r"|必要.{0,4}(ない|ありません)"
    )
    assert any(
        re.search(r"\bheadless\b", sentence, re.ASCII)
        and re.search(port, sentence, re.IGNORECASE)
        and re.search(unnecessary, sentence, re.IGNORECASE)
        for sentence in sentences
    ), "Explain that headless runs need no port overrides"


def test_section_omits_personal_identifiers(readme):
    section = _section(readme)
    patterns = (
        r"/(?:home|Users)/\w+",
        r"[\w.+-]+@[\w-]+\.[\w.-]+",
        r"\b\w+@[\w.-]+\b",
    )
    for pattern in patterns:
        assert not re.search(pattern, section)
