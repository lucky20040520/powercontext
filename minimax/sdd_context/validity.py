# -*- coding: utf-8 -*-
"""
sdd_context.validity
====================
验证有效性判定引擎（ValidityEngine）。

回答题目的核心问题之一：“先前验证是否仍适用于当前代码？”

判定一条测试/验证记录对当前代码的适用性，规则如下（按优先级）：

1. INVALID —— 验证所依据的规格已失效：
   测试的 spec_ref 对应的规格若处于 superseded / retired 状态，
   说明验证是针对旧规格做的，对当前需求不再适用，必须更新测试。

2. INVALID —— 验证引用的契约符号已不在当前契约中：
   从测试文本中提取接口引用（函数名 / HTTP 端点等），与当前 active
   的 contract 规格比对；引用了已不存在的符号，说明契约已变，测试失效。

3. STALE —— 验证覆盖的代码已变更：
   测试覆盖的代码文件，其当前 sha256 与登记时不一致（或从未登记），
   说明代码已修改而验证未重跑，结果可能过期，需要重新运行。

4. VALID —— 其余情况：依据的规格仍有效、契约未变、代码未变，
   先前验证结果可以直接采信。

判定结果带有原因（reason），供 AI 开发助手直接引用。
"""

from __future__ import annotations

import re
from typing import List, Optional

from .model import (
    SpecKind,
    SpecStatus,
    TestRecord,
    VerificationStatus,
)
from .registry import SpecRegistry


class ValidityEngine:
    """基于注册表当前状态判定每条测试的适用性。"""

    def __init__(self, registry: SpecRegistry) -> None:
        self._registry = registry

    # ------------------------------------------------------------------
    # 契约符号提取
    # ------------------------------------------------------------------
    # 测试显式导入的接口名：from module import name, ...
    _FROM_IMPORT_RE = re.compile(r"from\s+[\w.]+\s+import\s+([^#\n]+)")
    # 独立的 import 语句：import module（取模块名，供与契约声明对照）
    _IMPORT_RE = re.compile(r"(?<!from\s)import\s+([\w.]+)")
    # HTTP 端点引用：形如 "/discount" 或 "GET /price"
    _ENDPOINT_RE = re.compile(r"[\"'](/[\w\-/]+)[\"']|(?:GET|POST|PUT|DELETE)\s+(/[\w\-/]+)")

    @staticmethod
    def extract_symbols(test_text: str) -> set:
        """从测试正文中提取被测接口的引用符号。

        只提取测试**显式导入（from ... import ...）**的接口名与 HTTP 端点；
        `import sys` 等标准库模块导入不参与契约对照。
        """
        symbols: set = set()

        for m in ValidityEngine._FROM_IMPORT_RE.finditer(test_text):
            for raw in m.group(1).split(","):
                name = raw.strip()
                if name and name.isidentifier():
                    symbols.add(name)

        for m in ValidityEngine._ENDPOINT_RE.finditer(test_text):
            if m.group(1):
                symbols.add(m.group(1))
            if m.group(2):
                symbols.add(m.group(2))

        return symbols

    # 契约正文中的函数签名：`compute_discount(amount: ...) -> float`
    _SIG_RE = re.compile(r"`([a-zA-Z_]\w*)\s*\(")

    def _active_contract_symbols(self) -> set:
        """当前有效契约中声明的接口符号。"""
        symbols: set = set()
        for spec in self._registry.active_specs(SpecKind.CONTRACT):
            # 契约正文中的“函数签名/端点”按行提取
            for line in spec.content.splitlines():
                stripped = line.strip().lstrip("-* ").strip()
                if not stripped:
                    continue
                m = ValidityEngine._SIG_RE.search(stripped)
                if m:
                    symbols.add(m.group(1))
                em = ValidityEngine._ENDPOINT_RE.search(stripped)
                if em:
                    symbols.add(em.group(1) or em.group(2))
        return symbols

    # ------------------------------------------------------------------
    # 判定入口
    # ------------------------------------------------------------------
    def evaluate(self, test: TestRecord, test_text: str = "") -> VerificationStatus:
        """判定一条测试对当前代码的适用性，返回 VerificationStatus。"""
        reg = self._registry

        # 规则 1：测试依据的规格版本是否仍有效
        spec = self._referenced_spec(test)
        if spec is None or spec.status != SpecStatus.ACTIVE:
            return VerificationStatus.INVALID

        # 规则 2：测试引用的契约符号是否仍存在
        if test_text:
            used = self.extract_symbols(test_text)
            declared = self._active_contract_symbols()
            missing = used - declared
            if missing:
                return VerificationStatus.INVALID

        # 规则 3：覆盖的代码是否已变更
        for path in test.covered_files:
            snap = reg.get_code_snapshot(path)
            if snap is None:
                # 代码文件从未被登记：无法确认一致性，视为已变化
                return VerificationStatus.STALE
            # 重新计算磁盘上当前文件的指纹（由调用方传入 compare 值）
            # 这里只做登记侧比较；与磁盘的实时比较由 assembly/reconcile 完成。
        return VerificationStatus.VALID

    def _referenced_spec(self, test: TestRecord):
        """定位测试登记时所依据的规格版本。

        优先按 test.spec_version 精确定位；未记录版本时回退到最新版本。
        """
        if test.spec_version:
            return self._registry.get_spec(test.spec_ref, test.spec_version)
        return self._registry.get_spec(test.spec_ref)

    def evaluate_with_reason(
        self, test: TestRecord, test_text: str = "",
        current_hashes: Optional[dict] = None,
    ) -> tuple:
        """判定并返回 (status, reason, detail)。

        current_hashes: {path: sha256}，磁盘上代码文件当前的真实指纹。
        """
        reg = self._registry
        spec = self._referenced_spec(test)

        if spec is None or spec.status != SpecStatus.ACTIVE:
            state = spec.status.value if spec else "缺失"
            why = (
                f"验证依据的规格 {test.spec_ref}"
                f"{'@' + test.spec_version if test.spec_version else ''} 已失效"
                f"（状态 {state}），按旧规格做的验证不适用于当前需求"
            )
            return VerificationStatus.INVALID, why, {}

        detail: dict = {}
        if test_text:
            used = self.extract_symbols(test_text)
            declared = self._active_contract_symbols()
            missing = sorted(used - declared)
            if missing:
                why = (
                    f"测试引用的接口符号 {missing} 已不在当前有效契约中，"
                    f"契约已变更，该验证不再适用（需按新契约更新测试）"
                )
                return VerificationStatus.INVALID, why, {"missing_symbols": missing}

        changed_files: List[str] = []
        for path in test.covered_files:
            snap = reg.get_code_snapshot(path)
            current = (current_hashes or {}).get(path)
            if current is None:
                changed_files.append(path)
            elif snap is None or snap.sha256 != current:
                changed_files.append(path)

        if changed_files:
            why = (
                f"测试覆盖的代码文件已变更：{changed_files}。"
                f"先前验证结果可能过期，需重新运行后再采信"
            )
            return VerificationStatus.STALE, why, {"changed_files": changed_files}

        why = "依据的规格有效、契约未变、覆盖代码未变，先前验证结果可直接采信"
        return VerificationStatus.VALID, why, {}
