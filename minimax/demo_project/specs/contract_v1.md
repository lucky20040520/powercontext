# 接口契约 v1.0 —— 订单折扣服务（discount-service）

- 状态：**已替代（superseded by discount-service@2.0.0）**
- 生效时间：2026-10-20

## 对外接口

### 函数 `compute_discount(amount: float, code: str | None) -> float`

- `amount`：订单金额（元，正数）
- `code`：折扣码（可选，None 表示未使用折扣码）
- 返回：折扣后金额（元，两位小数）

### HTTP 端点 `GET /discount?amount=100&code=SAVE10`

- 响应 `{"amount": 100, "discount": 81.0}`
- 行为与 `compute_discount` 一致

## 边界约定

- `amount <= 0` 视为非法输入，行为未定义（v1.1 起返回 0.0）。
- 未知折扣码视为未使用折扣码。
