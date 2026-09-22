"""Unit tests for ``core/workshop.py``: the mapping, the bugs and the presets.

The drift *view* and its request seam are tested in ``test_drift_view.py``;
this module covers the tables themselves and the pure helpers built on them:
stage precedence (task 2.2), the invariants of the mapping (task 2.3), the
replacements a stage renders (task 2.5), the planted-bug helpers (task 3.1) and
the presets (task 3.3).
"""
from __future__ import annotations

import pytest

from backend.app.core.feature_flags import baseline_flags
from backend.app.core.workshop import (
    AI_FLAGS,
    BUG_FLAGS,
    COVERED_CLASSES,
    COVERED_IDS,
    DATA_TEST_VALUES,
    FORM_FIELD_IDS,
    LAYOUT_COMPONENTS,
    LOCATOR_FLAGS,
    PLANTED_BUGS,
    STABLE_IDS,
    STAGE_SPECS,
    STAGES,
    BugView,
    DriftView,
    UnknownHook,
    build_presets,
    covering_class,
    effective_stage,
    get_ai_response_template,
    is_covered_class,
)

#: The stages that rename something; stage 1 is the absence of locator flags.
DRIFTING_STAGES = STAGES[1:]


def bugs_with(*flags: str) -> BugView:
    """A bug view with exactly ``flags`` enabled."""
    return BugView.from_flags({flag: True for flag in flags})


def product(product_id: int, price: float = 100.0) -> dict:
    """The product fields the bug helpers read, as the services hand them over."""
    return {"id": product_id, "price": price, "name": f"Product {product_id}"}


class TestStagePrecedence:
    """``effective_stage``: the highest enabled locator flag wins (task 2.2)."""

    def test_no_flag_is_stage_one(self):
        """Stage 1 is the absence of locator flags; there is no LOCATOR_V1."""
        assert effective_stage({}) == 1

    @pytest.mark.parametrize(
        ("flags", "stage"),
        [
            ({"LOCATOR_V2": True}, 2),
            ({"LOCATOR_V3": True}, 3),
            ({"LOCATOR_V4": True}, 4),
            ({"LOCATOR_V2": True, "LOCATOR_V3": True}, 3),
            ({"LOCATOR_V2": True, "LOCATOR_V4": True}, 4),
            ({"LOCATOR_V2": True, "LOCATOR_V3": True, "LOCATOR_V4": True}, 4),
        ],
    )
    def test_the_highest_enabled_flag_decides(self, flags, stage):
        assert effective_stage(flags) == stage

    def test_disabled_flags_do_not_select_a_stage(self):
        """A row that exists and is false is not an enabled flag."""
        assert effective_stage({flag: False for flag in LOCATOR_FLAGS}) == 1

    def test_unrelated_flags_are_ignored(self):
        assert effective_stage({"NEW_CART_UI": True, "BUG_WRONG_PRICE": True}) == 1


