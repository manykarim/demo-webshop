"""Unit tests for workshop features - locator variations, bugs, and AI variations."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.core.workshop import (
    get_class_name,
    get_element_id,
    should_remove_data_test,
    get_data_test_attr,
    apply_bug_missing_button,
    apply_bug_wrong_price,
    apply_bug_broken_link,
    get_ai_response_template,
    LOCATOR_STAGES,
    ID_TRANSFORMS,
)


class TestLocatorVariations:
    """Tests for CSS class and ID transformations."""

    def test_get_class_name_no_flags(self):
        """Returns original class when no flags set."""
        flags = {}
        assert get_class_name("product-card", flags) == "product-card"

    def test_get_class_name_v2(self):
        """V2 transforms product-card to item-card."""
        flags = {"LOCATOR_V2": True}
        assert get_class_name("product-card", flags) == "item-card"
        assert get_class_name("product-card__title", flags) == "item-title"
        assert get_class_name("button--primary", flags) == "btn-main"

    def test_get_class_name_v4_takes_precedence(self):
        """V4 takes precedence over V2 when both set."""
        flags = {"LOCATOR_V2": True, "LOCATOR_V4": True}
        assert get_class_name("product-card", flags) == "product-tile"

    def test_get_class_name_unknown_class(self):
        """Returns original for unknown classes."""
        flags = {"LOCATOR_V2": True}
        assert get_class_name("unknown-class", flags) == "unknown-class"

    def test_get_element_id_no_flags(self):
        """Returns original ID when no flags set."""
        flags = {}
        assert get_element_id("auth-email", flags) == "auth-email"

    def test_get_element_id_v2(self):
        """V2 transforms auth-email to login-email."""
        flags = {"LOCATOR_V2": True}
        assert get_element_id("auth-email", flags) == "login-email"
        assert get_element_id("chat-input", flags) == "ai-question"

    def test_get_element_id_v3(self):
        """V3 has different ID mappings."""
        flags = {"LOCATOR_V3": True}
        assert get_element_id("auth-email", flags) == "email-field"

    def test_get_element_id_v4_precedence(self):
        """V4 takes precedence when multiple flags set."""
        flags = {"LOCATOR_V2": True, "LOCATOR_V3": True, "LOCATOR_V4": True}
        assert get_element_id("auth-email", flags) == "frm-email"


class TestDataTestAttributes:
    """Tests for data-test attribute handling."""

    def test_should_remove_data_test_no_flags(self):
        """data-test should NOT be removed when no flags."""
        flags = {}
        assert should_remove_data_test(flags) is False

    def test_should_remove_data_test_v2(self):
        """V2 does NOT remove data-test."""
        flags = {"LOCATOR_V2": True}
        assert should_remove_data_test(flags) is False

    def test_should_remove_data_test_v3(self):
        """V3 DOES remove data-test."""
        flags = {"LOCATOR_V3": True}
        assert should_remove_data_test(flags) is True

    def test_should_remove_data_test_v4(self):
        """V4 DOES remove data-test."""
        flags = {"LOCATOR_V4": True}
        assert should_remove_data_test(flags) is True

    def test_get_data_test_attr_enabled(self):
        """Returns attribute string when not removed."""
        flags = {}
        result = get_data_test_attr("product-card", flags)
        assert result == 'data-test="product-card"'

    def test_get_data_test_attr_disabled(self):
        """Returns empty string when removed."""
        flags = {"LOCATOR_V3": True}
        result = get_data_test_attr("product-card", flags)
        assert result == ""


class TestIntentionalBugs:
    """Tests for intentional bug features."""

    def test_bug_missing_button_disabled(self):
        """No buttons hidden when flag disabled."""
        flags = {}
        assert apply_bug_missing_button(flags, 5) is False
        assert apply_bug_missing_button(flags, 10) is False

    def test_bug_missing_button_enabled(self):
        """Hides buttons for products where id % 5 == 0."""
        flags = {"BUG_MISSING_BUTTON": True}
        assert apply_bug_missing_button(flags, 5) is True
        assert apply_bug_missing_button(flags, 10) is True
        assert apply_bug_missing_button(flags, 1) is False
        assert apply_bug_missing_button(flags, 7) is False

    def test_bug_wrong_price_disabled(self):
        """Returns original price when flag disabled."""
        flags = {}
        assert apply_bug_wrong_price(flags, 100.0, 3) == 100.0

    def test_bug_wrong_price_enabled(self):
        """Modifies price for products where id % 3 == 0."""
        flags = {"BUG_WRONG_PRICE": True}
        # id=3: should be modified (15% higher)
        assert apply_bug_wrong_price(flags, 100.0, 3) == 115.0
        # id=6: should be modified
        assert apply_bug_wrong_price(flags, 100.0, 6) == 115.0
        # id=1: should NOT be modified
        assert apply_bug_wrong_price(flags, 100.0, 1) == 100.0
        # id=7: should NOT be modified
        assert apply_bug_wrong_price(flags, 100.0, 7) == 100.0

    def test_bug_broken_link_disabled(self):
        """Returns original URL when flag disabled."""
        flags = {}
        url = "/products/4"
        assert apply_bug_broken_link(flags, url, 4) == url

    def test_bug_broken_link_enabled(self):
        """Breaks links for products where id % 4 == 0."""
        flags = {"BUG_BROKEN_LINKS": True}
        # id=4: should be broken
        assert apply_bug_broken_link(flags, "/products/4", 4) == "/products/invalid-4"
        # id=8: should be broken
        assert apply_bug_broken_link(flags, "/products/8", 8) == "/products/invalid-8"
        # id=1: should NOT be broken
        assert apply_bug_broken_link(flags, "/products/1", 1) == "/products/1"


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
