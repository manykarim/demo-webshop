"""The stylesheet follows the drift (task 6.1, design Decision 5).

One variant per distinct class mapping is built at startup from the single
source ``backend/app/assets/styles.css``. The rewrite renames covered class
tokens in *selector preludes* only, so the rules of the uncovered flows - the
shared ``form-field`` and ``button`` blocks above all - keep working in every
stage, and nothing inside a declaration block or an at-rule prelude can be
mistaken for a class name.

Two parts, as the task asks: the checks below run against the real stylesheet,
and ``TestSyntheticStylesheet`` covers the forms the real file does not contain.
"""
from __future__ import annotations

import re

import pytest

from backend.app.core.workshop import (
    COVERED_CLASSES,
    STAGES,
    STYLESHEET_SOURCE,
    STYLESHEET_VARIANTS,
    DriftView,
    build_stylesheet_variants,
    is_covered_class,
    rewrite_stylesheet,
)

#: The stylesheet as it is shipped.
SOURCE = STYLESHEET_SOURCE.read_text(encoding="utf-8")

#: One rule: its prelude and its declaration block. Nested rules inside an
#: at-rule block match as well, and at-rule preludes do not.
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")

#: Every class token of a selector.
CLASS_TOKEN = re.compile(r"\.(-?[_a-zA-Z][-_a-zA-Z0-9]*)")

#: The rules whose preludes hold only uncovered tokens. They must be identical
#: in every variant, byte for byte.
UNCOVERED_RULES = [
    ".form-field",
    ".form-field input, .form-field textarea",
    ".form-field__icon",
    ".button",
    ".button--primary",
    ".button--primary:hover, .button--primary:focus-visible",
    ".button--ghost",
    ".button--ghost:hover, .button--ghost:focus-visible",
    ".button--text",
    ".button--lg",
    '.button[aria-busy="true"]',
]

#: The four-selector focus rule, whose two covered tokens follow their blocks
#: while ``.button`` and ``.theme-toggle`` stay as they are.
FOCUS_RULE = ".button:focus-visible, .theme-toggle:focus-visible, .{nav}:focus-visible, .{card}:focus-visible"

#: The three real rules that put a shared token in the same prelude as a
#: covered one, with the prelude each stage must render.
MIXED_RULES = {
    1: [
        FOCUS_RULE.format(nav="site-nav__link", card="product-card__link"),
        ".product-card--compact .button",
        ".auth-modal__form .form-field",
    ],
    2: [
        FOCUS_RULE.format(nav="main-nav__link", card="item-card__link"),
        ".item-card--compact .button",
        ".signin-modal__form .form-field",
    ],
    3: [
        FOCUS_RULE.format(nav="site-nav__link", card="product-card__link"),
        ".product-card--compact .button",
        ".auth-modal__form .form-field",
    ],
    4: [
        FOCUS_RULE.format(nav="topbar-nav__link", card="product-tile__link"),
        ".product-tile--compact .button",
        ".login-dialog__form .form-field",
    ],
}

#: Selectors that hold no covered class token and must come through unchanged.
UNTOUCHED_SELECTORS = [
    "*,\n*::before,\n*::after",
    "body.site-nav-open",
    "body.theme-dark",
    '.category-badge[data-category="audio"]',
    '.category-badge[data-category="home office"]',
    '.button[aria-busy="true"]',
    'input[type="range"]',
    ".theme-toggle",
    ".workshop-space",
    ".workshop-space-hint",
]

#: The shared tokens of the uncovered flows (design Decision 3).
SHARED_TOKENS = [
    "form-field",
    "form-field__icon",
    "button",
    "button--primary",
    "button--ghost",
    "button--text",
    "button--lg",
    "theme-toggle",
    "category-badge",
    "site-nav-open",
    "workshop-space",
    "workshop-space-hint",
]


def variant(stage: int) -> str:
    """The stylesheet of ``stage``."""
    return STYLESHEET_VARIANTS[stage].css


#: A comment, dropped before a prelude is normalised.
COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def rules(css: str) -> list[tuple[str, str]]:
    """``(normalised prelude, declaration block)`` of every rule in ``css``.

    The prelude is read without the comments in front of it, so the rule under
    the space-indicator comment is found by its selector.
    """
    return [
        (" ".join(COMMENT.sub(" ", match.group(1)).split()), match.group(2))
        for match in RULE.finditer(css)
    ]


