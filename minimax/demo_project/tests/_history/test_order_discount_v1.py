# -*- coding: utf-8 -*-
"""test_order_discount_v1.py —— v1 测试历史（引用已移除的旧接口）。

保留历史快照仅用于对照；当前测试以 tests/test_order_discount.py 为准。
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src", "_history"))

from order_discount_v1 import compute_discount  # noqa: E402


class TestComputeDiscount(unittest.TestCase):
    """针对契约 v1.0 接口 compute_discount 的验证（v2.0 起已失效）。"""

    def test_at_threshold(self):
        self.assertEqual(compute_discount(100.0), 90.0)

    def test_below_threshold(self):
        self.assertEqual(compute_discount(99.0), 99.0)

    def test_threshold_plus_coupon(self):
        self.assertEqual(compute_discount(100.0, "SAVE10"), 81.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
