"""The named scenarios of the `locator-drift` spec (task 14.2).

`test_stage_contract.py` checks the whole matrix mechanically - snapshot
equality, the mapping, the two oracles. This module spells out the four
scenarios the spec names, in the spec's own words, so a reviewer can read the
requirement and the check side by side:

* "Stage 2 keeps semantics" - the checkout page means the same and is called
  something else;
* "Stage 3 removes test hooks" - the listing has no `data-test` left and every
  card still shows what it showed;
* "Stage 4 restructures" - the cards are nested differently and a role-and-text
  locator still finds each card's add-to-cart button *inside that card*;
* "Stage 4 restructures checkout" - every checkout field sits somewhere else and
  its label still names it.

Everything here is located the way a resilient suite would locate it: by role,
by accessible name, by visible text, by field `name` and by the stable content
attribute `data-product`. The only drifting hooks that appear are the ones a
scenario asserts have *gone*.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

import pytest
from bs4 import Tag

from .conftest import PAGES_BY_KEY
from .hooks import ancestor_chain, extract_hooks, matches, soup_of
from .semantic import accessible_name, document, normalize_text, visible_text

#: The checkout fields, by the `name` attribute that never drifts.
CHECKOUT_FIELDS: tuple[str, ...] = ("email", "name", "address", "team_size", "notes")

#: The stage-1 ids of those fields, which stages 2 to 4 all rename.
CHECKOUT_FIELD_IDS: tuple[str, ...] = (
    "checkout-email",
    "checkout-name",
    "checkout-address",
    "checkout-team-size",
    "checkout-notes",
)

#: The visible text of every card's action, in every stage.
ADD_TO_CART = "Add to cart"

#: A currency amount as the shop prints it.
_PRICE = re.compile(r"\$[\d,]+\.\d{2}")


def has_button_role(element: Tag) -> bool:
    """Whether ``element`` exposes the ARIA role ``button``.

    Either explicitly, or implicitly as a `<button>` that does not override it.
    This is the same rule the semantic snapshot applies; it is restated here so
    that the scenarios read as "an element with button role" and depend on no
    private helper.
    """
    explicit = str(element.get("role") or "").strip().lower()
    if explicit:
        return explicit == "button"
    return element.name == "button"


def cards_with_actions(html: str) -> list[Tag]:
    """Every product card that renders an add-to-cart button.

    A card is an `<article>`; the stable content attribute `data-product` marks
    its action. The category-preview cards of `/products` render no action at
    all (the page calls the macro with `show_actions=False`), so they are not
    cards "that contain a `button[data-product]`" and stay out of this check.
    """
    soup = soup_of(html)
    return [
        article
        for article in soup.find_all("article")
        if article.select_one("button[data-product]") is not None
    ]


def card_summary(card: Tag) -> tuple[str, str, tuple[str, ...]]:
    """What a card shows: its name, its price and its button texts."""
    heading = card.find(["h2", "h3", "h4"])
    name = normalize_text(heading.get_text(" ")) if heading is not None else ""
    prices = _PRICE.findall(normalize_text(card.get_text(" ")))
    buttons = tuple(
        visible_text(element) for element in card.find_all(True) if has_button_role(element)
    )
    return name, (prices[0] if prices else ""), buttons


def label_targets(html: str) -> Mapping[str, tuple[str, str]]:
    """``{label text: (field name, tag)}`` for every `label[for]` of a render.

    Resolving the `for` through the document is the point: a label that points
    at an id no element carries is a broken association, whatever the id is
    called in this stage.
    """
    soup = soup_of(html)
    targets: dict[str, tuple[str, str]] = {}
    for label in soup.select("label[for]"):
        target = soup.find(id=label["for"])
        assert target is not None, (
            f"the label {normalize_text(label.get_text(' '))!r} points at "
            f"{label['for']!r}, which no element carries"
        )
        targets[normalize_text(label.get_text(" "))] = (
            str(target.get("name") or ""),
            target.name,
        )
    return targets


def field_of(html: str, name: str) -> Tag:
    """The checkout field called ``name``, found through the form's action."""
    found = matches(html, f'form[action="/checkout"] [name="{name}"]')
    assert len(found) == 1, f"expected one field named {name!r}, found {len(found)}"
    return found[0]


# ---------------------------------------------------------------------------
# "Stage 2 keeps semantics"
# ---------------------------------------------------------------------------


def test_stage_2_keeps_semantics(rendered) -> None:
    """The checkout page means the same and is called something else.

    Text, roles, accessible names and field names are identical; the form's
    class and every field id are not.
    """
    page = PAGES_BY_KEY["checkout-items"]
    baseline = rendered(page, 1)
    stage_2 = rendered(page, 2)

    # The semantics: labels still name their fields, and they name the same.
    assert label_targets(stage_2) == label_targets(baseline)
    assert [field_of(stage_2, name)["name"] for name in CHECKOUT_FIELDS] == list(
        CHECKOUT_FIELDS
    )

    baseline_doc = document(soup_of(baseline))
    stage_2_doc = document(soup_of(stage_2))
    for name in CHECKOUT_FIELDS:
        before = field_of(baseline, name)
        after = field_of(stage_2, name)
        assert accessible_name(after, stage_2_doc) == accessible_name(before, baseline_doc)
        assert after.get("type") == before.get("type")

    # The hooks: every field id and the form's class moved.
    baseline_ids = extract_hooks(baseline).ids
    stage_2_ids = extract_hooks(stage_2).ids
    assert set(CHECKOUT_FIELD_IDS) <= baseline_ids
    assert set(CHECKOUT_FIELD_IDS).isdisjoint(stage_2_ids)
    for name in CHECKOUT_FIELDS:
        assert field_of(stage_2, name).get("id") != field_of(baseline, name).get("id")

    assert matches(baseline, ".checkout-form")
    assert not matches(stage_2, ".checkout-form")
    assert matches(stage_2, 'form[action="/checkout"]')


