# -*- coding: utf-8 -*-
"""order_discount_v1.py —— v1.1 历史实现（随 v2.0 契约被淘汰）。

保留历史快照仅用于对照；当前实现以 src/order_discount.py 为准。
"""

THRESHOLD = 100.0
DISCOUNT = 10.0
COUPON_RATES = {"SAVE10": 0.9}


def compute_discount(amount: float, code: str | None = None) -> float:
    """v1 契约接口：compute_discount（v2.0 起已移除）。"""
    if amount <= 0:
        return 0.0  # v1.1 新增的负金额防御
    price = amount
    if price >= THRESHOLD:
        price -= DISCOUNT
    price *= COUPON_RATES.get(code, 1.0)
    return round(price, 2)
