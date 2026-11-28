"""Documentation contract for the isaac architecture overview."""

import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree.ElementTree import TreeBuilder

import pytest

pytestmark = pytest.mark.docs

_ROOT = Path(__file__).resolve().parents[3]
_OVERVIEW = _ROOT / "doc" / "arch" / "overview.html"
_ADR_DIR = _ROOT / "src" / "doc" / "adr"


class _PageParser(HTMLParser):
    """Expose HTML elements to the tests using only the standard library."""

    _void = set("area base br col embed hr img input link meta param source track wbr".split())

    def __init__(self):
        super().__init__()
        self.tree = TreeBuilder()
        self.root = self.tree.start("document", {})

    def handle_starttag(self, tag, attrs):
        self.tree.start(tag, dict(attrs))
        if tag in self._void:
            self.tree.end(tag)

    def handle_endtag(self, tag):
        if tag not in self._void:
            self.tree.end(tag)

    def handle_data(self, data):
        self.tree.data(data)


def _read_page():
    assert _OVERVIEW.is_file(), f"Missing architecture overview: {_OVERVIEW}"
    parser = _PageParser()
    parser.feed(_OVERVIEW.read_text(encoding="utf-8"))
    parser.close()
    parser.tree.end("document")
    return parser.root


def _text(element):
    return "".join(element.itertext()).strip()


def test_overview_exists():
    assert _OVERVIEW.is_file(), f"Missing architecture overview: {_OVERVIEW}"


def test_final_section_has_one_row_per_adr():
    page = _read_page()
    elements = list(page.iter())
    headings = list(page.iter("h2"))
    assert headings, "Expected a final ADR cross-reference section"
    tables = [el for el in elements[elements.index(headings[-1]) + 1:] if el.tag == "table"]
    assert tables, "Missing ADR table after the final heading"
    rows = list(tables[-1].iter("tr"))
    assert rows, "Empty ADR table"
    headers = [_text(cell).casefold() for cell in rows[0].findall("th")]
    assert len(headers) == 3 and headers[0] == "adr", headers
    assert headers[1] in {"relation", "關係", "關聯"} and headers[2] in {"impact", "影響"}, headers

    files = {path.name[:4]: path.name for path in _ADR_DIR.glob("[0-9][0-9][0-9][0-9]-*.md")}
    numbers = []
    for row in rows[1:]:
        cells = [cell for cell in row if cell.tag in {"td", "th"}]
        assert len(cells) == 3 and all(_text(cell) for cell in cells[1:]), _text(row)
        label = _text(cells[0])
        links = [Path(unquote(urlsplit(a.get("href", "")).path)).name for a in cells[0].iter("a")]
        references = [name for name in files.values() if name in label or name in links]
        assert len(references) == 1, f"Expected one ADR file in first cell: {label!r}, {links}"
        number = references[0][:4]
        for cited in re.findall(r"\bADR-(\d+)\b", label, re.IGNORECASE):
            assert int(cited) == int(number), f"{label!r} references {references[0]}"
        numbers.append(number)

    assert Counter(numbers) == Counter(files.keys())


def test_adr_link_targets_exist():
    for anchor in _read_page().iter("a"):
        href = anchor.get("href", "")
        url = urlsplit(href)
        path = unquote(url.path)
        if "src/doc/adr/" not in path and not re.fullmatch(r"\d{4}-.+\.md", Path(path).name):
            continue
        if url.netloc:
            _, directory, filename = path.rpartition("/src/doc/adr/")
            assert directory, f"ADR link lacks repository path: {href}"
            target = _ADR_DIR / filename
        elif path.startswith("/"):
            target = _ROOT / path.lstrip("/")
        else:
            target = _OVERVIEW.parent / path
        assert target.is_file(), f"Broken ADR link {href!r} in {_OVERVIEW}"


def test_no_scripts_or_disclosures():
    assert not any(el.tag in {"script", "details", "summary"} for el in _read_page().iter())


def test_svg_figures_have_accessible_labels_and_captions():
    page = _read_page()
    svgs = list(page.iter("svg"))
    assert svgs, "Expected an inline architecture diagram"
    assert len(svgs) == len(list(page.iter("figcaption")))
    for svg in svgs:
        # HTMLParser normalizes attribute names to lowercase.
        assert svg.get("viewbox", "").strip(), "SVG needs a viewBox"
        assert svg.get("role") == "img"
        assert svg.get("aria-label", "").strip(), "SVG needs an accessible label"
    figures = [figure for figure in page.iter("figure") if figure.find(".//svg") is not None]
    assert len(figures) == len(svgs), "Each SVG needs its own figure"
    for figure in figures:
        captions = figure.findall("figcaption")
        assert len(captions) == 1 and _text(captions[0]), "Expected one caption per SVG figure"


def test_dark_mode_supports_system_and_explicit_theme():
    css = "\n".join(_text(style) for style in _read_page().iter("style"))
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    assert re.search(r"@media\b[^{]*\(\s*prefers-color-scheme\s*:\s*dark\s*\)", css, re.I)
    assert re.search(r"""\[\s*data-theme\s*=\s*(["']?)dark\1\s*\]""", css, re.I)


def test_h2_sections_are_numbered():
    headings = list(_read_page().iter("h2"))
    assert headings
    for index, heading in enumerate(headings, 1):
        numbers = [span for span in heading.iter("span") if "num" in span.get("class", "").split()]
        assert len(numbers) == 1, _text(heading)
        assert re.fullmatch(rf"0*{index}\b[.、]?", _text(numbers[0])), _text(heading)


def test_no_external_images():
    for img in _read_page().iter("img"):
        src = img.get("src", "").strip()
        assert not src or src.startswith(("data:", "#")), f"External image: {src}"
        candidates = img.get("srcset", "").strip()
        while candidates:
            url, *rest = candidates.split(maxsplit=1)
            assert url.startswith(("data:", "#")), f"External image candidate: {url}"
            candidates = rest[0] if rest else ""
            if not url.endswith(","):
                candidates = candidates.partition(",")[2].lstrip()
