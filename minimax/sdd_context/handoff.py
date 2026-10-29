# -*- coding: utf-8 -*-
"""
sdd_context.handoff
===================
跨会话与任务交接（Handoff）支持。

会话天然是无状态的：一个会话里沉淀的规格、决策、代码指纹与验证状态，
在会话关闭后就会丢失。本模块提供：

1. export_snapshot()  —— 把注册表的完整演进历史导出为 JSON；
2. import_snapshot()  —— 在新会话中重建注册表，恢复全部上下文；
3. reconcile()        —— 把“磁盘上真实的代码”与登记状态对齐：
   - 计算每个相关代码文件的当前 sha256；
   - 与登记快照比较，更新快照；
   - 返回代码变更清单（可据此把相关验证标记为 stale）。

交接后的新会话，对同一任务调用 assemble() 得到与旧会话一致且
“当前有效”的上下文 —— 这正是题目要求的跨会话能力。
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Dict, List, Tuple

from .registry import SpecRegistry


class HandoffManager:
    """负责注册表快照的导出、导入与代码状态对账。"""

    def __init__(self, registry: SpecRegistry) -> None:
        self._registry = registry

    # ------------------------------------------------------------------
    # 导出 / 导入
    # ------------------------------------------------------------------
    def export_snapshot(self) -> Dict[str, Any]:
        """导出当前工程上下文快照（含全部规格历史、决策、测试与代码指纹）。"""
        return {
            "schema": "sdd-context-handoff-v1",
            "registry": self._registry.to_dict(),
        }

    def export_json(self) -> str:
        return json.dumps(self.export_snapshot(), ensure_ascii=False, indent=2)

    @staticmethod
    def import_snapshot(payload: Dict[str, Any]) -> SpecRegistry:
        """从快照重建注册表（新会话入口）。"""
        return SpecRegistry.from_dict(payload["registry"])

    # ------------------------------------------------------------------
    # 磁盘对账：发现真实代码变更
    # ------------------------------------------------------------------
    @staticmethod
    def digest_file(path: str) -> str:
        """计算磁盘上某个文件当前内容的 sha256（文件缺失返回空串）。"""
        try:
            with open(path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except OSError:
            return ""

    def current_hashes(self, paths: List[str]) -> Dict[str, str]:
        """批量计算代码文件当前指纹。"""
        return {p: self.digest_file(p) for p in paths}

    def reconcile(self, paths: List[str]) -> List[Tuple[str, str, str]]:
        """对账：返回 [(path, registered_sha, current_sha)] 中已变更的项。

        对账本身不修改注册表；调用方拿到变更清单后，
        可决定是否 record_code() 更新快照并标记测试 stale。
        """
        changed: List[Tuple[str, str, str]] = []
        for p in paths:
            current = self.digest_file(p)
            snap = self._registry.get_code_snapshot(p)
            registered = snap.sha256 if snap else ""
            if snap is None or registered != current:
                changed.append((p, registered, current))
        return changed