class TestDriftMapping:
    """The invariants the mapping tables must keep (task 2.3)."""

    def test_stable_ids_are_exactly_the_six_documented_ids(self):
        assert STABLE_IDS == {
            "main-content",
            "price-min-range",
            "price-max-range",
            "newsletter-email",
            "newsletter-hint",
            "newsletter-alert",
        }

    def test_stable_ids_are_never_covered(self):
        """A stable id has no mapping at all, so it cannot drift by accident."""
        assert COVERED_IDS.isdisjoint(STABLE_IDS)
        for stage in DRIFTING_STAGES:
            ids = STAGE_SPECS[stage].ids
            assert STABLE_IDS.isdisjoint(ids.keys())
            assert STABLE_IDS.isdisjoint(ids.values())

    def test_every_mapped_name_is_a_covered_name(self):
        """No stage renames something the coverage tables do not know."""
        for stage in DRIFTING_STAGES:
            spec = STAGE_SPECS[stage]
            assert set(spec.ids) <= COVERED_IDS
            assert set(spec.classes.blocks) <= COVERED_CLASSES
            for name in spec.classes.exact:
                assert is_covered_class(name), name

    def test_form_field_ids_are_covered_ids(self):
        assert FORM_FIELD_IDS <= COVERED_IDS

    def test_replacement_names_are_unique_across_stages(self):
        """A locator healed for stage 2 must not pass stage 3 or 4 by accident."""
        replacements = [
            name
            for stage in DRIFTING_STAGES
            for name in (
                *STAGE_SPECS[stage].ids.values(),
                *STAGE_SPECS[stage].classes.replacements,
            )
        ]
        assert len(replacements) == len(set(replacements)), sorted(replacements)

    def test_no_replacement_is_a_stage_one_name(self):
        """Healing to a replacement name must not land back on a stage-1 hook."""
        stage_one_names = set(COVERED_IDS) | set(COVERED_CLASSES) | set(STABLE_IDS)
        for stage in DRIFTING_STAGES:
            spec = STAGE_SPECS[stage]
            stage_one_names |= set(spec.ids) | set(spec.classes.blocks)
            stage_one_names |= set(spec.classes.exact)
        for stage in DRIFTING_STAGES:
            spec = STAGE_SPECS[stage]
            for name in (*spec.ids.values(), *spec.classes.replacements):
                assert name not in stage_one_names, name

    def test_only_stage_two_keeps_data_test(self):
        """Stage 3 and stage 4 remove every ``data-test`` attribute."""
        assert [stage for stage in DRIFTING_STAGES if STAGE_SPECS[stage].keep_data_test] == [2]
        assert STAGE_SPECS[1].keep_data_test is True

    def test_stage_three_renames_only_form_field_ids(self):
        """Stage 3 keeps the classes and touches the form fields only."""
        spec = STAGE_SPECS[3]
        assert not spec.classes
        assert set(spec.ids) <= FORM_FIELD_IDS

    def test_only_stage_four_restructures(self):
        """The ``layout`` list is exhaustive and belongs to stage 4 alone."""
        assert set(STAGE_SPECS[4].layout) <= set(LAYOUT_COMPONENTS)
        assert STAGE_SPECS[4].layout
        for stage in (1, 2, 3):
            assert not STAGE_SPECS[stage].layout

    def test_the_card_block_names_are_the_ones_the_spaces_suite_relies_on(self):
        """``rendered_stage()`` in backend/tests/spaces/helpers.py reads these."""
        assert STAGE_SPECS[2].classes.blocks["product-card"] == "item-card"
        assert STAGE_SPECS[4].classes.blocks["product-card"] == "product-tile"

    def test_covered_class_derivation_follows_the_block(self):
        """A covered block covers its BEM element and modifier names as well."""
        assert covering_class("product-card") == "product-card"
        assert covering_class("product-card__title") == "product-card"
        assert covering_class("product-card--compact") == "product-card"
        assert covering_class("category-badge") is None
        assert covering_class("button--primary") is None


class TestLocatorVariations:
    """The class names a stage renders (``DriftView.cls``, task 2.5)."""

    def test_stage_one_renames_nothing(self):
        assert DriftView(1).cls("product-card") == "product-card"
        assert DriftView(1).cls("product-card__title") == "product-card__title"

    def test_stage_two_renames_the_card(self):
        drift = DriftView(2)
        assert drift.cls("product-card") == "item-card"
        assert drift.cls("product-card__title") == "item-title"
        assert drift.cls("product-card__price") == "item-cost"
        assert drift.cls("product-card__cta") == "item-actions"

    def test_stage_two_renames_the_card_action_to_the_name_it_always_had(self):
        """``btn-main`` is the stage-2 name of the card action hook now.

        The inherited ``button--primary -> btn-main`` entry went with the old
        helpers: the shared ``button`` block styles the filter panel, the
        newsletter and the auth, chat and checkout buttons too, so it is
        uncovered and stays literal in every stage (design Decision 3).
        """
        assert DriftView(2).cls("product-card__add") == "btn-main"
        with pytest.raises(UnknownHook):
            DriftView(2).cls("button--primary")

    def test_stage_four_takes_precedence_over_stage_two(self):
        """Both flags on means stage 4, on every page and in the card."""
        stage = effective_stage({"LOCATOR_V2": True, "LOCATOR_V4": True})
        assert stage == 4
        assert DriftView(stage).cls("product-card") == "product-tile"

    def test_unknown_classes_raise(self):
        """A typo fails the contract tests instead of quietly not drifting."""
        with pytest.raises(UnknownHook):
            DriftView(2).cls("unknown-class")

    @pytest.mark.parametrize("stage", STAGES)
    def test_covered_ids_resolve_through_the_stage_table(self, stage):
        """Whatever is registered, ``id()`` answers the table or the key."""
        drift = DriftView(stage)
        for key in COVERED_IDS:
            assert drift.id(key) == STAGE_SPECS[stage].ids.get(key, key)

    @pytest.mark.parametrize("stage", STAGES)
    def test_stable_ids_are_not_addressable_through_the_view(self, stage):
        """They are written literally; asking for them is a template bug."""
        drift = DriftView(stage)
        for key in sorted(STABLE_IDS):
            with pytest.raises(UnknownHook):
                drift.id(key)


