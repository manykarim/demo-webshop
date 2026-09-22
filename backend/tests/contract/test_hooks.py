"""Hook extraction, stage expectations and both oracles, on fixtures (task 4.3).

The stage contract test (``test_stage_contract.py``) runs these checks against
real renders, where a passing run proves only that the shop and the mapping
agree. This module proves the *checks* themselves: the fixtures below are
hand-written stage renders, and every deliberate breach must be reported.
"""
from __future__ import annotations

import pytest

from .coverage_oracle import (
    CoverageEntry,
    check_coverage,
    check_oracle_consistency,
    expected_breaks,
)
from .hooks import (
    ancestor_chain,
    check_stage_expectations,
    extract_hooks,
    matches,
    selector_chains,
)
from .structure_oracle import (
    StructureAnchor,
    anchors_for_page,
    check_declared_components,
    check_page_structure,
)

#: A miniature stage-1 render: one hook of every covered kind.
STAGE_1 = """<body>
  <nav class="site-nav">
    <a class="site-nav__link site-nav__link--cart" href="/cart">
      <span class="badge" data-test="cart-count">2</span></a>
  </nav>
  <main id="main-content">
    <form class="checkout-form" action="/checkout" method="post">
      <label class="form-field" for="checkout-email">Email</label>
      <input id="checkout-email" name="email" data-test="checkout-email-input" />
    </form>
    <div class="product-grid">
      <article class="product-card" data-test="product-card">
        <button class="button product-card__add" data-product="3"
          data-test="add-to-cart-btn">Add to cart</button>
      </article>
    </div>
    <div class="chat-widget" id="chat-widget">
      <input class="chat-widget__input" id="chat-input" name="question" data-test="chat-input" />
    </div>
  </main>
</body>"""

#: Stage 2: ids and classes renamed, every test hook kept, nesting untouched.
STAGE_2 = """<body>
  <nav class="main-nav">
    <a class="main-nav__link main-nav__link--cart" href="/cart">
      <span class="count-bubble" data-test="cart-count">2</span></a>
  </nav>
  <main id="main-content">
    <form class="order-form" action="/checkout" method="post">
      <label class="form-field" for="order-email">Email</label>
      <input id="order-email" name="email" data-test="checkout-email-input" />
    </form>
    <div class="item-collection">
      <article class="item-card" data-test="product-card">
        <button class="button btn-main" data-product="3"
          data-test="add-to-cart-btn">Add to cart</button>
      </article>
    </div>
    <div class="assistant-widget" id="assistant-panel">
      <input class="assistant-widget__input" id="assistant-question" name="question"
        data-test="chat-input" />
    </div>
  </main>
</body>"""

#: Stage 3: no test hooks, classes untouched, only form-field ids renamed.
STAGE_3 = """<body>
  <nav class="site-nav">
    <a class="site-nav__link site-nav__link--cart" href="/cart">
      <span class="badge">2</span></a>
  </nav>
  <main id="main-content">
    <form class="checkout-form" action="/checkout" method="post">
      <label class="form-field" for="buyer-email">Email</label>
      <input id="buyer-email" name="email" />
    </form>
    <div class="product-grid">
      <article class="product-card">
        <button class="button product-card__add" data-product="3">Add to cart</button>
      </article>
    </div>
    <div class="chat-widget" id="chat-widget">
      <input class="chat-widget__input" id="chat-question" name="question" />
    </div>
  </main>
</body>"""

#: Stage 4: no test hooks, ids and classes renamed, the card re-nested.
STAGE_4 = """<body>
  <nav class="topbar-nav">
    <a class="topbar-nav__link topbar-nav__link--cart" href="/cart">
      <span class="cart-pip">2</span></a>
  </nav>
  <main id="main-content">
    <form class="payment-form" action="/checkout" method="post">
      <label class="form-field" for="payment-email">Email</label>
      <input id="payment-email" name="email" />
    </form>
    <div class="tile-rack">
      <div class="product-tile__wrapper">
        <article class="product-tile">
          <button class="button product-tile__add" data-product="3">Add to cart</button>
        </article>
      </div>
    </div>
    <div class="concierge-panel" id="concierge-dock">
      <input class="concierge-panel__input" id="concierge-question" name="question" />
    </div>
  </main>
</body>"""

#: The structural anchor of the fixtures: a stable content data attribute.
CARD_ANCHOR = "button[data-product]"

STAGE_HTML = {1: STAGE_1, 2: STAGE_2, 3: STAGE_3, 4: STAGE_4}


# ---------------------------------------------------------------------------
# Hook extraction
# ---------------------------------------------------------------------------


