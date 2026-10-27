---
title: 保存与召回 Memory
description: 保存项目决策、检索相关历史并纠正过时 Memory。
---

# 保存与召回 Memory

Memory 保存持久的决策、约束和事实。PreparedContext 为单次请求筛选相关历史，属于临时结果，不会再创建一条 Memory。

## 保存、召回与纠正

1. 完成 [Quick Start](../get-started/quickstart.md)，让不同会话解析到相同 Scope。
2. 显式请 Agent 保存信息。直接调用 `remember_memory` 不需要模型。
3. 使用 `search_memory` 搜索，或在宿主提供对应工具时用 `list_memory_entries` 和 `get_memory_entry` 检查条目。
   引用结果时保留返回的 citation。
4. 使用当前 citation 修订错误信息，或退役不应继续召回的信息。退役会将条目移出活跃召回范围，同时保留历史。

各宿主工具名称不同，见[接入 Agent](../integrations/index.md)。完整请求结构和并发要求见 [HTTP API](../develop/http-api.md)。

FTS 的候选检索和准入使用相同的查询词。查询归一化会排除较长查询中的常见英语虚词，并识别问题前后独立的执行指令，
例如“Use only supplied context”和“Do not call tools, read files, inspect old sessions, or delegate”。
这些指令不能为无关事实提供匹配依据。显式加引号的词始终参与检索，包括 `"AND" "OR" precedence` 中作为标识符的虚词。
包含领域信息的指令和未识别的措辞仍参与检索；这是一项保守的词项规则，
并非通用意图分类器。默认准入要求匹配剩余全部不同查询词的 25%，至少两个；只有一两个词的查询要求匹配一个词。
直接搜索和上下文准备使用相同规则，可选的 recall gate 放宽门槛时也如此。存储文本和向量查询保持不变，
词语重合本身不能证明语义相关。

## 撤回与恢复已注册的证据

Python 内置 Runtime 通过 `runtime.lifecycle.for_scope(scope_id)` 管理显式、注册后不改写的依赖 DAG。
绑定已采集的 `SourceRef`、可读取的 `MemoryCitation` 和 Topic Memory 的 `ArtifactRef`：

```python
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleEvent


async def withdraw_evidence(runtime, scope_id, source_ref, citation, topic_ref):
    service = runtime.lifecycle.for_scope(scope_id)
    await service.register_source("source-a", source_ref, revision=3)
    await service.register_memory("memory-a", citation, parents=("source-a",), policy="all")
    await service.register_topic("topic-a", topic_ref, parents=("memory-a",), policy="any")
    return await service.apply(
        SourceLifecycleEvent(node_id="source-a", revision=3, sequence=1, available=False, reason="来源已撤回")
    )
```

节点编号在 Scope 内唯一。相同注册幂等，不同绑定冲突；每个原生 Source、逻辑 Memory 条目或 Topic 身份对应一个节点。
父节点必须先注册，派生节点至少有一个不重复的父节点。`all` 要求全部父节点可用；`any` 表示任一父节点能够独立支持整份正文。
若正文含多个独立断言，应拆分节点或使用 `all`。注册立即按父节点当前状态计算资格，包括来源已经撤回的情况。
每个 Scope 使用单写者；绑定期间不要外部改写已注册的 Memory 正文版本。

事件要求节点编号和原因是非空白字符串、版本和序号是严格正整数、可用状态是严格布尔值，并拒绝额外字段。
只有 Source 节点接受事件，生命周期版本必须与注册值完全相同。序号按每个 Source 递增；重放最近一次相同事件幂等，
更低序号或同序号不同内容抛出 `SourceLifecycleError`。恢复时发送更高序号且 `available=True` 的事件。

传播将图状态、事件和原生 Memory 状态更新放在同一事务中。原生写入失败时全部回滚，排除故障或重开数据库后可重试同一事件。
成功事件重放不新增 Memory 修订。Memory 停用保留正文版本，并退出普通搜索和 PreparedContext；
失去支持的 Topic 在浏览、全文搜索、向量搜索和 Context 中被过滤，过滤发生在候选截断之前，原有投影和精确修订仍可供审计。

`await service.resolve(node_id, purpose="generation")` 仅在节点可用时返回原始引用；`purpose="audit"` 允许返回撤回前的原始引用。
未知节点或用途抛出 `SourceLifecycleError`。`apply()` 按编号排序返回全部可用节点，包括 Source。
绑定及状态在同一数据库重启后保留，不同 Scope 互不影响。

更新读取一个 Scope 的图，并以节点数和边数之和的线性成本计算状态；原生 Memory 发布仍承担既有 manifest 和索引成本。
引用解析使用键查询。Topic 资格按 Scope、Topic 和状态索引查询，不重写历史正文。
SQLite 行为由真实持久化测试覆盖；OceanBase/seekdb 的实际执行需运行相应外部后端测试。

依赖图管理通过 Python Runtime API 提供。已有 HTTP/MCP 搜索和 Context 接口会读取持久化状态，未新增 HTTP/MCP 图管理入口。

## 自动上下文与提取

召回 Hook 向 Server 请求有大小上限的 PreparedContext。没有相关信息时返回 `empty` 是正常结果。
历史内容不能覆盖当前指令或项目现状。

按[输出标准上下文文本](prepare-context-text.md)选择 Memory、Experience、Profile 和 Topic Memory，
设置输出顺序、各类别条数及总条数上限。

采集 Prompt 会创建 Source 证据，不保证提取出 Memory。按[模型配置](../get-started/configure-models.md)
启用生成模型与 Source 处理；只有需要[向量或混合搜索](configure-vector-search.md)时才配置 Embedding。
记录项目信息前，检查宿主的 Prompt 采集开关。

Topic Memory 有独立的处理与检索入口，包括 MCP 的 `search_topic_memory` 和 `get_topic_memory`。
基本的显式 Memory 写入不会启用 Topic Memory；相关设置和运行时能力见[配置](../operate/configuration.md)。

交接当前任务边界使用 [Handoff](memory-and-handoff.md)，保留原始证据使用 [Sources](sources.md)。
