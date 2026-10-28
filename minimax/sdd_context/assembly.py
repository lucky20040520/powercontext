# -*- coding: utf-8 -*-
"""
sdd_context.assembly
====================
任务上下文组装器（ContextAssembler）。

回答题目的核心问题之一：“AI 开发助手根据开发任务，应当拿到什么上下文？”

组装流程：
1. 对任务描述做关键词提取（中文与英文关键词）；
2. 用关键词匹配当前所有 active 的规格（标题 / 正文），得到适用规格；
3. 由适用规格的 linked_files 得到相关代码，由 linked_tests 得到相关测试；
4. 对每条相关测试调用 ValidityEngine 判定有效性，区分
   relevant（valid）/ stale（需重跑）/ invalid（不再适用）；
5. 收集与该任务相关的、已经失效的决策（retired_decisions）作为警示；
6. 输出 TaskContext —— 可直接注入 AI 助手的 prompt。

关键保证：TaskContext 中绝不包含 superseded / retired 的规格，
避免 AI 开发助手遵守已失效的要求。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from .model import (
    DecisionRecord,
    SpecKind,
    SpecVersion,
    TaskContext,
    TestRecord,
    VerificationStatus,
)
from .registry import SpecRegistry
from .validity import ValidityEngine


class ContextAssembler:
    """把注册表 + 判定引擎组合为按任务检索的上下文服务。"""

    def __init__(self, registry: SpecRegistry, engine: ValidityEngine) -> None:
        self._registry = registry
        self._engine = engine

    # ------------------------------------------------------------------
    # 关键词提取
    # ------------------------------------------------------------------
    _EN_TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_\-]{1,}")
    _CN_SEQ_RE = re.compile(r"[\u4e00-\u9fff]+")

    @staticmethod
    def extract_keywords(task: str) -> List[str]:
        """从任务描述中提取检索关键词。

        - 英文标识符（如 compute_price、discount）整体作为强关键词；
        - 中文按 2/3-gram 切分（如「折扣码」→ 折扣、折扣码），
          使关键词能与规格正文做子串匹配。
        """
        tokens: List[str] = list(ContextAssembler._EN_TOKEN_RE.findall(task))
        # 中文 n-gram
        for seq in ContextAssembler._CN_SEQ_RE.findall(task):
            for n in (3, 2):
                for i in range(0, len(seq) - n + 1):
                    tokens.append(seq[i:i + n])
        seen: set = set()
        result: List[str] = []
        for t in tokens:
            key = t.lower()
            if key not in seen:
                seen.add(key)
                result.append(t)
        return result

    # kind 的展示/排序优先级（同分时固定顺序）
    _KIND_ORDER = {
        SpecKind.REQUIREMENT: 0,
        SpecKind.CONTRACT: 1,
        SpecKind.DECISION: 2,
        SpecKind.TEST_PLAN: 3,
    }

    def _score_spec(self, spec: SpecVersion, keywords: List[str]) -> int:
        """规格与任务的相关度打分（标题匹配权重 3，正文匹配权重 1）。"""
        text = f"{spec.id} {spec.version} {spec.kind.value} {spec.content}".lower()
        title = f"{spec.id} {spec.version} {spec.kind.value}".lower()
        score = 0
        for kw in keywords:
            k = kw.lower()
            if k in title:
                score += 3
            elif k in text:
                score += 1
        return score

    # ------------------------------------------------------------------
    # 组装入口
    # ------------------------------------------------------------------
    def assemble(
        self,
        task: str,
        current_hashes: Optional[Dict[str, str]] = None,
    ) -> TaskContext:
        """根据任务描述组装当前有效的工程上下文。

        current_hashes: {path: sha256} 磁盘上代码当前指纹（可选），
        用于把“代码已变更”反映为 stale 测试。
        """
        reg = self._registry
        keywords = self.extract_keywords(task)

        # 1. 匹配当前有效规格
        candidates: List[SpecVersion] = []
        for spec in reg.active_specs():
            score = self._score_spec(spec, keywords)
            if score > 0:
                candidates.append(spec)
        # 按相关度降序；同分按 kind 固定顺序，保证渲染稳定
        candidates.sort(
            key=lambda s: (
                -self._score_spec(s, keywords),
                self._KIND_ORDER.get(s.kind, 9),
                s.id,
            ),
        )

        ctx = TaskContext(task=task)
        ctx.active_specs = candidates

        # 2. 相关代码：来自适用规格的 linked_files（去重、保序）
        code_files: List[str] = []
        seen_code: set = set()
        for spec in candidates:
            for f in spec.linked_files:
                if f not in seen_code:
                    seen_code.add(f)
                    code_files.append(f)
        ctx.relevant_code = code_files

        # 3. 相关测试：来自适用规格的 linked_tests，并判定有效性
        seen_test: set = set()
        for spec in candidates:
            for t_path in spec.linked_tests:
                if t_path in seen_test:
                    continue
                seen_test.add(t_path)
                test = reg.get_test(t_path)
                if test is None:
                    continue
                status, _reason, _detail = self._engine.evaluate_with_reason(
                    test,
                    test_text=_read_test_text(t_path),
                    current_hashes=current_hashes,
                )
                if status == VerificationStatus.INVALID:
                    ctx.invalid_tests.append(test)
                elif status == VerificationStatus.STALE:
                    ctx.stale_tests.append(test)
                else:
                    ctx.relevant_tests.append(test)

        # 4. 与该任务相关的失效决策（警示，不进入“应遵守”集合）
        #    匹配规则：决策关联的服务名与候选规格 id 完全一致，或共享
        #    语义前缀（如 "discount-service" 匹配 "discount-requirements"）。
        related_spec_ids = {s.id for s in candidates}

        def _related_to_candidates(related_spec: Optional[str]) -> bool:
            if not related_spec:
                return False
            if related_spec in related_spec_ids:
                return True
            prefix = related_spec.split("-")[0]
            return any(sid.split("-")[0] == prefix for sid in related_spec_ids)

        for dec in reg.retired_decisions():
            if _related_to_candidates(dec.related_spec):
                ctx.retired_decisions.append(dec)

        # 5. 组装警示
        if ctx.invalid_tests:
            ctx.warnings.append(
                "以下验证已不再适用于当前代码（规格/契约已变更，须更新测试）："
                + ", ".join(t.path for t in ctx.invalid_tests)
            )
        if ctx.stale_tests:
            ctx.warnings.append(
                "以下验证覆盖的代码已变更，结果可能过期，须重新运行："
                + ", ".join(t.path for t in ctx.stale_tests)
            )
        if ctx.retired_decisions:
            ctx.warnings.append(
                "以下决策已失效，不得作为本次任务的依据："
                + ", ".join(d.id for d in ctx.retired_decisions)
            )
        if not candidates:
            ctx.warnings.append(
                "未检索到与任务匹配的当前有效规格，请补充需求规格后再开工"
            )

        return ctx

    def render_prompt(self, ctx: TaskContext) -> str:
        """把 TaskContext 渲染为可直接注入 AI 开发助手的提示文本。"""
        lines: List[str] = []
        lines.append(f"# 工程上下文：{ctx.task}")
        lines.append("")
        lines.append("## 当前必须遵守的规格（唯一有效要求）")
        if ctx.active_specs:
            for s in ctx.active_specs:
                lines.append(f"- [{s.kind.value}] {s.id}@{s.version}（{s.status.value}）")
                lines.append(f"  {s.content.strip()}")
        else:
            lines.append("- （无）")
        lines.append("")
        lines.append("## 相关代码")
        if ctx.relevant_code:
            lines.extend(f"- {f}" for f in ctx.relevant_code)
        else:
            lines.append("- （无）")
        lines.append("")
        lines.append("## 可采信的验证（仍适用于当前代码）")
        if ctx.relevant_tests:
            lines.extend(f"- {t.path}" for t in ctx.relevant_tests)
        else:
            lines.append("- （无）")
        lines.append("")
        lines.append("## 需重新运行的验证（代码已变更）")
        lines.extend(f"- {t.path}" for t in ctx.stale_tests) or lines.append("- （无）")
        lines.append("")
        lines.append("## 已失效、不得使用的验证（规格/契约已变更）")
        lines.extend(f"- {t.path}" for t in ctx.invalid_tests) or lines.append("- （无）")
        lines.append("")
        lines.append("## 已失效的决策（不得作为依据）")
        lines.extend(f"- {d.id}: {d.content}" for d in ctx.retired_decisions) or lines.append("- （无）")
        lines.append("")
        if ctx.warnings:
            lines.append("## 警示")
            lines.extend(f"- {w}" for w in ctx.warnings)
        return "\n".join(lines)


def _read_test_text(path: str) -> str:
    """读取测试文件正文（用于契约符号提取；文件缺失时返回空串）。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""
