from backend.app.services.order_service import calculate_totals


def test_calculate_totals_rounding():
    items = [{"total_price": 19.99}, {"total_price": 5.01}]
    subtotal, tax, total = calculate_totals(items, tax_rate=0.05)
    assert subtotal == 25.0
    assert tax == 1.25
    assert total == 26.25
