# -*- coding: utf-8 -*-
"""验证有效性判定引擎单元测试。

覆盖题目核心问题：“先前验证是否仍适用于当前代码”——
valid（可采信）/ stale（代码已变更需重跑）/ invalid（规格/契约已失效）。
"""

import unittest

from sdd_context import (
    HandoffManager,
    SpecKind,
    SpecRegistry,
    ValidityEngine,
    VerificationStatus,
)


def _mk_registry() -> tuple:
    """构造：契约 v1 active、代码快照已登记、测试引用 compute_discount。"""
    reg = SpecRegistry()
    src = "/repo/src/app.py"
    test = "/repo/tests/test_app.py"
    reg.register_spec(
        "svc-contract", "1.0.0", SpecKind.CONTRACT,
        "### 函数 `compute_discount(amount: float) -> float`",
        linked_files=[src], linked_tests=[test],
    )
    reg.record_code(src, "hash-v1")
    reg.register_test(
        test, spec_ref="svc-contract", covered_files=[src], last_status="passed",
    )
    return reg, src, test


class TestValidityEngine(unittest.TestCase):
    def setUp(self):
        self.reg, self.src, self.test = _mk_registry()
        self.engine = ValidityEngine(self.reg)
        self.rec = self.reg.get_test(self.test)

    def test_valid_when_unchanged(self):
        status, reason, _ = self.engine.evaluate_with_reason(
            self.rec,
            test_text="from app import compute_discount\nassert compute_discount(100) == 90",
            current_hashes={self.src: "hash-v1"},
        )
        self.assertEqual(status, VerificationStatus.VALID)

    def test_stale_when_code_changed(self):
        status, reason, detail = self.engine.evaluate_with_reason(
            self.rec,
            test_text="from app import compute_discount",
            current_hashes={self.src: "hash-v2"},   # 代码已变
        )
        self.assertEqual(status, VerificationStatus.STALE)
        self.assertIn(self.src, detail["changed_files"])

    def test_stale_when_hash_missing(self):
        # 未提供当前 hash：无法确认一致性，保守判定为 stale
        status, _, _ = self.engine.evaluate_with_reason(
            self.rec, test_text="from app import compute_discount", current_hashes=None,
        )
        self.assertEqual(status, VerificationStatus.STALE)

    def test_invalid_when_spec_superseded(self):
        self.reg.register_spec(
            "svc-contract", "2.0.0", SpecKind.CONTRACT,
            "### 函数 `compute_price(amount: float) -> float`",
        )
        status, reason, _ = self.engine.evaluate_with_reason(
            self.rec,
            test_text="from app import compute_discount",
            current_hashes={self.src: "hash-v1"},
        )
        self.assertEqual(status, VerificationStatus.INVALID)
        self.assertIn("已失效", reason)

    def test_invalid_when_contract_symbol_missing(self):
        # 契约已升级到 v2（active），测试登记时依据 v2，但仍引用旧接口
        self.reg.register_spec(
            "svc-contract", "2.0.0", SpecKind.CONTRACT,
            "### 函数 `compute_price(amount: float) -> float`",
        )
        self.rec = self.reg.register_test(
            self.test, spec_ref="svc-contract",
            covered_files=[self.src], last_status="passed",  # spec_version 自动取 2.0.0
        )
        status, reason, detail = self.engine.evaluate_with_reason(
            self.rec,
            test_text="from app import compute_discount",
            current_hashes={self.src: "hash-v1"},
        )
        self.assertEqual(status, VerificationStatus.INVALID)
        self.assertIn("compute_discount", reason)

    def test_symbol_extraction_ignores_stdlib(self):
        text = (
            "import sys\nimport os\nimport unittest\n"
            "from app import compute_discount\n"
            "class TestApp(unittest.TestCase):\n"
            "    def test_a(self):\n"
            "        self.assertEqual(compute_discount(100), 90)\n"
        )
        symbols = self.engine.extract_symbols(text)
        self.assertEqual(symbols, {"compute_discount"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
