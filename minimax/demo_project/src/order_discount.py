# -*- coding: utf-8 -*-
"""order_discount.py —— 订单折扣服务（discount-service）当前实现。

当前版本：v2.0（随需求规格 v2.0 / 契约 v2.0 演进）
"""

# 折扣档位表：[(门槛金额, 减免额)]，按最高满足档生效
THRESHOLD_TIERS = [
    (200, 30),
    (300, 50),
]

COUPON_RATES = {
    "SAVE10": 0.9,
}


def compute_price(amount: float, code: str | None = None) -> float:
    """计算订单最终价格（契约 v2.0 对外接口）。"""
    if amount <= 0:
        return 0.0
    price = amount
    tier_discount = 0.0
    for threshold, cut in THRESHOLD_TIERS:
        if price >= threshold:
            tier_discount = cut
    price -= tier_discount
    price *= COUPON_RATES.get(code, 1.0)
    return round(price, 2)