def rule_text(css: str, prelude: str) -> str:
    """The one rule of ``css`` whose normalised prelude is ``prelude``."""
    matches = [
        match.group(0)
        for match in RULE.finditer(css)
        if " ".join(COMMENT.sub(" ", match.group(1)).split()) == prelude
    ]
    assert len(matches) == 1, f"{prelude!r} matched {len(matches)} rules"
    return matches[0]


def class_tokens(css: str) -> list[str]:
    """Every class token of every selector prelude of ``css``."""
    return [token for prelude, _ in rules(css) for token in CLASS_TOKEN.findall(prelude)]


def at_rule_preludes(css: str) -> list[str]:
    return [line.strip() for line in css.splitlines() if line.lstrip().startswith("@")]


# ---------------------------------------------------------------------------
# (a) Against the real stylesheet
# ---------------------------------------------------------------------------


def test_stages_one_and_three_share_one_variant() -> None:
    """They rename no class, so they are the same bytes and the same URL."""
    assert STYLESHEET_VARIANTS[1] is STYLESHEET_VARIANTS[3]
    assert STYLESHEET_VARIANTS[1].digest == STYLESHEET_VARIANTS[3].digest
    assert len({STYLESHEET_VARIANTS[stage].digest for stage in STAGES}) == 3


def test_stage_one_is_the_source_itself() -> None:
    assert variant(1) == SOURCE


def test_every_variant_has_its_own_href_with_its_digest() -> None:
    for stage in STAGES:
        entry = STYLESHEET_VARIANTS[stage]
        assert entry.href == f"/assets/styles.{entry.digest}.css"
        assert DriftView(stage).stylesheet_href == entry.href


@pytest.mark.parametrize("stage", [2, 4])
@pytest.mark.parametrize("name", sorted(COVERED_CLASSES))
def test_no_covered_stage_one_class_survives(stage: int, name: str) -> None:
    """Matched as whole class tokens, so ``category-badge`` is not a hit."""
    assert name not in class_tokens(variant(stage))


@pytest.mark.parametrize("stage", [2, 4])
def test_no_derived_covered_name_survives_either(stage: int) -> None:
    """``product-card__title`` follows its block without a row of its own."""
    assert [token for token in class_tokens(variant(stage)) if is_covered_class(token)] == []


@pytest.mark.parametrize("token", SHARED_TOKENS)
def test_a_shared_token_appears_in_every_variant_as_often_as_in_the_source(token: str) -> None:
    """Renaming one would ripple into the filter panel and the newsletter."""
    expected = class_tokens(SOURCE).count(token)
    assert expected, f"{token} is not in the stylesheet at all"
    for stage in STAGES:
        assert class_tokens(variant(stage)).count(token) == expected


@pytest.mark.parametrize("prelude", UNCOVERED_RULES)
def test_a_rule_of_an_uncovered_flow_is_identical_in_every_variant(prelude: str) -> None:
    expected = rule_text(SOURCE, prelude)
    for stage in STAGES:
        assert rule_text(variant(stage), prelude) == expected


@pytest.mark.parametrize("stage", STAGES)
def test_a_mixed_rule_keeps_its_shared_token(stage: int) -> None:
    """Only the covered tokens of these three rules change."""
    preludes = {prelude for prelude, _ in rules(variant(stage))}
    for expected in MIXED_RULES[stage]:
        assert expected in preludes


@pytest.mark.parametrize("stage", STAGES)
def test_every_declaration_block_is_unchanged(stage: int) -> None:
    assert [body for _, body in rules(variant(stage))] == [body for _, body in rules(SOURCE)]


@pytest.mark.parametrize("stage", STAGES)
def test_the_at_rule_preludes_are_unchanged(stage: int) -> None:
    assert at_rule_preludes(variant(stage)) == at_rule_preludes(SOURCE)
    assert "@media (max-width: 900px) {" in variant(stage)
    assert "@media (max-width: 600px) {" in variant(stage)


@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("selector", UNTOUCHED_SELECTORS)
def test_a_selector_without_a_covered_token_is_unchanged(stage: int, selector: str) -> None:
    assert selector in variant(stage)


