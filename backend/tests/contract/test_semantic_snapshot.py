"""The semantic snapshot, on hand-written fixtures (drift-coverage task 4.2).

The snapshot is the whole stage contract in one function, so it is tested on
markup written here rather than on a rendered page: every way a stage is allowed
to change the markup must leave it alone, and every way the contract forbids
must change it.
"""
from __future__ import annotations

import pytest

from .semantic import ORDER_RESULT_MASK, snapshot

#: A page in miniature: navigation, a dialog with a labelled field, a product
#: card with content data attributes, and a stylesheet link.
STAGE_1 = """<!DOCTYPE html>
<html lang="en">
<head>
  <title>Flowline Supply</title>
  <link rel="stylesheet" href="/assets/styles.aaa.css" />
</head>
<body>
  <nav aria-label="Primary navigation">
    <a class="site-nav__link site-nav__link--cart" href="/cart">Cart
      <span class="badge" data-test="cart-count" aria-live="polite">2</span></a>
  </nav>
  <main id="main-content">
    <div class="auth-modal" id="auth-modal" role="dialog" aria-labelledby="auth-modal-title">
      <h2 class="auth-modal__title" id="auth-modal-title">Sign in</h2>
      <form class="auth-modal__form" action="/api/auth/login" method="post">
        <label class="form-field" for="auth-email"><span>Email</span></label>
        <input id="auth-email" name="email" type="email" data-test="auth-email-input" />
        <button class="button button--primary" type="submit" data-test="auth-submit">Sign in</button>
      </form>
    </div>
    <form class="hero__search" role="search" action="/search" method="get">
      <label class="form-field"><span>Search</span>
        <input name="query" type="search" data-test="search-input" />
      </label>
      <button class="button" type="submit" data-test="search-submit">Search</button>
    </form>
    <article class="product-card" data-test="product-card">
      <h3 class="product-card__title">
        <a href="/products/3" data-test="product-link">Pulse Bio Ring</a></h3>
      <span class="category-badge" data-category="wearables">Wearables</span>
      <button class="product-card__add" data-product="3" data-product-name="Pulse Bio Ring"
        data-test="add-to-cart-btn" aria-label="Add Pulse Bio Ring to cart">Add to cart</button>
    </article>
  </main>
  <script>document.title = "never part of a snapshot";</script>
  <template id="search-suggestions-template">
    <li class="suggestion"><a href="/products/99">Never rendered</a></li>
  </template>
</body>
</html>
"""


def _replaced(*pairs: tuple[str, str]) -> str:
    """``STAGE_1`` with each ``(old, new)`` pair applied in order."""
    html = STAGE_1
    for old, new in pairs:
        assert old in html, f"the fixture does not contain {old!r}"
        html = html.replace(old, new)
    return html


# ---------------------------------------------------------------------------
# What a stage may change
# ---------------------------------------------------------------------------


def test_the_fixture_produces_a_snapshot() -> None:
    """A guard: an empty snapshot would make every equality below vacuous."""
    entries = snapshot(STAGE_1)

    assert ("text", "Add to cart") in entries
    assert any("href=/products/3" in entry for entry in entries)
    # `script` and `template` content is invisible and therefore absent.
    assert not any("never part of a snapshot" in part for entry in entries for part in entry)
    assert not any("Never rendered" in part for entry in entries for part in entry)


def test_renaming_ids_and_their_references_changes_nothing() -> None:
    """Stage 2 and 4 rename ids; ``for`` and ``aria-*`` follow them."""
    stage_2 = _replaced(
        ('id="auth-modal"', 'id="signin-overlay"'),
        ('id="auth-modal-title"', 'id="signin-heading"'),
        ('aria-labelledby="auth-modal-title"', 'aria-labelledby="signin-heading"'),
        ('id="auth-email"', 'id="login-email"'),
        ('for="auth-email"', 'for="login-email"'),
        ('id="main-content"', 'id="page-body"'),
    )

    assert snapshot(stage_2) == snapshot(STAGE_1)


def test_renaming_classes_changes_nothing() -> None:
    """Stage 2 and 4 rename class names, including the derived BEM names."""
    stage_2 = _replaced(
        ("product-card__title", "item-title"),
        ("product-card__add", "btn-main"),
        ('class="hero__search"', 'class="banner-search"'),
        ('class="product-card"', 'class="item-card"'),
        ("auth-modal__", "signin-modal__"),
        ('class="auth-modal"', 'class="signin-modal"'),
        ("site-nav__", "main-nav__"),
        ('class="badge"', 'class="count-bubble"'),
    )

    assert snapshot(stage_2) == snapshot(STAGE_1)


