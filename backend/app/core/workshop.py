"""Workshop utilities for self-healing locator testing and intentional bugs."""
from __future__ import annotations

import asyncio
import random
from typing import Dict, Any

# Locator variation stages - maps flag to element transformations
LOCATOR_STAGES = {
    "LOCATOR_V2": {
        "product-card": "item-card",
        "product-card__title": "item-title",
        "product-card__price": "item-cost",
        "product-card__cta": "item-actions",
        "add_to_cart": "add-item",
        "site-nav__link": "nav-item",
        "cart-count": "basket-badge",
        "button--primary": "btn-main",
    },
    "LOCATOR_V3": {
        # Remove data-test attributes entirely in templates
        "remove_data_test": True,
    },
    "LOCATOR_V4": {
        # Wrap elements in extra divs
        "wrap_products": True,
        "product-card": "product-tile",
        "product-card__body": "tile-content",
        "product-card__footer": "tile-actions",
    },
}

# ID transformations per stage
ID_TRANSFORMS = {
    "LOCATOR_V2": {
        "auth-email": "login-email",
        "auth-password": "login-pass",
        "chat-input": "ai-question",
        "primary-nav-menu": "main-nav",
        "main-content": "page-body",
    },
    "LOCATOR_V3": {
        "auth-email": "email-field",
        "auth-password": "password-field",
        "chat-input": "question-box",
    },
    "LOCATOR_V4": {
        "auth-email": "frm-email",
        "auth-password": "frm-pwd",
        "chat-input": "q-input",
        "main-content": "content-area",
    },
}


def get_class_name(base_class: str, flags: Dict[str, bool]) -> str:
    """Get the appropriate class name based on active locator flags."""
    for stage in ["LOCATOR_V4", "LOCATOR_V3", "LOCATOR_V2"]:
        if flags.get(stage):
            transforms = LOCATOR_STAGES.get(stage, {})
            if base_class in transforms:
                return transforms[base_class]
    return base_class


def get_element_id(base_id: str, flags: Dict[str, bool]) -> str:
    """Get the appropriate element ID based on active locator flags."""
    for stage in ["LOCATOR_V4", "LOCATOR_V3", "LOCATOR_V2"]:
        if flags.get(stage):
            transforms = ID_TRANSFORMS.get(stage, {})
            if base_id in transforms:
                return transforms[base_id]
    return base_id


def should_remove_data_test(flags: Dict[str, bool]) -> bool:
    """Check if data-test attributes should be removed."""
    return flags.get("LOCATOR_V3", False) or flags.get("LOCATOR_V4", False)


def get_data_test_attr(value: str, flags: Dict[str, bool]) -> str:
    """Get data-test attribute or empty string if disabled."""
    if should_remove_data_test(flags):
        return ""
    return f'data-test="{value}"'


def apply_bug_missing_button(flags: Dict[str, bool], product_id: int) -> bool:
    """Determine if button should be hidden for this product."""
    if not flags.get("BUG_MISSING_BUTTON"):
        return False
    # Hide button for ~20% of products (deterministic based on product_id)
    return (product_id % 5) == 0


def apply_bug_wrong_price(flags: Dict[str, bool], price: float, product_id: int) -> float:
    """Return potentially incorrect price if bug is enabled."""
    if not flags.get("BUG_WRONG_PRICE"):
        return price
    # Randomly modify price for some products
    if (product_id % 3) == 0:
        return round(price * 1.15, 2)  # 15% higher
    return price


def apply_bug_broken_link(flags: Dict[str, bool], url: str, product_id: int) -> str:
    """Return potentially broken link if bug is enabled."""
    if not flags.get("BUG_BROKEN_LINKS"):
        return url
    # Break links for ~25% of products
    if (product_id % 4) == 0:
        return f"/products/invalid-{product_id}"
    return url


async def apply_bug_slow_response(flags: Dict[str, bool]) -> None:
    """Add artificial delay if slow response bug is enabled."""
    if flags.get("BUG_SLOW_RESPONSE"):
        delay = random.uniform(1.0, 3.0)
        await asyncio.sleep(delay)


# AI Response variation utilities
AI_RESPONSE_VARIATIONS = [
    "Based on your query, I recommend checking out our {product}.",
    "Great question! The {product} might be exactly what you're looking for.",
    "I'd suggest taking a look at the {product} - it's quite popular!",
    "For your needs, the {product} could be a perfect fit.",
    "Have you considered the {product}? It has excellent reviews.",
]


def get_ai_response_template(flags: Dict[str, bool], index: int = 0) -> str:
    """Get AI response template based on variation settings."""
    if flags.get("AI_VARIED_RESPONSES"):
        # Use different template based on index
        return AI_RESPONSE_VARIATIONS[index % len(AI_RESPONSE_VARIATIONS)]
    return AI_RESPONSE_VARIATIONS[0]


async def apply_ai_random_delay(flags: Dict[str, bool]) -> None:
    """Add random delay to AI responses if enabled."""
    if flags.get("AI_RANDOM_DELAYS"):
        delay = random.uniform(0.5, 2.0)
        await asyncio.sleep(delay)
