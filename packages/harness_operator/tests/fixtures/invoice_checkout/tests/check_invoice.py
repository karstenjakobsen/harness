import unittest
from decimal import Decimal

from invoice import invoice_total


class InvoiceTotalTest(unittest.TestCase):
    def test_quantities_are_included_without_losing_decimal_precision(self):
        self.assertEqual(
            invoice_total([("0.10", 3), ("2.35", 2), ("9.99", 0)]),
            Decimal("5.00"),
        )


if __name__ == "__main__":
    unittest.main()
