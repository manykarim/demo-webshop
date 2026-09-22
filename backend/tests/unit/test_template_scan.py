"""The templates may not write a drift hook themselves (task 5.10).

Every covered name has to reach the markup through ``drift.id``, ``drift.cls``,
``drift.layout`` or ``drift.test``. That is what makes the name-based stylesheet
rewrite of group 6 safe: a class an *uncovered* flow writes literally (the
shared ``form-field`` and ``button`` blocks, ``category-badge``, the newsletter)
is not covered at all, so no element can keep pointing at a renamed rule
(design Decisions 1, 3 and 5).

The scan therefore reports, anywhere outside a ``drift.cls(...)``,
``drift.id(...)`` or ``drift.layout(...)`` argument:

* a ``LOCATOR_`` or ``BUG_`` token - a template that reads a workshop flag;
* a literal ``data-test=`` - only ``drift.test`` may render one;
* a literal ``id="..."`` whose value is not in :data:`STABLE_IDS`;
* a name in :data:`COVERED_IDS` or :data:`COVERED_CLASSES`, including the
  ``block__element`` and ``block--modifier`` names derived from a covered
  block, written as a whole class token inside a ``class="..."`` attribute.

Covered names match as whole class tokens and never as substrings, so the
uncovered literal ``category-badge`` is accepted although the covered class
``badge`` is part of it.

Task 8.5 adds a second scan, :func:`scan_markers`: the behaviour-only ``data-*``
markers are removed from the templates *and* from the stylesheet in every
stage, because they are exactly the drift-proof locators the workshop refuses
to hand out (design Decision 4). Only the four content data attributes - and
the space indicator of the sibling change ``workshop-spaces`` - may stay.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.app.core.workshop import (
    COVERED_CLASSES,
    COVERED_IDS,
    STABLE_IDS,
    is_covered_class,
)

#: The directory the scan walks: every template of the application.
TEMPLATE_ROOT = Path(__file__).resolve().parents[3] / "backend" / "app" / "templates"

#: The stylesheet source, scanned for markers together with the templates.
STYLESHEET = Path(__file__).resolve().parents[3] / "backend" / "app" / "assets" / "styles.css"

#: The data attributes that are content, not behaviour (design Decision 3),
#: plus the space indicator of ``workshop-spaces``, which is a stable hook.
ALLOWED_DATA_ATTRIBUTES = frozenset(
    {
        "data-product",
        "data-product-name",
        "data-category",
        "data-chat-prompt",
        "data-workshop-space",
    }
)

#: The behaviour-only markers task 8.5 removes, for the tests below and for
#: the script scan of task 9.4, which bans the same names in ``app.js``. An
#: entry ending in ``-`` stands for the whole family.
REMOVED_MARKERS = (
    "data-cart-count",
    "data-auth-",
    "data-chat-toggle",
    "data-chat-widget",
    "data-chat-close",
    "data-chat-form",
    "data-chat-messages",
    "data-search-",
    "data-nav-",
    "data-theme-",
    "data-icon-",
    "data-filter-form",
    "data-price-",
    "data-event",
    "data-product-id",
    "data-product-wrapper",
)

#: A ``data-*`` attribute name, wherever it is written.
_DATA_ATTRIBUTE = re.compile(r"data-[a-z0-9-]*[a-z0-9]")

#: The helper calls whose arguments are allowed to name a covered hook.
_DRIFT_CALL = re.compile(r"drift\.(?:cls|id|layout)\s*\(")

#: A workshop flag key, whatever it is used for.
_WORKSHOP_FLAG = re.compile(r"\b(?:LOCATOR|BUG)_[A-Z0-9_]+")

#: A literal test hook. ``drift.test`` renders the attribute, never a template.
_DATA_TEST = re.compile(r"data-test\s*=")

#: The whole attribute name ``id``, so ``data-product-id="..."`` is not one.
_ID_ATTRIBUTE = re.compile(r"(?<![-\w])id\s*=\s*\"([^\"]*)\"", re.DOTALL)

#: A ``class`` attribute and its value.
_CLASS_ATTRIBUTE = re.compile(r"(?<![-\w])class\s*=\s*\"([^\"]*)\"", re.DOTALL)

#: An id attribute that is resolved through the mapping.
_DRIFT_ID_VALUE = re.compile(r"\{\{\s*drift\.id\(.*?\)\s*\}\}", re.DOTALL)

#: Jinja output and statement blocks, removed before class tokens are read.
_JINJA_BLOCK = re.compile(r"\{\{.*?\}\}|\{%.*?%\}|\{#.*?#\}", re.DOTALL)


def blank_drift_arguments(text: str) -> str:
    """``text`` with the arguments of every drift call replaced by spaces.

    Blanks rather than removes, so the offsets of everything else - and with
    them the line numbers the scan reports - stay as they are.
    """
    out = list(text)
    for call in _DRIFT_CALL.finditer(text):
        index = call.end()
        depth = 1
        while index < len(text) and depth:
            char = text[index]
            if char in "\"'":
                quote = char
                index += 1
                while index < len(text) and text[index] != quote:
                    index += 2 if text[index] == "\\" else 1
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if not depth:
                    break
            if not text[index].isspace():
                out[index] = " "
            index += 1
    return "".join(out)


def _line_of(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def scan_template(text: str, *, name: str = "<template>") -> list[str]:
    """Every rule this template breaks, as readable findings."""
    findings: list[str] = []
    scrubbed = blank_drift_arguments(text)

    def report(position: int, message: str) -> None:
        findings.append(f"{name}:{_line_of(text, position)}: {message}")

    for match in _WORKSHOP_FLAG.finditer(scrubbed):
        report(match.start(), f"reads the workshop flag {match.group(0)}")

    for match in _DATA_TEST.finditer(scrubbed):
        report(match.start(), "writes data-test itself; use drift.test(...)")

    for match in _ID_ATTRIBUTE.finditer(scrubbed):
        value = text[match.start(1) : match.end(1)].strip()
        if _DRIFT_ID_VALUE.fullmatch(value):
            continue
        if value in STABLE_IDS:
            continue
        report(match.start(), f"writes the id {value!r}; use drift.id(...) or a stable id")

    for match in _CLASS_ATTRIBUTE.finditer(scrubbed):
        for token in _JINJA_BLOCK.sub(" ", match.group(1)).split():
            if is_covered_class(token):
                report(match.start(), f"writes the covered class {token!r}; use drift.cls(...)")

    return findings


def scan_markers(text: str, *, name: str = "<source>") -> list[str]:
    """Every behaviour marker ``text`` still writes (task 8.5).

    ``data-test`` is reported here as well; only ``drift.test`` renders it, and
    stages 3 and 4 render nothing at all.
    """
    findings: list[str] = []
    for match in _DATA_ATTRIBUTE.finditer(text):
        attribute = match.group(0)
        if attribute in ALLOWED_DATA_ATTRIBUTES:
            continue
        findings.append(
            f"{name}:{_line_of(text, match.start())}: writes the behaviour marker {attribute!r}"
        )
    return findings


def scan_marker_sources() -> list[str]:
    """The marker findings of every template and of the stylesheet."""
    findings: list[str] = []
    for path in sorted(TEMPLATE_ROOT.rglob("*.html")):
        findings.extend(
            scan_markers(path.read_text(encoding="utf-8"), name=str(path.relative_to(TEMPLATE_ROOT)))
        )
    findings.extend(scan_markers(STYLESHEET.read_text(encoding="utf-8"), name=STYLESHEET.name))
    return findings


def scan_templates() -> list[str]:
    """The findings of every template under ``backend/app/templates``."""
    findings: list[str] = []
    for path in sorted(TEMPLATE_ROOT.rglob("*.html")):
        findings.extend(
            scan_template(path.read_text(encoding="utf-8"), name=str(path.relative_to(TEMPLATE_ROOT)))
        )
    return findings


# ---------------------------------------------------------------------------
# The real templates
# ---------------------------------------------------------------------------


def test_the_templates_write_no_drift_hook_of_their_own() -> None:
    """The scan the whole change hangs on, run against the real templates."""
    assert scan_templates() == []


def test_no_template_and_not_the_stylesheet_writes_a_behaviour_marker() -> None:
    """Task 8.5: every removed marker has a stable replacement hook."""
    assert scan_marker_sources() == []


def test_the_content_data_attributes_survive_the_marker_scan() -> None:
    """They are part of the stable contract, so the script may read them."""
    card = (TEMPLATE_ROOT / "components" / "product_card.html").read_text(encoding="utf-8")

    assert 'data-product="' in card
    assert 'data-product-name="' in card
    assert scan_markers(card, name="product_card.html") == []


@pytest.mark.parametrize("marker", REMOVED_MARKERS)
def test_every_removed_marker_is_reported(marker: str) -> None:
    attribute = marker if not marker.endswith("-") else f"{marker}x"

    assert scan_markers(f"<div {attribute}></div>", name=attribute)
    assert scan_markers(f"[{attribute}] {{ display: none; }}", name=attribute)


def test_a_literal_data_test_is_reported_by_the_marker_scan() -> None:
    assert scan_markers('<button data-test="x"></button>', name="data-test")


def test_the_scan_actually_looked_at_the_templates() -> None:
    """A scan that finds no file would pass vacuously."""
    names = {path.name for path in TEMPLATE_ROOT.rglob("*.html")}

    assert {"base.html", "home.html", "products.html", "product_card.html"} <= names


def test_the_newsletter_block_of_home_html_passes_untouched() -> None:
    """Its three ids are stable, so no conversion was needed (design D3)."""
    home = (TEMPLATE_ROOT / "home.html").read_text(encoding="utf-8")
    newsletter = home[home.index('<form class="newsletter"') :]

    assert 'id="newsletter-email"' in newsletter
    assert scan_template(newsletter, name="newsletter") == []


# ---------------------------------------------------------------------------
# Accepted markup (fixtures written here, never rendered)
# ---------------------------------------------------------------------------

ACCEPTED_FIXTURE = """
<form class="newsletter" novalidate>
  <label class="form-field" for="newsletter-email"><span>Email</span>
    <input id="newsletter-email" type="email" aria-describedby="newsletter-hint" required />
  </label>
  <span id="newsletter-hint" class="newsletter-hint">One email a week.</span>
  <div id="newsletter-alert" class="newsletter-alert" role="alert" hidden></div>
  <span class="category-badge" data-category="audio">Audio</span>
  <article class="{{ drift.cls('product-card') }}" {{ drift.test('product-card') }}
    data-product-id="{{ product.id }}">
    <a class="button button--primary {{ drift.cls('product-card__add') }}"
      href="{{ bugs.card_href(product) }}" id="{{ drift.id('search-results') }}">Add to cart</a>
  </article>
  <div class="{{ drift.cls('site-nav__link site-nav__link--cart') }}{% if active %} active{% endif %}"></div>
