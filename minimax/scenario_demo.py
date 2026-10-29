# -*- coding: utf-8 -*-
"""
scenario_demo.py —— 端到端场景演示
===================================
通过“实际代码修改”验证工程上下文模块的效果。

演示一个订单折扣服务（discount-service）在持续维护中的完整演进：

  阶段 0  登记 v1.0 规格（需求 / 契约 / 决策）与代码、测试
  阶段 1  新会话：任务“实现订单折扣” → 组装当前有效上下文
  阶段 2  实际修改代码（v1.0 → v1.1 增加负金额防御）→ 验证判定为 stale
  阶段 3  需求升级（v1.0 → v2.0：满 200 减 30、阶梯折扣）→ 旧决策级联失效
  阶段 4  契约变更（compute_discount→compute_price，/discount→/price）
          → 旧测试 invalid、新测试 valid；任务上下文只含 v2 规格
  阶段 5  跨会话交接：导出快照 → 新会话导入 → 上下文一致且仍“当前有效”

运行：python scenario_demo.py （在 minimax/ 目录下）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 保证可从任意目录运行
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sdd_context import (  # noqa: E402
    ContextAssembler,
    HandoffManager,
    SpecKind,
    SpecRegistry,
    ValidityEngine,
)

# ---------------------------------------------------------------------------
# 代码内容（随演进阶段写入 src/order_discount.py —— 这就是“实际代码修改”）
# ---------------------------------------------------------------------------
V1_0_CODE = '''# -*- coding: utf-8 -*-
"""order_discount.py —— 订单折扣服务（discount-service）当前实现。"""

THRESHOLD = 100.0
DISCOUNT = 10.0
COUPON_RATES = {"SAVE10": 0.9}


def compute_discount(amount: float, code: str | None = None) -> float:
    """计算折扣后金额（契约 v1.0 对外接口）。"""
    price = amount
    if price >= THRESHOLD:
        price -= DISCOUNT
    price *= COUPON_RATES.get(code, 1.0)
    return round(price, 2)
'''

V1_1_CODE = '''# -*- coding: utf-8 -*-
"""order_discount.py —— 订单折扣服务（discount-service）当前实现。"""

THRESHOLD = 100.0
DISCOUNT = 10.0
COUPON_RATES = {"SAVE10": 0.9}


def compute_discount(amount: float, code: str | None = None) -> float:
    """计算折扣后金额（契约 v1.0 对外接口）。"""
    if amount <= 0:
        return 0.0  # v1.1 新增：负金额防御
    price = amount
    if price >= THRESHOLD:
        price -= DISCOUNT
    price *= COUPON_RATES.get(code, 1.0)
    return round(price, 2)
'''

V2_0_CODE = '''# -*- coding: utf-8 -*-
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
'''

# 测试内容（随契约版本写入 tests/test_order_discount.py）
TEST_V1 = '''# -*- coding: utf-8 -*-
"""test_order_discount.py —— 契约 v1.0 测试。"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from order_discount import compute_discount  # noqa: E402


