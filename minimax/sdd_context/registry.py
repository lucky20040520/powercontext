# -*- coding: utf-8 -*-
"""
sdd_context.registry
====================
工程上下文的核心仓库：规格注册表（SpecRegistry）。

职责：
1. 规格的版本化登记与演进 —— 同一 id 可以登记多个 version；
2. 状态机 —— active -> superseded / retired，只有 active 规格对任务生效；
3. 决策失效传播 —— 规格被替代时，依附于它的决策被级联标记失效；
4. 代码与测试的登记 —— 维护代码快照与测试记录，供验证有效性判定使用。

所有写操作都保留历史（不会物理删除任何版本），保证可追溯。
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, Iterable, List, Optional

from .model import (
    CodeSnapshot,
    DecisionRecord,
    SpecKind,
    SpecStatus,
    SpecVersion,
    TestRecord,
)


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


class SpecRegistry:
    """保存规格、决策、代码快照、测试记录的注册表。"""

    def __init__(self) -> None:
        # id -> {version -> SpecVersion}
        self._specs: Dict[str, Dict[str, SpecVersion]] = {}
        # id -> DecisionRecord
        self._decisions: Dict[str, DecisionRecord] = {}
        # path -> CodeSnapshot（登记时的代码指纹）
        self._code_snapshots: Dict[str, CodeSnapshot] = {}
        # path -> TestRecord
        self._tests: Dict[str, TestRecord] = {}

    # ------------------------------------------------------------------
    # 规格登记
    # ------------------------------------------------------------------
    def register_spec(
        self,
        spec_id: str,
        version: str,
        kind: SpecKind,
        content: str,
        linked_files: Optional[List[str]] = None,
        linked_tests: Optional[List[str]] = None,
        created_at: Optional[str] = None,
    ) -> SpecVersion:
        """登记一份新规格（或同一 id 的新版本）。

        若该 id 已存在 active 版本，新版本登记后会自动把旧版本标记为
        superseded，实现“规格演进”的默认语义。
        """
        spec = SpecVersion(
            id=spec_id,
            version=version,
            kind=kind,
            content=content,
            status=SpecStatus.ACTIVE,
            linked_files=list(linked_files or []),
            linked_tests=list(linked_tests or []),
            created_at=created_at or _now(),
            updated_at=_now(),
        )
        bucket = self._specs.setdefault(spec_id, {})
        # 同一 (id, version) 幂等：已存在则视为重放，不覆盖历史
        if version in bucket:
            return bucket[version]
        # 规格演进：旧 active 版本被本版本替代
        for prev in bucket.values():
            if prev.status == SpecStatus.ACTIVE:
                prev.status = SpecStatus.SUPERSEDED
                prev.superseded_by = spec.qualified()
                prev.updated_at = _now()
        bucket[version] = spec
        return spec

    def get_spec(self, spec_id: str, version: Optional[str] = None) -> Optional[SpecVersion]:
        bucket = self._specs.get(spec_id)
        if not bucket:
            return None
        if version is not None:
            return bucket.get(version)
        # 取最新版本（按登记顺序，通常也是最高版本）
        return list(bucket.values())[-1]

    def all_versions(self, spec_id: str) -> List[SpecVersion]:
        return list(self._specs.get(spec_id, {}).values())

    def active_specs(self, kind: Optional[SpecKind] = None) -> List[SpecVersion]:
        """当前所有有效的规格（排除 superseded / retired）。"""
        result: List[SpecVersion] = []
        for bucket in self._specs.values():
            for spec in bucket.values():
                if spec.status == SpecStatus.ACTIVE and (
                    kind is None or spec.kind == kind
                ):
                    result.append(spec)
        return result

    def retire_spec(self, spec_id: str, version: Optional[str] = None) -> None:
        """废弃一份规格（retired）。若未指定版本则废弃最新版本。"""
        spec = self.get_spec(spec_id, version)
        if spec is None:
            raise KeyError(f"spec not found: {spec_id}@{version or '*'}")
        spec.status = SpecStatus.RETIRED
        spec.updated_at = _now()

    def supersede_spec(
        self, spec_id: str, new_version: str, new_content: str,
        kind: Optional[SpecKind] = None,
        linked_files: Optional[List[str]] = None,
        linked_tests: Optional[List[str]] = None,
    ) -> SpecVersion:
        """显式演进：为 spec_id 登记新版本，旧版本自动 superseded。"""
        old = self.get_spec(spec_id)
        k = kind or (old.kind if old else SpecKind.REQUIREMENT)
        return self.register_spec(
            spec_id, new_version, k, new_content,
            linked_files=linked_files, linked_tests=linked_tests,
        )

    # ------------------------------------------------------------------
    # 决策登记与失效
    # ------------------------------------------------------------------
    def register_decision(
        self,
        decision_id: str,
        content: str,
        related_spec: Optional[str] = None,
        created_at: Optional[str] = None,
    ) -> DecisionRecord:
        rec = DecisionRecord(
            id=decision_id,
            content=content,
            status="active",
            related_spec=related_spec,
            created_at=created_at or _now(),
            updated_at=_now(),
        )
        self._decisions[decision_id] = rec
        return rec

    def supersede_decision(self, decision_id: str, superseded_by: str) -> None:
        """显式标记一条决策失效。"""
        rec = self._decisions.get(decision_id)
        if rec is None:
            raise KeyError(f"decision not found: {decision_id}")
        rec.status = "superseded"
        rec.superseded_by = superseded_by
        rec.updated_at = _now()

    def active_decisions(self) -> List[DecisionRecord]:
        return [d for d in self._decisions.values() if d.status == "active"]

    def retired_decisions(self) -> List[DecisionRecord]:
        return [d for d in self._decisions.values() if d.status != "active"]

    def cascade_invalidate_decisions(self, spec_id: str) -> None:
        """规格失效/被替代后，级联失效依附于它的全部决策。

        这是“哪些决策已经失效”判定中最重要的传播规则：需求变了，
        建立在旧需求上的技术决策随之失效。
        """
        for rec in self._decisions.values():
            if rec.related_spec == spec_id and rec.status == "active":
                rec.status = "superseded"
                rec.superseded_by = f"spec:{spec_id} invalidated"
                rec.updated_at = _now()

    # ------------------------------------------------------------------
    # 代码快照登记
    # ------------------------------------------------------------------
    def record_code(self, path: str, sha256: str) -> CodeSnapshot:
        snap = CodeSnapshot(path=path, sha256=sha256, recorded_at=_now())
        self._code_snapshots[path] = snap
        return snap

    def get_code_snapshot(self, path: str) -> Optional[CodeSnapshot]:
        return self._code_snapshots.get(path)

    def code_changed(self, path: str, current_sha256: str) -> bool:
        """判断某代码文件自登记以来是否已变化。"""
        snap = self._code_snapshots.get(path)
        if snap is None:
            return True  # 从未登记：视为变化，需要重新验证
        return snap.sha256 != current_sha256

    # ------------------------------------------------------------------
    # 测试登记
    # ------------------------------------------------------------------
    def register_test(
        self,
        path: str,
        spec_ref: str,
        covered_files: Optional[List[str]] = None,
        last_status: str = "unknown",
        spec_version: Optional[str] = None,
    ) -> TestRecord:
        """登记一条测试记录。

        spec_version 未指定时，取 spec_ref 当前最新（通常 active）版本号，
        即“测试登记时依据的规格版本”。
        """
        if spec_version is None:
            latest = self.get_spec(spec_ref)
            spec_version = latest.version if latest else None
        rec = TestRecord(
            path=path,
            spec_ref=spec_ref,
            spec_version=spec_version,
            covered_files=list(covered_files or []),
            last_status=last_status,
            last_run_at=_now(),
        )
        self._tests[path] = rec
        return rec

    def get_test(self, path: str) -> Optional[TestRecord]:
        return self._tests.get(path)

    def all_tests(self) -> List[TestRecord]:
        return list(self._tests.values())

    def record_test_run(self, path: str, status: str) -> None:
        rec = self._tests.get(path)
        if rec is None:
            raise KeyError(f"test not found: {path}")
        rec.last_status = status
        rec.last_run_at = _now()

    # ------------------------------------------------------------------
    # 序列化（供交接快照使用）
    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "specs": [
                s.to_dict()
                for bucket in self._specs.values()
                for s in bucket.values()
            ],
            "decisions": [d.to_dict() for d in self._decisions.values()],
            "code_snapshots": [s.to_dict() for s in self._code_snapshots.values()],
            "tests": [t.to_dict() for t in self._tests.values()],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpecRegistry":
        reg = cls()
        for spec_dict in data.get("specs", []):
            spec = SpecVersion.from_dict(spec_dict)
            reg._specs.setdefault(spec.id, {})[spec.version] = spec
        for dec_dict in data.get("decisions", []):
            dec = DecisionRecord.from_dict(dec_dict)
            reg._decisions[dec.id] = dec
        for snap_dict in data.get("code_snapshots", []):
            snap = CodeSnapshot.from_dict(snap_dict)
            reg._code_snapshots[snap.path] = snap
        for test_dict in data.get("tests", []):
            test = TestRecord.from_dict(test_dict)
            reg._tests[test.path] = test
        return reg
