"""Invoice arithmetic for the worker checkout acceptance fixture."""

from decimal import Decimal


def invoice_total(items):
    """Return the exact total for (unit price, quantity) invoice lines."""
    return sum((Decimal(price) for price, quantity in items), Decimal("0.00"))
