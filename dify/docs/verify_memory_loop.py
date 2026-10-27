# -*- coding: utf-8 -*-
"""PowerContext 记忆闭环验证脚本（模拟 Dify 工作流的三个 HTTP 节点）
运行：powershell 执行，或 python 本脚本
输出：scope 创建、记忆写入、记忆召回的完整记录
"""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"
CONV = "demo-conv-001"  # 模拟一个 Dify 会话 conversation_id


def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


print("=== 步骤 1：建 Scope（对应 Dify「建Scope」HTTP 节点） ===")
scope = post(
    "/v1/scopes",
    {
        "title": "雾谷镇旅人会话",
        "summary": "雾谷镇守夜人老钟与旅人的对话记忆（按会话隔离）",
        "idempotency_key": f"fogvalley-{CONV}",
    },
)
scope_id = scope["scope_id"]
print("scope_id:", scope_id)
print()

print("=== 步骤 2：写入记忆（对应 Dify「写记忆」HTTP 节点） ===")
memories = post(
    "/v1/memory/remember",
    {
        "scope_id": scope_id,
        "kind": "promise",
        "text": "[承诺] 旅人对老钟说：「老钟，明天我帮你把东门的风灯修亮，说到做到」（老钟默默记下）。",
        "reason": "Extracted from player chat in Dify workflow",
    },
)
print("written records:", json.dumps(memories, ensure_ascii=False)[:300])
print()

print("=== 步骤 3：召回记忆（对应 Dify「读记忆」HTTP 节点） ===")
prepared = post(
    "/v1/context/prepare",
    {"scope_id": scope_id, "query": "修风灯 承诺", "max_bytes": 2000},
)
print("status:", prepared.get("status"))
print("content:", prepared.get("content"))
