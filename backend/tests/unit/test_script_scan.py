"""The shop script may bind only to stable hooks (task 9.4, design Decision 4).

``app.js`` is the one place a drift-proof locator could sneak back in: a
stage-1 id or class in a selector, a behaviour marker, a ``data-test`` lookup,
a runtime-written marker, or markup assembled from a string. The bans live
here, in a permanent test, instead of in one-off greps.

What the scan reports in ``backend/app/static/app.js``:

* a stage-1 name of a covered id or class, including the ``block__element``
  and ``block--modifier`` names derived from a covered block (the derivation
  rule of :func:`~backend.app.core.workshop.is_covered_class`, the same one
  the template scan of task 5.10 uses) - matched as a whole token and only
  inside string literals, so the stable state class ``"site-nav-open"`` is
  fine although the covered block ``site-nav`` is a prefix of it, and a local
  variable named ``badge`` or ``flash`` is not mistaken for a covered class;
* ``data-test``;
* a removed behaviour marker, in its attribute form and in its ``dataset``
  camelCase form;
* a ``dataset.<name>`` property or a ``data-<name>`` string literal outside
  the four content data attributes;
* a runtime write of a data attribute or an id;
* any ``className`` assignment;
* any use of ``innerHTML``.

Comments are not scanned: they are prose, and the file explains its own rules.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.app.core.workshop import COVERED_IDS, is_covered_class
from backend.tests.unit.test_template_scan import REMOVED_MARKERS

#: The script the scan protects.
SCRIPT = Path(__file__).resolve().parents[3] / "backend" / "app" / "static" / "app.js"

#: The content data attributes (design Decision 3). They are part of the
#: stable contract, so the script may read them.
CONTENT_DATA_ATTRIBUTES = ("product", "product-name", "category", "chat-prompt")

#: The behaviour markers of task 8.5 are shared with the template scan, so a
#: marker cannot be banned in one place and forgotten in the other.

#: The same four content attributes as ``dataset`` properties.
CONTENT_DATASET_PROPERTIES = ("product", "productName", "category", "chatPrompt")

#: A class or id name as it appears inside a string literal.
_NAME_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")

#: A ``data-*`` attribute name inside a string literal.
_DATA_ATTRIBUTE = re.compile(r"data-[a-z0-9-]*[a-z0-9]")

#: The runtime writes that would put a locator back into the DOM.
_RUNTIME_WRITES = (
    (re.compile(r"\.dataset\.[A-Za-z_$][\w$]*\s*=(?!=)"), "writes a data attribute (dataset.x = ...)"),
    (re.compile(r"\.dataset\[[^\]]*\]\s*=(?!=)"), "writes a data attribute (dataset[...] = ...)"),
    (re.compile(r"Object\.assign\(\s*[\w.$\[\]\"']+\.dataset"), "writes data attributes through Object.assign"),
    (re.compile(r"""(?:set|toggle|remove)Attribute\(\s*[\"'`]data-"""), "writes a data attribute by name"),
    (re.compile(r"""setAttribute\(\s*[\"'`]id[\"'`]"""), "writes an id"),
    (re.compile(r"\.id\s*=(?!=)"), "writes an id (.id = ...)"),
    (re.compile(r"\.className\s*=(?!=)"), "assigns className; use classList"),
    (re.compile(r"\binnerHTML\b"), "uses innerHTML"),
    (re.compile(r"data-test"), "looks an element up by data-test"),
)

#: A ``dataset`` property read or write.
_DATASET_PROPERTY = re.compile(r"\.dataset\.([A-Za-z_$][\w$]*)")


def _marker_of_property(prop: str) -> str | None:
    """The removed marker ``dataset.<prop>`` would read, if it is one."""
    for entry in REMOVED_MARKERS:
        prefix = _camel(entry.rstrip("-"))
        if prop == prefix or (entry.endswith("-") and prop.startswith(prefix)):
            return entry
    return None


def _camel(marker: str) -> str:
    """The ``dataset`` property name of a ``data-*`` attribute."""
    head, *rest = marker.removeprefix("data-").split("-")
    return head + "".join(part.title() for part in rest)


def strip_comments_and_collect_strings(source: str) -> tuple[str, list[tuple[int, str]]]:
    """``source`` without comments, plus every string literal with its offset.

    Template literals are taken as a whole, and regular expression literals
    are skipped, so a slash inside a character class cannot open a comment.
    """
    code: list[str] = []
    strings: list[tuple[int, str]] = []
    index = 0
    previous = ""
    length = len(source)
    while index < length:
        char = source[index]
        pair = source[index : index + 2]
        if pair == "//":
            end = source.find("\n", index)
            end = length if end == -1 else end
            code.append(" " * (end - index))
            index = end
            continue
        if pair == "/*":
            end = source.find("*/", index + 2)
            end = length if end == -1 else end + 2
            code.append("".join(" " if c != "\n" else "\n" for c in source[index:end]))
            index = end
            continue
        if char in "\"'`":
            quote = char
            cursor = index + 1
            while cursor < length:
                if source[cursor] == "\\":
                    cursor += 2
                    continue
                if source[cursor] == quote:
                    break
                cursor += 1
            end = min(cursor + 1, length)
            strings.append((index + 1, source[index + 1 : end - 1]))
            code.append(source[index:end])
            previous = quote
            index = end
            continue
        if char == "/" and previous in "(,=:[!&|?{};+*%~^" :
            cursor = index + 1
            in_class = False
            while cursor < length:
                current = source[cursor]
                if current == "\\":
                    cursor += 2
                    continue
                if current == "[":
                    in_class = True
                elif current == "]":
                    in_class = False
                elif current == "/" and not in_class:
                    break
                elif current == "\n":
                    break
                cursor += 1
            end = min(cursor + 1, length)
            code.append(source[index:end])
            index = end
            continue
        code.append(char)
        if not char.isspace():
            previous = char
        index += 1
    return "".join(code), strings