class TestComputeDiscount(unittest.TestCase):
    def test_at_threshold(self):
        self.assertEqual(compute_discount(100.0), 90.0)

    def test_below_threshold(self):
        self.assertEqual(compute_discount(99.0), 99.0)

    def test_threshold_plus_coupon(self):
        self.assertEqual(compute_discount(100.0, "SAVE10"), 81.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
'''

TEST_V2 = '''# -*- coding: utf-8 -*-
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
'''


def section(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def main() -> None:
    src_file = ROOT / "demo_project" / "src" / "order_discount.py"
    test_file = ROOT / "demo_project" / "tests" / "test_order_discount.py"
    specs_dir = ROOT / "demo_project" / "specs"

    def read_spec(name: str) -> str:
        return (specs_dir / name).read_text(encoding="utf-8")

    handoff = HandoffManager(SpecRegistry())  # 仅用于 digest 工具

    # ------------------------------------------------------------------
    section("阶段 0：登记 v1.0 规格、代码与测试")
    # ------------------------------------------------------------------
    src_file.write_text(V1_0_CODE, encoding="utf-8")
    test_file.write_text(TEST_V1, encoding="utf-8")

    reg = SpecRegistry()
    src_abs = str(src_file)
    test_abs = str(test_file)

    reg.register_spec(
        "discount-requirements", "1.0.0", SpecKind.REQUIREMENT,
        read_spec("requirements_v1.md"),
        linked_files=[src_abs],
    )
    reg.register_spec(
        "discount-contract", "1.0.0", SpecKind.CONTRACT,
        read_spec("contract_v1.md"),
        linked_files=[src_abs], linked_tests=[test_abs],
    )
    reg.record_code(src_abs, handoff.digest_file(src_abs))
    reg.register_test(test_abs, spec_ref="discount-contract",
                      covered_files=[src_abs], last_status="passed")
    reg.register_decision("DEC-001", "规则表驱动，不引入数据库", "discount-service")
    reg.register_decision("DEC-002", "金额统一 round 两位小数", "discount-service")
    print("已登记：需求 v1.0、契约 v1.0、代码快照、测试（passed）、决策 DEC-001/002")

    engine = ValidityEngine(reg)
    assembler = ContextAssembler(reg, engine)

    # ------------------------------------------------------------------
    section("阶段 1：新会话，任务「实现订单折扣」→ 组装当前有效上下文")
    # ------------------------------------------------------------------
    ctx1 = assembler.assemble(
        "实现订单折扣：满减与折扣码",
        current_hashes=handoff.current_hashes([src_abs]),
    )
    print(assembler.render_prompt(ctx1))
    assert [s.qualified() for s in ctx1.active_specs] == [
        "discount-requirements@1.0.0", "discount-contract@1.0.0"
    ]
    assert len(ctx1.relevant_tests) == 1 and not ctx1.stale_tests
    assert not ctx1.invalid_tests
    print("\n[校验通过] 上下文只含 v1.0 有效规格，测试可直接采信")

    # ------------------------------------------------------------------
    section("阶段 2：实际修改代码（v1.0 → v1.1 增加负金额防御）")
    # ------------------------------------------------------------------
    src_file.write_text(V1_1_CODE, encoding="utf-8")
    changed = handoff.reconcile([src_abs])
    print(f"对账发现代码变更：{[(p.split(os.sep)[-1], '内容变化') for p, _, _ in changed]}")
    # 注意：此处不更新注册表快照，模拟“代码已修改、验证尚未重跑”的真实中间态，
    # 上下文模块应据此把相关验证判定为 stale。

    ctx2 = assembler.assemble(
        "修复折扣计算的金额边界问题",
        current_hashes=handoff.current_hashes([src_abs]),
    )
    print(assembler.render_prompt(ctx2))
    assert len(ctx2.stale_tests) == 1, "代码变更后相关测试应判定为 stale"
    print("\n[校验通过] 代码已变更 → 先前验证判定为 stale（须重跑）")

    # ------------------------------------------------------------------
    section("阶段 3：需求升级 v1.0 → v2.0（满 200 减 30、阶梯折扣）")
    # ------------------------------------------------------------------
    reg.supersede_spec("discount-requirements", "2.0.0", read_spec("requirements_v2.md"))
    reg.supersede_spec("discount-contract", "2.0.0", read_spec("contract_v2.md"),
                       linked_files=[src_abs], linked_tests=[test_abs])
    # 需求变更 → 旧设计决策级联失效，登记新决策
    reg.cascade_invalidate_decisions("discount-service")
    reg.register_decision("DEC-101", "阶梯折扣使用有序档位表", "discount-service")
    reg.register_decision("DEC-102", "接口以最终价格语义重构，统一 compute_price", "discount-service")

    print("v2.0 规格已登记；失效决策：",
          [d.id for d in reg.retired_decisions()])

    # 此刻代码仍是 v1.1（未同步升级），任务上下文应只含 v2 规格并警示
    ctx3 = assembler.assemble("增加阶梯折扣与满减档位", current_hashes=handoff.current_hashes([src_abs]))
    print(assembler.render_prompt(ctx3))
    versions = [s.qualified() for s in ctx3.active_specs]
    assert all("2.0.0" in v for v in versions), "任务上下文不得再含 v1 规格"
    assert any(d.id == "DEC-001" for d in ctx3.retired_decisions)
    assert any(d.id == "DEC-002" for d in ctx3.retired_decisions)
    assert any(d.id == "DEC-101" for d in reg.active_decisions())
    print("\n[校验通过] 上下文只含 v2.0 有效规格；DEC-001/002 已列为失效决策")

    # ------------------------------------------------------------------
    section("阶段 4：契约变更落地（compute_discount → compute_price）")
    # ------------------------------------------------------------------
    src_file.write_text(V2_0_CODE, encoding="utf-8")
    test_file.write_text(TEST_V2, encoding="utf-8")
    reg.record_code(src_abs, handoff.digest_file(src_abs))
    # 契约 v2 的测试登记为新测试（旧测试记录保留在历史中，未覆盖）
    reg.register_test(test_abs, spec_ref="discount-contract",
                      covered_files=[src_abs], last_status="passed")

    # 模拟“旧测试仍在测试套件中运行”的场景：登记一条引用旧接口的测试，
    # 并挂到契约 v2 的关联测试列表，使组装器能评估它并判定失效。
    from sdd_context import TestRecord  # noqa: E402
    legacy_test_path = str(ROOT / "demo_project" / "tests" / "_history" / "test_order_discount_v1.py")
    reg.register_test(legacy_test_path, spec_ref="discount-contract",
                      spec_version="1.0.0",   # v1 时代遗留，依据的是已失效的 v1 契约
                      covered_files=[src_abs], last_status="passed")
    contract_v2 = reg.get_spec("discount-contract", "2.0.0")
    if legacy_test_path not in contract_v2.linked_tests:
        contract_v2.linked_tests.append(legacy_test_path)

    ctx4 = assembler.assemble("价格计算接口迁移：compute_discount 到 compute_price",
                              current_hashes=handoff.current_hashes([src_abs]))
    print(assembler.render_prompt(ctx4))
    # 新测试（当前 tests/test_order_discount.py）应 valid
    current_test = reg.get_test(test_abs)
    assert any(t.path == current_test.path for t in ctx4.relevant_tests)
    # 旧测试应 invalid（其引用符号不在当前契约中 / 依据的契约已变更）
    assert any(t.path == legacy_test_path for t in ctx4.invalid_tests)
    print("\n[校验通过] 新契约测试 valid；引用旧接口的测试判定 invalid")

    # ------------------------------------------------------------------
    section("阶段 5：跨会话交接（导出 → 新会话导入 → 上下文一致）")
    # ------------------------------------------------------------------
    handoff = HandoffManager(reg)   # 绑定真实注册表
    snapshot = handoff.export_snapshot()
    print(f"快照已导出：规格历史 {len(snapshot['registry']['specs'])} 条、"
          f"决策 {len(snapshot['registry']['decisions'])} 条、"
          f"测试 {len(snapshot['registry']['tests'])} 条")

    new_reg = HandoffManager.import_snapshot(snapshot)   # 新会话重建
    new_engine = ValidityEngine(new_reg)
    new_assembler = ContextAssembler(new_reg, new_engine)
    ctx5 = new_assembler.assemble("价格计算接口迁移", current_hashes=handoff.current_hashes([src_abs]))

    assert {s.qualified() for s in ctx5.active_specs} == {
        s.qualified() for s in ctx4.active_specs
    }, "交接后上下文应与交接前一致"
    assert ctx5.active_specs, "交接后任务上下文非空"
    assert all(
        "1.0.0" not in s.qualified() for s in ctx5.active_specs
    ), "交接后不得再提供已失效的 v1 规格"
    assert len(ctx5.invalid_tests) == 1
    assert not any("1.0.0" in s.qualified() for s in ctx5.active_specs)
    print("新会话组装结果（同一任务）：")
    print(new_assembler.render_prompt(ctx5))
    print("\n[校验通过] 交接后上下文与旧会话一致，且仍只含当前有效规格")

    section("全部场景验证通过 ✓")

    # 恢复仓库文件到 v2.0 当前版本（与规格一致）
    src_file.write_text(V2_0_CODE, encoding="utf-8")
    test_file.write_text(TEST_V2, encoding="utf-8")


if __name__ == "__main__":
    main()
