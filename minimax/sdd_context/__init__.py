# -*- coding: utf-8 -*-
"""
sdd_context
===========
面向软件持续演进的 SDD（Spec-Driven Development）工程上下文管理系统。

为已有 AI 开发助手（如 MiniMax Code + PowerContext）实现工程上下文模块，
解决三个核心问题：

1. 当前任务应遵守什么要求？   —— 只提供 active 状态的规格（SpecRegistry）
2. 哪些决策已经失效？         —— 决策生命周期与规格演进的级联失效
3. 先前验证是否仍适用于当前代码？ —— 代码指纹 + 契约符号的适用性判定

同时提供跨会话交接（HandoffManager）与 PowerContext 可选对接
（PowerContextBridge）。

用法（纯标准库，无需第三方依赖）：

    from sdd_context.registry import SpecRegistry
    from sdd_context.validity import ValidityEngine
    from sdd_context.assembly import ContextAssembler

    reg = SpecRegistry()
    # ... 登记规格 / 决策 / 代码快照 / 测试 ...
    engine = ValidityEngine(reg)
    assembler = ContextAssembler(reg, engine)
    ctx = assembler.assemble("修复订单折扣计算 bug")
    print(assembler.render_prompt(ctx))
"""

from .model import (
    CodeSnapshot,
    DecisionRecord,
    SpecKind,
    SpecStatus,
    SpecVersion,
    TaskContext,
    TestRecord,
    VerificationStatus,
)
from .registry import SpecRegistry
from .validity import ValidityEngine
from .assembly import ContextAssembler
from .handoff import HandoffManager
from .powercontext_bridge import PowerContextBridge

__all__ = [
    "CodeSnapshot",
    "ContextAssembler",
    "DecisionRecord",
    "HandoffManager",
    "PowerContextBridge",
    "SpecKind",
    "SpecRegistry",
    "SpecStatus",
    "SpecVersion",
    "TaskContext",
    "TestRecord",
    "ValidityEngine",
    "VerificationStatus",
]

__version__ = "1.0.0"
