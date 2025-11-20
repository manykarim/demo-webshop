from __future__ import annotations


def format_currency(value: float | int | None) -> str:
    """Format numeric values as USD currency with thousands separators."""
    if value is None:
        return "$0.00"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "$0.00"
    return f"${amount:,.2f}"