@pytest.mark.parametrize("stage", STAGES)
def test_the_child_combinator_of_the_mobile_menu_survives(stage: int) -> None:
    """``.site-nav__items>*`` may only have its class token renamed."""
    expected = f".{DriftView(stage).cls('site-nav__items')}>*"
    assert expected in variant(stage)


def test_the_source_has_no_class_attribute_selector() -> None:
    """A token rewrite cannot see inside ``[class*="..."]``."""
    assert "[class" not in SOURCE


def test_the_space_indicator_keeps_its_rules() -> None:
    """``workshop-spaces`` requires them to be unaffected by drift."""
    for stage in STAGES:
        assert rule_text(variant(stage), ".workshop-space") == rule_text(SOURCE, ".workshop-space")
        assert rule_text(variant(stage), ".workshop-space-hint") == rule_text(SOURCE, ".workshop-space-hint")



# ---------------------------------------------------------------------------
# The rules that moved off a removed hook (task 8.4)
# ---------------------------------------------------------------------------

#: The pending chat message draws its "Thinking..." indicator from `aria-busy`
#: now, scoped to the chat log because the add-to-cart button carries
#: `aria-busy` too and has a rule of its own. Neither selector holds a class
#: token, so every variant must carry it byte for byte.
THINKING_PRELUDE = '[role="log"] [aria-busy="true"]::after'


@pytest.mark.parametrize("stage", STAGES)
def test_every_variant_draws_the_pending_chat_indicator(stage: int) -> None:
    matching = [block for prelude, block in rules(variant(stage)) if prelude == THINKING_PRELUDE]

    assert len(matching) == 1
    assert 'content: "Thinking...";' in matching[0]


@pytest.mark.parametrize("stage", STAGES)
def test_no_variant_keeps_a_loading_modifier(stage: int) -> None:
    """``chat-message--loading`` is gone, in the source and in every variant."""
    assert "--loading" not in variant(stage)

# ---------------------------------------------------------------------------
# (b) A synthetic stylesheet, for the forms the real file does not contain
# ---------------------------------------------------------------------------

FIXTURE = """\
/* fixture: not the shop's stylesheet */
@media (max-width: 40.5em) {
  .product-card {
    margin: .5rem;
    content: ".product-card";
    background: url(card.png);
  }
}

.product-card__title::after {
  content: "\\201C";
  font: .9rem/1.2 system-ui;
}

.category-badge[data-category="home office"] {
  margin: .25rem 0 0 .5rem;
}
"""


class TestSyntheticStylesheet:
    """Decimals, leading-dot values and class-like strings stay as they are."""

    @pytest.fixture(params=[2, 4])
    def rewritten(self, request) -> str:
        return rewrite_stylesheet(FIXTURE, DriftView(request.param))

    def test_the_at_rule_prelude_keeps_its_decimal(self, rewritten: str) -> None:
        assert "@media (max-width: 40.5em) {" in rewritten

    def test_a_value_without_a_leading_zero_is_untouched(self, rewritten: str) -> None:
        assert "margin: .5rem;" in rewritten
        assert "font: .9rem/1.2 system-ui;" in rewritten
        assert "margin: .25rem 0 0 .5rem;" in rewritten

    def test_a_class_like_string_inside_a_declaration_is_untouched(self, rewritten: str) -> None:
        assert 'content: ".product-card";' in rewritten
        assert "background: url(card.png);" in rewritten
        assert 'content: "\\201C";' in rewritten

    def test_an_uncovered_selector_is_untouched(self, rewritten: str) -> None:
        assert '.category-badge[data-category="home office"] {' in rewritten

    def test_the_nested_rule_and_the_pseudo_element_do_drift(self) -> None:
        """The fixture is not unchanged as a whole, or it would prove nothing."""
        rewritten = rewrite_stylesheet(FIXTURE, DriftView(2))

        assert "\n  .item-card {\n" in rewritten
        assert ".item-title::after {" in rewritten

    def test_stages_one_and_three_leave_the_fixture_alone(self) -> None:
        for stage in (1, 3):
            assert rewrite_stylesheet(FIXTURE, DriftView(stage)) == FIXTURE

    def test_variants_are_built_per_distinct_mapping(self) -> None:
        built = build_stylesheet_variants(FIXTURE)

        assert built[1] is built[3]
        assert len({entry.digest for entry in built.values()}) == 3
