# -*- coding: utf-8 -*-
"""test_order_discount.py —— 契约 v2.0 测试。"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from order_discount import compute_price  # noqa: E402


class TestComputePrice(unittest.TestCase):
    def test_below_threshold_no_discount(self):
        self.assertEqual(compute_price(150.0), 150.0)

    def test_first_tier(self):
        self.assertEqual(compute_price(250.0), 220.0)

    def test_second_tier(self):
        self.assertEqual(compute_price(300.0), 250.0)

    def test_tier_plus_coupon(self):
        self.assertEqual(compute_price(250.0, "SAVE10"), 198.0)

    def test_non_positive_amount(self):
        self.assertEqual(compute_price(-10.0), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
