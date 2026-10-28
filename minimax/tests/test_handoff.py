# -*- coding: utf-8 -*-
"""交接模块单元测试：跨会话导出 / 导入 / 对账。

覆盖题目核心问题：“跨会话和任务交接” ——
新会话通过快照重建注册表，对同一任务得到与旧会话一致且当前有效的上下文。
"""

import os
import tempfile
import unittest

from sdd_context import (
    ContextAssembler,
    HandoffManager,
    SpecKind,
    SpecRegistry,
    ValidityEngine,
)


class TestHandoff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, "app.py")
        self.test = os.path.join(self.tmp, "test_app.py")
        with open(self.src, "w", encoding="utf-8") as f:
            f.write("def compute_price(x): return x\n")
        with open(self.test, "w", encoding="utf-8") as f:
            f.write("from app import compute_price\n")

        self.reg = SpecRegistry()
        self.reg.register_spec(
            "svc-contract", "1.0.0", SpecKind.CONTRACT,
            "### 函数 `compute_price(amount: float) -> float`",
            linked_files=[self.src], linked_tests=[self.test],
        )
        self.reg.record_code(self.src, HandoffManager.digest_file(self.src))
        self.reg.register_test(self.test, spec_ref="svc-contract",
                               covered_files=[self.src], last_status="passed")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_export_import_roundtrip(self):
        manager = HandoffManager(self.reg)
        snapshot = manager.export_snapshot()
        new_reg = HandoffManager.import_snapshot(snapshot)

        self.assertEqual(
            [s.qualified() for s in new_reg.active_specs()],
            [s.qualified() for s in self.reg.active_specs()],
        )
        self.assertEqual(len(new_reg.all_tests()), 1)

    def test_handoff_same_task_same_context(self):
        manager = HandoffManager(self.reg)
        snapshot = manager.export_snapshot()
        new_reg = HandoffManager.import_snapshot(snapshot)

        a1 = ContextAssembler(self.reg, ValidityEngine(self.reg)).assemble(
            "价格计算", current_hashes={self.src: HandoffManager.digest_file(self.src)}
        )
        a2 = ContextAssembler(new_reg, ValidityEngine(new_reg)).assemble(
            "价格计算", current_hashes={self.src: HandoffManager.digest_file(self.src)}
        )
        self.assertEqual(
            [s.qualified() for s in a1.active_specs],
            [s.qualified() for s in a2.active_specs],
        )

    def test_reconcile_detects_change(self):
        manager = HandoffManager(self.reg)
        # 修改磁盘上的代码 → 对账应发现变更
        with open(self.src, "w", encoding="utf-8") as f:
            f.write("def compute_price(x): return x * 2\n")
        changed = manager.reconcile([self.src])
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0][0], self.src)
        self.assertNotEqual(changed[0][1], changed[0][2])


if __name__ == "__main__":
    unittest.main(verbosity=2)
