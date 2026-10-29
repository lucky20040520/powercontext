# -*- coding: utf-8 -*-
"""
sdd_context.powercontext_bridge
================================
与 PowerContext（AI 开发助手的上下文底座）的可选对接层。

PowerContext 以 MCP 提供 create_scope / remember_memory / search_memory /
handoff_current_work 等工具。本桥接层做两件事：

1. 落库：把“规格登记 / 决策失效 / 测试判定”的关键事实作为 memory
   （kind=constraint / decision）写入 PowerContext Server，使事实跨
   会话被 AI 开发助手无感召回；
2. 召回：组装任务上下文前，先从 PowerContext 检索历史决策与约束，
   再叠加本地注册表结果。

本模块不依赖第三方库（只用 urllib），且对 PowerContext 不可用的情况
完全优雅降级 —— 模块主体（注册表/判定/组装/交接）始终可独立运行。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .registry import SpecRegistry


class PowerContextBridge:
    """PowerContext Server 的极简 HTTP 客户端（Streamable HTTP 之上的
    JSON-RPC 风格调用；仅用于可选增强，失败不影响主流程）。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        scope_id: Optional[str] = None,
    ) -> None:
        self.base_url = base_url or os.environ.get(
            "POWERCONTEXT_SERVER_URL", "http://127.0.0.1:8000"
        )
        self.token = token or os.environ.get("POWERCONTEXT_SERVER_AUTH_TOKEN", "")
        self.scope_id = scope_id or os.environ.get("POWERCONTEXT_SCOPE_ID", "")
        self._available: Optional[bool] = None

    # ------------------------------------------------------------------
    # 服务可用性
    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        """探测 PowerContext Server 是否可达（结果缓存）。"""
        if self._available is not None:
            return self._available
        try:
            with urllib.request.urlopen(
                f"{self.base_url}/health/live", timeout=2
            ) as resp:
                self._available = resp.status == 200
        except Exception:
            self._available = False
        return self._available

    # ------------------------------------------------------------------
    # 落库：把工程上下文事实写入 PowerContext 记忆
    # ------------------------------------------------------------------
    def remember(
        self,
        content: str,
        kind: str = "decision",
        scope_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """写入一条记忆。kind: decision / constraint / progress 等。"""
        if not self.is_available():
            return {"ok": False, "reason": "powercontext server unavailable"}
        payload = {
            "method": "tools/call",
            "params": {
                "name": "remember_memory",
                "arguments": {
                    "kind": kind,
                    "content": content,
                    "scope_id": scope_id or self.scope_id,
                },
            },
        }
        return self._post(payload)

    def remember_registry_state(self, registry: SpecRegistry) -> List[Dict[str, Any]]:
        """把注册表当前关键事实批量落库（active 规格 + 失效决策 + 过期测试）。"""
        results: List[Dict[str, Any]] = []
        for spec in registry.active_specs():
            results.append(
                self.remember(
                    f"[规格 {spec.kind.value}] {spec.id}@{spec.version}: "
                    f"{spec.content.strip()}",
                    kind="constraint",
                )
            )
        for dec in registry.retired_decisions():
            results.append(
                self.remember(
                    f"[已失效决策] {dec.id}: {dec.content.strip()}（失效）",
                    kind="decision",
                )
            )
        return results

    # ------------------------------------------------------------------
    # 召回：从 PowerContext 检索历史决策
    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """检索历史记忆（决策/约束），供组装前补充。"""
        if not self.is_available():
            return []
        payload = {
            "method": "tools/call",
            "params": {
                "name": "search_memory",
                "arguments": {
                    "query": query,
                    "limit": limit,
                    "scope_id": self.scope_id,
                },
            },
        }
        resp = self._post(payload)
        return resp.get("result", [])

    # ------------------------------------------------------------------
    # 底层 HTTP
    # ------------------------------------------------------------------
    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/mcp"
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            return {"ok": False, "reason": str(exc)}
