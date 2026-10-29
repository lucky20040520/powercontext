# 接口契约 v2.0 —— 订单折扣服务（discount-service）

- 状态：**当前有效（active）**
- 生效时间：2026-10-28
- 演进说明：替代 v1.0。接口更名为“价格计算”，函数与端点全部重构。

## 对外接口

### 函数 `compute_price(amount: float, code: str | None) -> float`

- `amount`：订单金额（元，正数；非正数返回 0.0）
- `code`：折扣码（可选，None 表示未使用折扣码）
- 返回：最终价格（元，两位小数）
- **替代**：旧函数 `compute_discount` 已移除，任何调用者必须迁移。

### HTTP 端点 `GET /price?amount=250&code=SAVE10`

- 响应 `{"amount": 250, "price": 198.0}`
- **替代**：旧端点 `GET /discount` 已移除。

## 边界约定

- `amount <= 0` 返回 0.0。
- 未知折扣码视为未使用折扣码。
- 旧符号 `compute_discount` 与 `/discount` 不再被支持。