def test_removing_and_renaming_data_test_changes_nothing() -> None:
    """Stage 3 drops every test hook; stage 2 could rename them."""
    renamed = _replaced(('data-test="product-card"', 'data-test="tile"'))
    removed = STAGE_1
    hooks = (
        "cart-count",
        "auth-email-input",
        "auth-submit",
        "search-input",
        "search-submit",
        "product-card",
        "product-link",
        "add-to-cart-btn",
    )
    for hook in hooks:
        removed = removed.replace(f' data-test="{hook}"', "")

    assert snapshot(renamed) == snapshot(STAGE_1)
    assert snapshot(removed) == snapshot(STAGE_1)


def test_role_less_wrappers_change_nothing() -> None:
    """Stage 4 nests content in role-less ``div`` and ``span`` wrappers."""
    stage_4 = _replaced(
        ('<article class="product-card"', '<div class="product-tile__wrapper"><article class="product-card"'),
        ("</article>", "</article></div>"),
        (">Add to cart</button>", "><span>Add to cart</span></button>"),
    )

    assert snapshot(stage_4) == snapshot(STAGE_1)


def test_a_different_stylesheet_changes_nothing() -> None:
    """The stylesheet href follows the drift (Decision 5) and is not content."""
    other_build = _replaced(("/assets/styles.aaa.css", "/assets/styles.bbb.css"))

    assert snapshot(other_build) == snapshot(STAGE_1)


# ---------------------------------------------------------------------------
# What no stage may change
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("description", "pairs"),
    [
        ("visible text", ((">Add to cart</button>", ">Add to basket</button>"),)),
        (
            "an accessible name",
            (('aria-label="Add Pulse Bio Ring to cart"', 'aria-label="Add this item"'),),
        ),
        ("a label association", (('for="auth-email"', 'for="somewhere-else"'),)),
        ("a field name", (('name="email"', 'name="user_email"'),)),
        ("a wrapping label's text", ((">Search</span>", ">Find</span>"),)),
        ("a hyperlink target", (('href="/products/3"', 'href="/products/4"'),)),
        ("a form action", (('action="/api/auth/login"', 'action="/api/auth/signin"'),)),
        ("a content data attribute", (('data-product-name="Pulse Bio Ring"', 'data-product-name="Ring"'),)),
        (
            "the content order",
            (
                (
                    '<span class="category-badge" data-category="wearables">Wearables</span>',
                    "",
                ),
                (
                    '<h3 class="product-card__title">',
                    (
                        '<span class="category-badge" data-category="wearables">Wearables</span>'
                        '<h3 class="product-card__title">'
                    ),
                ),
            ),
        ),
    ],
)
def test_changing_semantics_changes_the_snapshot(description: str, pairs) -> None:
    """Each of these is forbidden by the stage contract and must be visible."""
    changed = _replaced(*pairs)

    assert snapshot(changed) != snapshot(STAGE_1), description


# ---------------------------------------------------------------------------
# The order-result mask
# ---------------------------------------------------------------------------

SUCCESS_ALERT = """<div class="checkout-alert is-success" id="checkout-alert" role="status"
  data-test="checkout-result">
  <p>Thank you! Order {number} is confirmed. A copy is on the way to {email}.</p>
  <a href="/api/docs/orders/{order_id}/invoice.pdf">Download invoice (PDF)</a>
  <a href="/api/docs/orders/{order_id}/summary.pdf">Download summary (PDF)</a>
</div>
"""

FIRST_ORDER = SUCCESS_ALERT.format(
    number="ORD-1A2B3C4D", order_id=17, email="jamie@flowlinesupply.com"
)
SECOND_ORDER = SUCCESS_ALERT.format(
    number="ORD-9F8E7D6C", order_id=42, email="jamie@flowlinesupply.com"
)


def test_two_orders_differ_without_the_mask() -> None:
    """The order number and the document ids really are in the snapshot."""
    assert snapshot(FIRST_ORDER) != snapshot(SECOND_ORDER)


def test_two_orders_are_equal_with_the_mask() -> None:
    """With the mask, only what is unique per order is normalized away."""
    assert snapshot(FIRST_ORDER, ORDER_RESULT_MASK) == snapshot(SECOND_ORDER, ORDER_RESULT_MASK)


@pytest.mark.parametrize(
    ("description", "changed"),
    [
        (
            "the link text",
            FIRST_ORDER.replace("Download invoice (PDF)", "Get invoice (PDF)"),
        ),
        ("the path shape", FIRST_ORDER.replace("invoice.pdf", "receipt.pdf")),
        (
            "the customer email",
            SUCCESS_ALERT.format(number="ORD-1A2B3C4D", order_id=17, email="someone@example.com"),
        ),
        (
            "the message wording",
            FIRST_ORDER.replace("Thank you! Order", "Order"),
        ),
    ],
)
def test_the_mask_hides_only_the_order_identity(description: str, changed: str) -> None:
    """The mask must not swallow a broken link, a wrong address or new wording."""
    assert snapshot(changed, ORDER_RESULT_MASK) != snapshot(FIRST_ORDER, ORDER_RESULT_MASK), (
        description
    )
