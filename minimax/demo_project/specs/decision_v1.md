# 设计决策记录 —— 订单折扣服务（discount-service）

## DEC-001：折扣规则使用规则表驱动，不引入数据库

- 状态：**已失效（superseded，由 DEC-102 替代）**
- 关联规格：discount-service
- 决策内容：折扣门槛与折扣码映射用 Python 常量表维护，首版不引入数据库，
  便于快速上线与单元测试。

## DEC-002：金额运算统一使用 Decimal 或 round 两位小数

- 状态：**已失效（superseded，由 DEC-102 替代）**
- 关联规格：discount-service
- 决策内容：折扣计算后统一 `round(x, 2)`，避免浮点误差扩散到订单金额。
