# -*- coding: utf-8 -*-
"""DSL 结构校验脚本：节点类型、连线完整性、变量引用。"""
import yaml

p = r"C:\Users\wh-yin\Doubao\chats\2026-10-27\new-chat\powercontext\dify\workflows\雾谷镇夜话_守夜人老钟.yml"
d = yaml.safe_load(open(p, encoding="utf-8"))
g = d["workflow"]["graph"]
nodes = {n["id"]: n["data"].get("type") for n in g["nodes"]}
print("NODE_TYPES:", {k: v for k, v in nodes.items()})
print()
ok = True
for e in g["edges"]:
    src, tgt = e["data"]["source"], e["data"]["target"]
    s_ok = src in nodes
    t_ok = tgt in nodes or tgt == "answer"
    ok = ok and s_ok and t_ok
    print(f"{src}({nodes.get(src)}) -> {tgt}({nodes.get(tgt)})", "OK" if s_ok and t_ok else "BROKEN")
print("\nEDGES_ALL_OK:", ok)
s = open(p, encoding="utf-8").read()
print()
for ref in [
    "{{#sys.conversation_id#}}",
    "{{#sys.query#}}",
    "{{#n_code_scope.scope_id#}}",
    "{{#n_code_read.memory_text#}}",
    "{{#n_code_event.kind#}}",
    "{{#n_code_event.text#}}",
    "{{#env.POWERCONTEXT_URL#}}",
    "{{#n_llm_npc.text#}}",
]:
    print(ref, "FOUND" if ref in s else "MISSING")