class TestDataTestAttributes:
    """``DriftView.test``: the hook that stages 3 and 4 take away (task 2.5)."""

    @pytest.mark.parametrize("stage", [1, 2])
    def test_stages_one_and_two_render_the_attribute(self, stage):
        assert DriftView(stage).test("product-card") == 'data-test="product-card"'

    @pytest.mark.parametrize("stage", [3, 4])
    def test_stages_three_and_four_render_nothing(self, stage):
        assert DriftView(stage).test("product-card") == ""

    @pytest.mark.parametrize("stage", STAGES)
    def test_unknown_values_raise(self, stage):
        with pytest.raises(UnknownHook):
            DriftView(stage).test("not-a-registered-hook")

    @pytest.mark.parametrize("value", sorted(DATA_TEST_VALUES))
    def test_every_registered_value_renders_in_stage_two(self, value):
        assert DriftView(2).test(value) == f'data-test="{value}"'


class TestIntentionalBugs:
    """The planted-bug helpers of the registry view (task 3.1)."""

    def test_the_registry_is_ordered_and_complete(self):
        assert BUG_FLAGS == (
            "BUG_MISSING_BUTTON",
            "BUG_WRONG_PRICE",
            "BUG_BROKEN_LINKS",
            "BUG_SLOW_RESPONSE",
            "BUG_CHECKOUT_TOTAL",
        )
        assert all(bug.flow and bug.trigger and bug.defect and bug.scope for bug in PLANTED_BUGS)

    def test_wrong_price_raises_the_card_price_of_every_third_product(self):
        bugs = bugs_with("BUG_WRONG_PRICE")
        assert bugs.card_price(product(3, 100.0)) == 115.0
        assert bugs.card_price(product(6, 189.0)) == 217.35
        assert bugs.card_price(product(1, 100.0)) == 100.0
        assert bugs.card_price(product(7, 100.0)) == 100.0

    def test_broken_links_point_at_a_page_that_does_not_exist(self):
        bugs = bugs_with("BUG_BROKEN_LINKS")
        assert bugs.card_href(product(4)) == "/products/invalid-4"
        assert bugs.card_href(product(8)) == "/products/invalid-8"
        assert bugs.card_href(product(1)) == "/products/1"

    def test_missing_button_hides_every_fifth_card_action(self):
        bugs = bugs_with("BUG_MISSING_BUTTON")
        assert bugs.hides_add_to_cart(product(5)) is True
        assert bugs.hides_add_to_cart(product(10)) is True
        assert bugs.hides_add_to_cart(product(4)) is False
        assert bugs.hides_add_to_cart(product(1)) is False

    def test_checkout_total_replaces_only_the_total(self):
        """Subtotal and tax stay correct, which is what makes it detectable."""
        summary = {"subtotal": 100.0, "tax": 7.0, "total": 107.0}
        shown = bugs_with("BUG_CHECKOUT_TOTAL").checkout_total(summary)

        assert shown == {"subtotal": 100.0, "tax": 7.0, "total": 100.0}
        assert summary["total"] == 107.0, "the caller's summary is not mutated"

    def test_every_helper_is_a_no_op_with_its_flag_off(self):
        bugs = BugView.from_flags({})
        assert bugs.card_price(product(3, 100.0)) == 100.0
        assert bugs.card_href(product(4)) == "/products/4"
        assert bugs.hides_add_to_cart(product(5)) is False
        assert bugs.checkout_total({"subtotal": 100.0, "tax": 7.0, "total": 107.0}) == {
            "subtotal": 100.0,
            "tax": 7.0,
            "total": 107.0,
        }

    @pytest.mark.parametrize("stage", STAGES)
    def test_the_helpers_answer_the_same_in_every_stage(self, stage):
        """Triggers read the product and the cart, never the locator flags."""
        flags = {flag: True for flag in BUG_FLAGS}
        if stage > 1:
            flags[f"LOCATOR_V{stage}"] = True
        bugs = BugView.from_flags(flags)

        assert bugs.card_price(product(3, 100.0)) == 115.0
        assert bugs.card_href(product(4)) == "/products/invalid-4"
        assert bugs.hides_add_to_cart(product(5)) is True
        assert bugs.hides_add_to_cart(product(4)) is False
        assert bugs.checkout_total({"subtotal": 100.0, "tax": 7.0, "total": 107.0})["total"] == 100.0

    def test_an_unregistered_flag_raises(self):
        with pytest.raises(UnknownHook):
            bugs_with().is_active("BUG_NOT_PLANTED")


