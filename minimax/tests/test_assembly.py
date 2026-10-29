# -*- coding: utf-8 -*-
"""任务上下文组装器单元测试。

覆盖题目核心问题：“AI 开发助手根据开发任务，应当拿到什么上下文？”
—— 只提供当前有效规格、相关代码、相关测试，并附带失效决策与过期验证警示。
"""

import unittest

from sdd_context import (
    ContextAssembler,
    SpecKind,
    SpecRegistry,
    ValidityEngine,
)


def _mk_context() -> tuple:
    reg = SpecRegistry()
    src = "/repo/src/order.py"
    test = "/repo/tests/test_order.py"
    reg.register_spec(
        "order-requirements", "1.0.0", SpecKind.REQUIREMENT,
        "订单满 100 减 10，支持折扣码",
        linked_files=[src],
    )
    reg.register_spec(
        "order-contract", "1.0.0", SpecKind.CONTRACT,
        "接口契约：计算订单折扣后金额\n"
        "### 函数 `compute_discount(amount: float) -> float`\n"
        "端点 GET /discount",
        linked_files=[src], linked_tests=[test],
    )
    reg.record_code(src, "hash-v1")
    reg.register_test(test, spec_ref="order-contract",
                      covered_files=[src], last_status="passed")
    reg.register_decision("DEC-1", "规则表驱动", "order-service")
    return reg, src, test


class TestContextAssembler(unittest.TestCase):
    def setUp(self):
        self.reg, self.src, self.test = _mk_context()
        self.engine = ValidityEngine(self.reg)
        self.assembler = ContextAssembler(self.reg, self.engine)

    def test_assemble_active_specs_only(self):
        ctx = self.assembler.assemble(
            "实现订单折扣", current_hashes={self.src: "hash-v1"},
        )
        ids = {s.id for s in ctx.active_specs}
        self.assertEqual(ids, {"order-requirements", "order-contract"})
        # 相关代码与测试被带上
        self.assertIn(self.src, ctx.relevant_code)
        self.assertEqual(len(ctx.relevant_tests), 1)
        self.assertEqual(ctx.stale_tests, [])
        self.assertEqual(ctx.invalid_tests, [])

    def test_irrelevant_task_gets_no_spec(self):
        ctx = self.assembler.assemble(
            "修复登录页面的按钮样式", current_hashes={self.src: "hash-v1"},
        )
        self.assertEqual(ctx.active_specs, [])
        self.assertTrue(ctx.warnings)

    def test_retired_decisions_flagged(self):
        # 需求升级 → 决策失效 → 任务上下文中应出现失效决策警示
        self.reg.register_spec(
            "order-requirements", "2.0.0", SpecKind.REQUIREMENT,
            "订单满 200 减 30，阶梯折扣",
            linked_files=[self.src],
        )
        self.reg.cascade_invalidate_decisions("order-service")
        self.reg.register_decision("DEC-2", "阶梯档位表", "order-service")

        ctx = self.assembler.assemble(
            "新增阶梯折扣", current_hashes={self.src: "hash-v1"},
        )
        self.assertEqual({d.id for d in ctx.retired_decisions}, {"DEC-1"})
        self.assertTrue(any("DEC-1" in w for w in ctx.warnings))

    def test_render_prompt_contains_key_sections(self):
        ctx = self.assembler.assemble(
            "实现订单折扣", current_hashes={self.src: "hash-v1"},
        )
        prompt = self.assembler.render_prompt(ctx)
        for expected in ("当前必须遵守的规格", "相关代码", "可采信的验证"):
            self.assertIn(expected, prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
