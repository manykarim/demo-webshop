from backend.app.services.order_service import calculate_totals, checkout_summary


def test_calculate_totals_rounding():
    items = [{"total_price": 19.99}, {"total_price": 5.01}]
    subtotal, tax, total = calculate_totals(items, tax_rate=0.05)
    assert subtotal == 25.0
    assert tax == 1.25
    assert total == 26.25


def test_checkout_summary_uses_the_same_rate_as_the_order():
    """The page's amounts are the order's amounts (drift-coverage task 10.1)."""
    cart_state = {"items": [{"total_price": 39.50}, {"total_price": 39.50}]}

    assert checkout_summary(cart_state) == {
        "subtotal": 79.00,
        "tax": 5.53,
        "total": 84.53,
    }


def test_checkout_summary_of_an_empty_cart_is_zero():
    assert checkout_summary({"items": []}) == {"subtotal": 0.0, "tax": 0.0, "total": 0.0}
