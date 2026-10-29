# -*- coding: utf-8 -*-
"""
sdd_context.model
=================
面向 SDD（Spec-Driven Development，规格驱动开发）的工程上下文数据模型。

一个持续维护的软件项目里，需求规格（requirement）、接口契约（contract）、
设计决策（decision）、代码（code）与测试（test）都在不断演进。本模块用
不可变的历史记录 + 显式的状态机来表达这种演进，使 AI 开发助手能够回答：

1. 当前任务应遵守什么要求？（当前状态为 active 的规格）
2. 哪些决策已经失效？（被 superseded / retired 的决策）
3. 先前验证是否仍适用于当前代码？（测试与代码快照 / 契约的对照）

所有类型都是 dataclass，纯标准库实现，可序列化为 JSON 用于跨会话交接。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class SpecStatus(str, Enum):
    """规格生命周期状态。

    - active     : 当前有效，任务必须遵守
    - superseded : 已被新版本替代，不再有效（历史保留）
    - retired    : 已废弃，不再有效（历史保留）
    """

    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


class SpecKind(str, Enum):
    """规格的类型。

    - requirement : 需求规格（做什么、验收标准）
    - contract    : 接口契约（对外 API、数据结构、行为约定）
    - decision    : 设计决策（怎么做、技术选型、权衡记录）
    - test_plan   : 测试计划（覆盖哪些行为、如何验证）
    """

    REQUIREMENT = "requirement"
    CONTRACT = "contract"
    DECISION = "decision"
    TEST_PLAN = "test_plan"


class VerificationStatus(str, Enum):
    """先前验证（测试）对当前代码的适用性判定结果。

    - valid   : 验证仍然有效，可直接采信
    - stale   : 验证所覆盖的代码已变更，结果可能过期，需重新运行
    - invalid : 验证所依据的规格/契约已失效，不再适用于当前代码，必须更新
    """

    VALID = "valid"
    STALE = "stale"
    INVALID = "invalid"


@dataclass
class SpecVersion:
    """一份规格的某个版本。

    id 是规格的稳定标识（如 discount-service），version 是语义化版本号。
    同一 id 的多个 version 构成演进历史，只有 status == active 的版本对
    当前任务生效。
    """

    id: str
    version: str
    kind: SpecKind
    content: str
    status: SpecStatus = SpecStatus.ACTIVE
    superseded_by: Optional[str] = None      # 被哪个 (id@version) 替代
    linked_files: List[str] = field(default_factory=list)   # 关联的代码文件
    linked_tests: List[str] = field(default_factory=list)   # 关联的测试文件
    created_at: str = ""
    updated_at: str = ""

    def qualified(self) -> str:
        """形如 discount-service@1.0.0 的限定名。"""
        return f"{self.id}@{self.version}"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SpecVersion":
        d = dict(data)
        d["kind"] = SpecKind(d["kind"])
        d["status"] = SpecStatus(d["status"])
        return cls(**d)


@dataclass
class DecisionRecord:
    """一条设计决策。

    决策依附于某个规格演进（related_spec），当规格被替代或契约变更时，
    相关决策应被显式标记为失效（superseded），任务上下文不再采信。
    """

    id: str
    content: str
    status: str = "active"               # active / superseded / retired
    superseded_by: Optional[str] = None  # 替代该决策的新决策 id
    related_spec: Optional[str] = None   # 关联的规格 id（如 discount-service）
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecisionRecord":
        return cls(**data)


@dataclass
class CodeSnapshot:
    """某个代码文件的快照。

    sha256 是文件内容的指纹；验证有效性判定通过比较当前文件 sha256 与
    登记时的 sha256 判断“代码是否变化、先前验证是否可信”。
    """

    path: str
    sha256: str
    recorded_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CodeSnapshot":
        return cls(**data)

    @staticmethod
    def digest(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class TestRecord:
    """一条测试/验证记录。

    spec_ref 指向其验证的规格 id；spec_version 记录**登记时所依据的规格
    版本**（用于判定“依据的规格是否仍有效”）；covered_files 列出它覆盖
    的代码文件；last_status 记录最近一次运行结果。
    """

    path: str
    spec_ref: str
    spec_version: Optional[str] = None      # 登记时所依据的规格版本
    covered_files: List[str] = field(default_factory=list)
    last_status: str = "unknown"
    last_run_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TestRecord":
        return cls(**data)


@dataclass
class TaskContext:
    """面向一次开发任务组装出的工程上下文。

    这是 AI 开发助手真正消费的产物：只包含当前有效的规格、相关的代码与
    测试，并显式附带“哪些决策已失效 / 哪些验证已过期”的警示，避免助手
    依据旧规格、旧决策或过期测试做出错误判断。
    """

    task: str
    active_specs: List[SpecVersion] = field(default_factory=list)
    relevant_code: List[str] = field(default_factory=list)
    relevant_tests: List[TestRecord] = field(default_factory=list)
    stale_tests: List[TestRecord] = field(default_factory=list)
    invalid_tests: List[TestRecord] = field(default_factory=list)
    retired_decisions: List[DecisionRecord] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "active_specs": [s.to_dict() for s in self.active_specs],
            "relevant_code": list(self.relevant_code),
            "relevant_tests": [t.to_dict() for t in self.relevant_tests],
            "stale_tests": [t.to_dict() for t in self.stale_tests],
            "invalid_tests": [t.to_dict() for t in self.invalid_tests],
            "retired_decisions": [d.to_dict() for d in self.retired_decisions],
            "warnings": list(self.warnings),
        }