def test_extract_hooks_reads_ids_classes_and_the_test_multiset() -> None:
    hooks = extract_hooks(STAGE_1 + STAGE_1)

    assert "checkout-email" in hooks.ids
    assert "main-content" in hooks.ids
    assert {"site-nav", "site-nav__link--cart", "product-card__add"} <= hooks.classes
    # The multiset counts occurrences: the fixture is present twice.
    assert hooks.data_test["add-to-cart-btn"] == 2
    assert hooks.covered_ids == {"checkout-email", "chat-widget", "chat-input"}
    assert hooks.form_field_ids == {"checkout-email", "chat-input"}


def test_ancestor_chain_runs_up_to_body() -> None:
    button = matches(STAGE_1, CARD_ANCHOR)[0]

    assert ancestor_chain(button) == ("body", "main", "div", "article")


def test_stage_4_adds_one_level_to_the_card_chain() -> None:
    assert selector_chains(STAGE_1, CARD_ANCHOR) == (("body", "main", "div", "article"),)
    assert selector_chains(STAGE_4, CARD_ANCHOR) == (("body", "main", "div", "div", "article"),)


# ---------------------------------------------------------------------------
# Stage expectations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage", [1, 2, 3, 4])
def test_the_fixtures_satisfy_their_stage(stage: int) -> None:
    """Each hand-written stage render keeps the contract of its stage."""
    assert check_stage_expectations(stage, STAGE_1, STAGE_HTML[stage], (CARD_ANCHOR,)) == []


@pytest.mark.parametrize(
    ("description", "stage", "html", "expected"),
    [
        (
            "a covered class that stage 2 forgot to rename",
            2,
            STAGE_2.replace('class="item-collection"', 'class="product-grid"'),
            "still rendered under their stage-1 name",
        ),
        (
            "a test hook stage 2 dropped",
            2,
            STAGE_2.replace(' data-test="cart-count"', ""),
            "the data-test multiset changed",
        ),
        (
            "a test hook stage 3 kept",
            3,
            STAGE_3.replace('id="buyer-email"', 'id="buyer-email" data-test="checkout-email-input"'),
            "must render no data-test attribute",
        ),
        (
            "a class stage 3 renamed",
            3,
            STAGE_3.replace('class="product-grid"', 'class="item-collection"'),
            "classes disappeared although the mapping does not rename them",
        ),
        (
            "a non-form-field id stage 3 renamed",
            3,
            STAGE_3.replace('id="chat-widget"', 'id="assistant-panel"'),
            "ids disappeared although the mapping does not rename them",
        ),
        (
            "an id stage 2 renamed to something the mapping never declares",
            2,
            STAGE_2.replace('id="order-email"', 'id="surprise-email"').replace(
                'for="order-email"', 'for="surprise-email"'
            ),
            "this stage does not declare as replacements",
        ),
        (
            "a stable id stage 4 lost",
            4,
            STAGE_4.replace(' id="main-content"', ""),
            "stable ids are missing",
        ),
        (
            "nesting that stage 2 changed",
            2,
            STAGE_2.replace("<article", "<div><article").replace("</article>", "</article></div>"),
            "the nesting of",
        ),
    ],
)
def test_a_breach_of_the_stage_contract_is_reported(
    description: str, stage: int, html: str, expected: str
) -> None:
    problems = check_stage_expectations(stage, STAGE_1, html, (CARD_ANCHOR,))

    assert any(expected in problem for problem in problems), (description, problems)


def test_a_stage_that_renames_nothing_at_all_is_reported() -> None:
    """Stage 2 rendered as stage 1 would be the drift silently switched off."""
    problems = check_stage_expectations(2, STAGE_1, STAGE_1, (CARD_ANCHOR,))

    assert any("did not change" in problem for problem in problems), problems


# ---------------------------------------------------------------------------
# The coverage oracle
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("selector", "breaks"),
    [
        ("[data-test='product-card']", (3, 4)),
        (".site-nav__link--cart .badge", (2, 4)),
        ("#chat-widget", (2, 4)),
        ("#checkout-email", (2, 3, 4)),
        # A descendant selector breaks as soon as any of its parts breaks.
        ("#chat-widget [data-test='chat-input']", (2, 3, 4)),
    ],
)
def test_expected_breaks_follows_the_hook_kind(selector: str, breaks: tuple[int, ...]) -> None:
    assert expected_breaks(selector) == breaks


@pytest.mark.parametrize("selector", ["#main-content", ".button--primary", "article"])
def test_a_selector_that_never_drifts_is_rejected(selector: str) -> None:
    with pytest.raises(ValueError):
        expected_breaks(selector)


