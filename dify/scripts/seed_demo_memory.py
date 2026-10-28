# -*- coding: utf-8 -*-
"""预置演示记忆：往一个演示会话写入 3 条老钟记忆，便于评审演示"老钟记得旧事"。
用法：python scripts/seed_demo_memory.py
前置：PowerContext Server 已启动（http://127.0.0.1:8000）。
输出：演示 scope_id；可用 docs/节点执行记录.md 中 5.1 的 curl 召回核对。
"""
import json
import urllib.request

BASE = "http://127.0.0.1:8000"
DEMO_KEY = "fogvalley-demo-seed-20261028"

MEMORIES = [
    ("promise", "[承诺] 旅人对老钟说：「老钟，明天我帮你把东门的风灯修亮，说到做到」（老钟默默记下）。"),
    ("prank", "[恶作剧] 旅人骗老钟「山那头有狼」，害老钟白守了一夜，结果连个狼毛都没有。"),
    ("help", "[帮忙/馈赠] 旅人送老钟一壶热酒，老钟嘴上嫌酒劲不够，心里记下了这份情。"),
    ("preference", "[私事] 旅人说自己怕黑，走夜路都得打灯。"),
]


def post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    print("==> 建演示 Scope ...")
    scope = post(
        "/v1/scopes",
        {
            "title": "雾谷镇演示会话（预置记忆）",
            "summary": "用于评审演示：老钟已记得这位旅人的旧账",
            "idempotency_key": DEMO_KEY,
        },
    )
    scope_id = scope["scope_id"]
    print("scope_id:", scope_id)

    for kind, text in MEMORIES:
        r = post(
            "/v1/memory/remember",
            {
                "scope_id": scope_id,
                "kind": kind,
                "text": text,
                "reason": "Pre-seeded demo memory for evaluation",
            },
        )
        print(f"  [{kind}] changed={r.get('changed')}")

    print("\n完成。在 Dify 调试页开新会话聊几句后，可用以下命令核对记忆：")
    print(f'curl -s -X POST {BASE}/v1/context/prepare -H "Content-Type: application/json" '
          f'-d \'{{"scope_id":"{scope_id}","query":"风灯 热酒 怕黑","max_bytes":3000}}\'')


if __name__ == "__main__":
    main()