class TestPresets:
    """``build_presets``: absolute for the groups it owns (task 3.3)."""

    def test_stage_one_is_the_absence_of_locator_flags(self):
        presets = build_presets()
        assert presets["stage1"] == {flag: False for flag in LOCATOR_FLAGS}
        assert effective_stage(presets["stage1"]) == 1

    @pytest.mark.parametrize("stage", DRIFTING_STAGES)
    def test_a_stage_preset_selects_exactly_its_own_flag(self, stage):
        preset = build_presets()[f"stage{stage}"]
        assert set(preset) == set(LOCATOR_FLAGS)
        assert [flag for flag, value in preset.items() if value] == [f"LOCATOR_V{stage}"]
        assert effective_stage(preset) == stage

    @pytest.mark.parametrize("stage", STAGES)
    def test_stage_presets_own_the_locator_flags_only(self, stage):
        """They must leave the planted bugs alone, so presets compose."""
        preset = build_presets()[f"stage{stage}"]
        assert not set(preset) & set(BUG_FLAGS)

    def test_buggy_enables_every_registered_bug_and_no_locator_flag(self):
        preset = build_presets()["buggy"]
        assert preset == {flag: True for flag in BUG_FLAGS}
        assert not set(preset) & set(LOCATOR_FLAGS)

    def test_clean_clears_every_locator_and_bug_flag(self):
        preset = build_presets()["clean"]
        assert all(preset[flag] is False for flag in LOCATOR_FLAGS)
        assert all(preset[flag] is False for flag in BUG_FLAGS)
        assert preset["AI_DETERMINISTIC"] is True
        assert all(preset[flag] is False for flag in AI_FLAGS if flag != "AI_DETERMINISTIC")

    def test_drift_and_bug_is_stage_four_with_two_bugs(self):
        preset = build_presets()["drift_and_bug"]
        assert effective_stage(preset) == 4
        assert [flag for flag in LOCATOR_FLAGS if preset[flag]] == ["LOCATOR_V4"]
        assert [flag for flag in BUG_FLAGS if preset[flag]] == [
            "BUG_WRONG_PRICE",
            "BUG_CHECKOUT_TOTAL",
        ]
        assert set(preset) == set(LOCATOR_FLAGS) | set(BUG_FLAGS)

    def test_ai_chaos_is_unchanged(self):
        assert build_presets()["ai_chaos"] == {
            "AI_DETERMINISTIC": False,
            "AI_RANDOM_DELAYS": True,
            "AI_VARIED_RESPONSES": True,
        }

    def test_the_presets_are_fresh_dicts(self):
        """A caller may not edit the next caller's preset."""
        first = build_presets()
        first["clean"]["LOCATOR_V2"] = True
        assert build_presets()["clean"]["LOCATOR_V2"] is False


class TestSpaceBaseline:
    """``baseline_flags()`` reads this change's registries (task 15.1).

    The baseline is what a workshop space that has set nothing sees, so a flag
    this change adds - ``BUG_CHECKOUT_TOTAL``, say - has to be in it without a
    second edit in ``core/feature_flags.py``. The function builds it from the
    seeded rows of ``seeds/seed_data.py`` (whose bug rows are generated from
    :data:`PLANTED_BUGS`) with ``build_presets()["clean"]`` applied on top.
    """

    def test_the_baseline_carries_the_clean_preset(self):
        baseline = baseline_flags()
        clean = build_presets()["clean"]

        missing = sorted(key for key in clean if key not in baseline)
        assert not missing, missing
        assert {key: baseline[key] for key in clean} == clean

    def test_every_planted_bug_is_in_the_baseline_and_off(self):
        baseline = baseline_flags()

        assert {bug.flag: baseline.get(bug.flag) for bug in PLANTED_BUGS} == {
            bug.flag: False for bug in PLANTED_BUGS
        }

    def test_the_baseline_is_a_fresh_dict(self):
        """A caller may not edit the next caller's baseline."""
        baseline_flags()["LOCATOR_V4"] = True

        assert baseline_flags()["LOCATOR_V4"] is False


class TestAIResponseVariations:
    """Tests for AI response template variations."""

    def test_ai_response_template_no_variation(self):
        """Returns first template when variation disabled."""
        flags = {}
        template = get_ai_response_template(flags, 0)
        assert "recommend" in template.lower()

    def test_ai_response_template_with_variation(self):
        """Cycles through templates when variation enabled."""
        flags = {"AI_VARIED_RESPONSES": True}
        templates = [get_ai_response_template(flags, i) for i in range(5)]
        # Should get different templates
        unique_templates = set(templates)
        assert len(unique_templates) >= 3