FIXTURE_ENTRIES = (
    CoverageEntry("Listing and cards", "[data-test='product-card']", (3, 4), ("fixture",)),
    CoverageEntry("Listing and cards", ".product-card__add", (2, 4), ("fixture",)),
    CoverageEntry("Checkout form, summary and result", "#checkout-email", (2, 3, 4), ("fixture",)),
)


@pytest.mark.parametrize("stage", [1, 2, 3, 4])
def test_the_fixtures_break_exactly_the_named_selectors(stage: int) -> None:
    assert check_coverage("fixture", stage, STAGE_HTML[stage], FIXTURE_ENTRIES) == []


def test_an_entry_that_still_matches_in_a_stage_it_names_is_reported() -> None:
    """The stage-3 render keeps its test hook: the entry names 3, so it fails."""
    still_hooked = STAGE_3.replace(
        '<article class="product-card">', '<article class="product-card" data-test="product-card">'
    )

    problems = check_coverage("fixture", 3, still_hooked, FIXTURE_ENTRIES)

    assert len(problems) == 1
    assert "must break in stage 3" in problems[0]


def test_an_entry_that_stops_matching_too_early_is_reported() -> None:
    """A class entry must survive stage 3, where classes do not move."""
    renamed = STAGE_3.replace("product-card__add", "btn-main")

    problems = check_coverage("fixture", 3, renamed, FIXTURE_ENTRIES)

    assert len(problems) == 1
    assert "must still match in stage 3" in problems[0]


def test_an_entry_with_the_wrong_break_stages_is_reported() -> None:
    wrong = (CoverageEntry("Listing and cards", "[data-test='product-card']", (2, 3, 4), ("fixture",)),)

    problems = check_oracle_consistency(wrong, flows=())

    assert len(problems) == 1
    assert "declares breaks (2, 3, 4)" in problems[0]


def test_a_flow_without_a_data_test_entry_is_reported() -> None:
    only_classes = (CoverageEntry("Listing and cards", ".product-card__add", (2, 4), ("fixture",)),)

    problems = check_oracle_consistency(only_classes, flows=("Listing and cards",))

    assert problems == ["the flow 'Listing and cards' has no data-test entry"]


# ---------------------------------------------------------------------------
# The structural oracle
# ---------------------------------------------------------------------------

FIXTURE_ORACLE = {"product-card": (StructureAnchor(CARD_ANCHOR, ("fixture",)),)}


def test_anchors_for_page_lists_only_the_page_s_anchors() -> None:
    assert anchors_for_page("fixture", FIXTURE_ORACLE) == (CARD_ANCHOR,)
    assert anchors_for_page("elsewhere", FIXTURE_ORACLE) == ()


@pytest.mark.parametrize("stage", [1, 2, 3, 4])
def test_the_fixture_re_nests_the_card_in_stage_4(stage: int) -> None:
    assert check_page_structure("fixture", stage, STAGE_1, STAGE_HTML[stage], FIXTURE_ORACLE) == []


def test_a_stage_4_layout_that_did_not_move_is_reported() -> None:
    """Stage 4 declares a card layout; a flat card render must fail."""
    flat = STAGE_4.replace('<div class="product-tile__wrapper">', "").replace(
        "</article>\n      </div>", "</article>"
    )

    problems = check_page_structure("fixture", 4, STAGE_1, flat, FIXTURE_ORACLE)

    assert len(problems) == 1
    assert "is unchanged" in problems[0]


def test_an_anchor_that_matches_nothing_is_reported() -> None:
    """An anchor built on a hook the page does not render hides the check."""
    oracle = {"product-card": (StructureAnchor("button[data-nowhere]", ("fixture",)),)}

    problems = check_page_structure("fixture", 4, STAGE_1, STAGE_4, oracle)

    assert len(problems) == 1
    assert "matches nothing on fixture in stage 1" in problems[0]


def test_an_anchor_that_disappears_in_the_drifted_stage_is_reported() -> None:
    without_button = STAGE_4.replace(' data-product="3"', "")

    problems = check_page_structure("fixture", 4, STAGE_1, without_button, FIXTURE_ORACLE)

    assert len(problems) == 1
    assert "matches nothing on fixture in stage 4" in problems[0]


def test_a_component_that_no_anchor_checks_is_reported() -> None:
    problems = check_declared_components(FIXTURE_ORACLE)

    assert len(problems) == 1
    assert "no anchor checks" in problems[0]


def test_a_component_stage_4_does_not_declare_is_reported() -> None:
    oracle = dict(FIXTURE_ORACLE)
    oracle["invented-layout"] = (StructureAnchor(CARD_ANCHOR, ("fixture",)),)

    problems = check_declared_components(oracle)

    assert any("does not declare: ['invented-layout']" in problem for problem in problems), problems