# ---------------------------------------------------------------------------
# "Stage 3 removes test hooks"
# ---------------------------------------------------------------------------


def test_stage_3_removes_test_hooks(rendered) -> None:
    """No `data-test` left on the listing, and the cards show what they showed."""
    page = PAGES_BY_KEY["listing"]
    baseline = rendered(page, 1)
    stage_3 = rendered(page, 3)

    assert extract_hooks(baseline).data_test, "the stage-1 listing carries no data-test at all"
    assert not extract_hooks(stage_3).data_test
    assert "data-test" not in stage_3

    before = {summary[0]: summary for summary in map(card_summary, cards_with_actions(baseline))}
    after = {summary[0]: summary for summary in map(card_summary, cards_with_actions(stage_3))}

    assert before, "the stage-1 listing renders no card with an add-to-cart button"
    assert after == before
    for name, (_, price, buttons) in after.items():
        assert price, f"the card {name!r} shows no price"
        assert ADD_TO_CART in buttons, f"the card {name!r} lost its {ADD_TO_CART!r} button"


# ---------------------------------------------------------------------------
# "Stage 4 restructures"
# ---------------------------------------------------------------------------


def _single_by_text(card: Tag, text: str) -> Tag:
    found = [
        element
        for element in card.find_all(True)
        if has_button_role(element) and visible_text(element) == text
    ]
    assert len(found) == 1, (
        f"expected exactly one element with button role and the text {text!r} "
        f"in this card, found {len(found)}"
    )
    return found[0]


def _single_by_name(card: Tag, doc, name: str) -> Tag:
    found = [
        element
        for element in card.find_all(True)
        if has_button_role(element) and accessible_name(element, doc, "button") == name
    ]
    assert len(found) == 1, (
        f"expected exactly one element with button role and the accessible name "
        f"{name!r} in this card, found {len(found)}"
    )
    return found[0]


def _assert_card_actions_are_locatable(html: str) -> int:
    """Both stable locators find each card's action, and find the same one."""
    doc = document(soup_of(html))
    cards = cards_with_actions(html)
    assert cards, "no card with an add-to-cart button on this render"

    for card in cards:
        product_name = normalize_text(
            card.select_one("button[data-product]")["data-product-name"]
        )
        by_text = _single_by_text(card, ADD_TO_CART)
        by_name = _single_by_name(card, doc, f"Add {product_name} to cart")
        assert by_text is by_name, (
            f"the {ADD_TO_CART!r} text and the accessible name of {product_name!r} "
            f"resolve to different elements"
        )
    return len(cards)


@pytest.mark.parametrize("stage", (1, 4))
def test_the_card_action_is_found_by_role_and_text(rendered, stage: int) -> None:
    """The locator the spec scenario names works in stage 1 and in stage 4."""
    checked = _assert_card_actions_are_locatable(rendered(PAGES_BY_KEY["listing"], stage))

    assert checked > 1, f"only {checked} card checked in stage {stage}"


def test_stage_4_restructures_the_cards(rendered) -> None:
    """The cards are nested differently than in stage 1."""
    page = PAGES_BY_KEY["listing"]
    baseline = rendered(page, 1)
    stage_4 = rendered(page, 4)

    before = [ancestor_chain(card) for card in cards_with_actions(baseline)]
    after = [ancestor_chain(card) for card in cards_with_actions(stage_4)]

    assert before, "no card with an add-to-cart button in stage 1"
    assert len(after) == len(before)
    assert after != before, f"the card nesting is unchanged in stage 4: {before[0]}"
    assert all(chain != before[0] for chain in after), after[0]


# ---------------------------------------------------------------------------
# "Stage 4 restructures checkout"
# ---------------------------------------------------------------------------


def test_stage_4_restructures_checkout(rendered) -> None:
    """Every field sits somewhere else, and its label still names it."""
    page = PAGES_BY_KEY["checkout-items"]
    baseline = rendered(page, 1)
    stage_4 = rendered(page, 4)

    baseline_doc = document(soup_of(baseline))
    stage_4_doc = document(soup_of(stage_4))

    for name in CHECKOUT_FIELDS:
        before = field_of(baseline, name)
        after = field_of(stage_4, name)

        assert ancestor_chain(after) != ancestor_chain(before), (
            f"the field {name!r} is nested exactly as in stage 1: {ancestor_chain(before)}"
        )
        assert accessible_name(after, stage_4_doc) == accessible_name(before, baseline_doc)
        assert accessible_name(after, stage_4_doc), f"the field {name!r} has no accessible name"

    assert label_targets(stage_4) == label_targets(baseline)