</form>
"""


def test_the_accepted_fixture_is_accepted() -> None:
    assert scan_template(ACCEPTED_FIXTURE, name="accepted") == []


@pytest.mark.parametrize(
    "token",
    ["category-badge", "site-nav-open", "form-field", "form-field__icon", "button", "button--primary"],
)
def test_a_literal_class_of_an_uncovered_flow_is_accepted(token: str) -> None:
    """The invariant that keeps the stylesheet rewrite safe (Decision 5)."""
    assert not is_covered_class(token)
    assert scan_template(f'<div class="{token}"></div>', name="uncovered") == []


# ---------------------------------------------------------------------------
# Rejected markup
# ---------------------------------------------------------------------------

REJECTED = {
    "workshop flag": '{% if feature_flags.get("LOCATOR_V2") %}<span>drifted</span>{% endif %}',
    "literal data-test": '<button data-test="x">Add to cart</button>',
    "covered id": '<input id="auth-email" name="email" />',
    "unknown id": '<input type="range" id="price-mid-range" />',
    "covered class block": '<div class="product-grid"></div>',
    "covered class element": '<h3 class="product-card__title">Name</h3>',
}


@pytest.mark.parametrize("case", sorted(REJECTED))
def test_the_negative_cases_are_reported(case: str) -> None:
    findings = scan_template(REJECTED[case], name=case)

    assert findings, f"{case} was accepted"


def test_a_covered_name_inside_a_drift_call_is_not_a_finding() -> None:
    """The same name is fine as an argument and a finding as markup."""
    assert scan_template("""<div class="{{ drift.cls('product-grid') }}"></div>""") == []
    assert scan_template('<div class="product-grid"></div>')


@pytest.mark.parametrize("name", sorted(COVERED_CLASSES))
def test_every_covered_class_is_reported_when_written_literally(name: str) -> None:
    assert scan_template(f'<div class="{name}"></div>', name=name)


@pytest.mark.parametrize("name", sorted(COVERED_IDS))
def test_every_covered_id_is_reported_when_written_literally(name: str) -> None:
    assert scan_template(f'<div id="{name}"></div>', name=name)


@pytest.mark.parametrize("name", sorted(STABLE_IDS))
def test_every_stable_id_may_be_written_literally(name: str) -> None:
    assert scan_template(f'<div id="{name}"></div>', name=name) == []


def test_a_data_attribute_ending_in_id_is_not_an_id(name: str = "data-product-id") -> None:
    """The literal-id rule matches the whole attribute name (task 5.10)."""
    assert scan_template(f'<article {name}="{{{{ product.id }}}}"></article>') == []