def _line_of(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def scan_script(source: str, *, name: str = "app.js") -> list[str]:
    """Every rule this script breaks, as readable findings."""
    findings: list[str] = []
    code, strings = strip_comments_and_collect_strings(source)

    def report(position: int, message: str) -> None:
        findings.append(f"{name}:{_line_of(source, position)}: {message}")

    for offset, literal in strings:
        for match in _NAME_TOKEN.finditer(literal):
            token = match.group(0)
            if token in COVERED_IDS:
                report(offset + match.start(), f"names the covered id {token!r}")
            elif is_covered_class(token):
                report(offset + match.start(), f"names the covered class {token!r}")
        for match in _DATA_ATTRIBUTE.finditer(literal):
            attribute = match.group(0)
            marker = next(
                (
                    entry
                    for entry in REMOVED_MARKERS
                    if attribute == entry or (entry.endswith("-") and attribute.startswith(entry))
                ),
                None,
            )
            if marker is not None:
                report(offset + match.start(), f"uses the removed marker {attribute!r}")
            elif attribute.removeprefix("data-") not in CONTENT_DATA_ATTRIBUTES:
                report(offset + match.start(), f"uses the data attribute {attribute!r}")

    for match in _DATASET_PROPERTY.finditer(code):
        prop = match.group(1)
        if prop in CONTENT_DATASET_PROPERTIES:
            continue
        marker = _marker_of_property(prop)
        if marker is not None:
            report(match.start(), f"reads the removed marker {marker!r} as dataset.{prop}")
        else:
            report(match.start(), f"reads the data attribute dataset.{prop}")

    for pattern, message in _RUNTIME_WRITES:
        for match in pattern.finditer(code):
            report(match.start(), message)

    return findings


# ---------------------------------------------------------------------------
# The real script
# ---------------------------------------------------------------------------


def test_the_shop_script_binds_only_to_stable_hooks() -> None:
    """The scan the rebinding of group 8 hangs on."""
    assert scan_script(SCRIPT.read_text(encoding="utf-8")) == []


def test_the_scan_actually_looked_at_the_script() -> None:
    """A scan of an empty file would pass vacuously."""
    source = SCRIPT.read_text(encoding="utf-8")

    assert "addToCart" in source
    assert len(source.splitlines()) > 200


def test_the_script_still_reads_the_content_data_attributes() -> None:
    """The stable contract of design Decision 3 is what it binds to instead."""
    source = SCRIPT.read_text(encoding="utf-8")

    assert ".dataset.product" in source
    assert ".dataset.productName" in source


# ---------------------------------------------------------------------------
# Rejected code
# ---------------------------------------------------------------------------

REJECTED = {
    "covered id in a selector": 'const input = modal.querySelector("#auth-email");',
    "covered id as a bare name": 'const flash = document.getElementById("flash-message");',
    "marker written at runtime": 'el.dataset.chatBound = "true";',
    "dead dataset read": "const quantity = Number(button.dataset.quantity);",
    "id written at runtime": 'widget.id = "x";',
    "data attribute written by name": 'el.setAttribute("data-x", "1");',
    "removed price marker": "const min = wrapper.dataset.priceMinDefault;",
    "covered modifier written from the script": 'wrapper.classList.add("chat-message--user");',
    "className assignment": 'el.className = "flash";',
    "innerHTML literal": 'el.innerHTML = "<li>x</li>";',
    "innerHTML from a variable": "list.innerHTML = html;",
    "data-test lookup": "button.closest(\"[data-test='product-card']\");",
}


@pytest.mark.parametrize("case", sorted(REJECTED))
def test_the_negative_cases_are_reported(case: str) -> None:
    findings = scan_script(REJECTED[case], name=case)

    assert findings, f"{case} was accepted"


ACCEPTED = {
    "stable state class": 'document.body.classList.toggle("site-nav-open", true);',
    "badge is a variable, not a class": 'const badge = nav.querySelector("[aria-live]");',
    "flash is a variable, not a class": 'const flash = document.querySelector(\'[role="status"]\');',
    "content data attribute": 'const button = event.target.closest("button[data-product]");',
    "content dataset property": "const name = button.dataset.productName;",
    "a comment may name a marker": "// data-cart-count is gone; the badge carries aria-live.",
    "aria attributes are written freely": 'el.setAttribute("aria-busy", "true");',
    "an id may be read": "input.setAttribute(\"aria-controls\", list.id);",
    "equality is not an assignment": "if (el.id === other.id) return;",
}


@pytest.mark.parametrize("case", sorted(ACCEPTED))
def test_the_positive_cases_are_not_reported(case: str) -> None:
    assert scan_script(ACCEPTED[case], name=case) == []


@pytest.mark.parametrize("marker", REMOVED_MARKERS)
def test_every_removed_marker_is_reported(marker: str) -> None:
    attribute = marker if not marker.endswith("-") else f"{marker}x"

    assert scan_script(f'document.querySelector("[{attribute}]");', name=attribute)
    assert scan_script(f"el.dataset.{_camel(attribute)};", name=attribute)
