# -*- coding: utf-8 -*-
"""注册表单元测试：规格登记、演进状态机、决策失效传播。"""

import unittest

from sdd_context import DecisionRecord, SpecKind, SpecRegistry, SpecStatus


class TestSpecRegistry(unittest.TestCase):
    def test_register_and_active(self):
        reg = SpecRegistry()
        reg.register_spec("svc", "1.0.0", SpecKind.REQUIREMENT, "需求 A")
        specs = reg.active_specs()
        self.assertEqual(len(specs), 1)
        self.assertEqual(specs[0].qualified(), "svc@1.0.0")
        self.assertEqual(specs[0].status, SpecStatus.ACTIVE)

    def test_new_version_supersedes_old(self):
        reg = SpecRegistry()
        reg.register_spec("svc", "1.0.0", SpecKind.REQUIREMENT, "旧需求")
        reg.register_spec("svc", "2.0.0", SpecKind.REQUIREMENT, "新需求")
        v1 = reg.get_spec("svc", "1.0.0")
        v2 = reg.get_spec("svc", "2.0.0")
        self.assertEqual(v1.status, SpecStatus.SUPERSEDED)
        self.assertEqual(v1.superseded_by, "svc@2.0.0")
        self.assertEqual(v2.status, SpecStatus.ACTIVE)
        # 只有 v2 出现在 active 集合中
        self.assertEqual([s.qualified() for s in reg.active_specs()], ["svc@2.0.0"])
        # 历史仍保留
        self.assertEqual(len(reg.all_versions("svc")), 2)

    def test_retire(self):
        reg = SpecRegistry()
        reg.register_spec("svc", "1.0.0", SpecKind.REQUIREMENT, "A")
        reg.retire_spec("svc")
        self.assertEqual(reg.get_spec("svc").status, SpecStatus.RETIRED)
        self.assertEqual(reg.active_specs(), [])

    def test_cascade_decision_invalidation(self):
        reg = SpecRegistry()
        reg.register_spec("svc", "1.0.0", SpecKind.REQUIREMENT, "A")
        reg.register_decision("DEC-1", "基于 v1 的决策", "svc")
        reg.register_decision("DEC-2", "与规格无关的决策", "other-service")
        # 规格演进导致依附决策失效
        reg.cascade_invalidate_decisions("svc")
        self.assertEqual([d.id for d in reg.retired_decisions()], ["DEC-1"])
        self.assertEqual([d.id for d in reg.active_decisions()], ["DEC-2"])

    def test_spec_kind_filter(self):
        reg = SpecRegistry()
        reg.register_spec("r", "1.0.0", SpecKind.REQUIREMENT, "需求")
        reg.register_spec("c", "1.0.0", SpecKind.CONTRACT, "契约")
        self.assertEqual(len(reg.active_specs(SpecKind.REQUIREMENT)), 1)
        self.assertEqual(len(reg.active_specs(SpecKind.CONTRACT)), 1)

    def test_serialization_roundtrip(self):
        reg = SpecRegistry()
        reg.register_spec("svc", "1.0.0", SpecKind.REQUIREMENT, "A")
        reg.register_spec("svc", "2.0.0", SpecKind.REQUIREMENT, "B")
        reg.register_decision("DEC-1", "决策", "svc")
        data = reg.to_dict()
        reg2 = SpecRegistry.from_dict(data)
        self.assertEqual(
            [s.qualified() for s in reg2.active_specs()],
            ["svc@2.0.0"],
        )
        self.assertEqual(len(reg2.all_versions("svc")), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
