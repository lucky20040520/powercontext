---
title: Sources 与采集
description: 采集证据、查看 Source 记录并配置后续处理。
---

# Sources 与采集

Sources 在信息被筛选为知识之前保留证据。Content Source 保存采集的文本，其他 Source 类型可引用 Connector 提供的材料。
Work Contract 和 Task Outcome 也会保留 Source 证据。

## 采集与检查

1. 选择已有 Scope。[API Quick Start](../develop/api-quickstart.md)演示通过 `POST /v1/sources/content` 采集内容，
   并保留返回的 Source 引用。
2. 使用 `GET /v1/scopes/{scope_id}/sources` 浏览 Source journal，再通过
   `GET /v1/scopes/{scope_id}/sources/{source_type}/{source_id}` 读取选中的 Source。
3. 将符合条件的证据处理为 Memory，需要配置生成模型，并启用定时处理、Source 数量门槛或显式执行 Memory flush。
   步骤见[启用提取与向量搜索](../get-started/configure-models.md)。

采集成功表示证据已保存，不表示提取成功，也不表示内容一定值得长期保留。
通过 Source 引用追溯生成结果的输入。不要在同一身份下修改内容并重试采集，将其当作新的观察。

## 选择采集入口

- Agent Prompt Hook：在[接入指南](../integrations/index.md)中选择宿主对应的采集开关。
- 文件与对象存储：使用 [OpenDAL Connector](ingest-text-files-with-opendal.md)。
- Scope Profile 的主体证据：按 [Scope Profile](use-profiles.md)写入。
- 应用或评测事件：使用应用对应适配器；[Bub 采集](../integrations/evaluation.md)需要显式启用。

Source 读写受所选 [Scope 与访问策略](scopes-and-access.md)约束。

## 按新增 Source 数量启动处理

在 `RuntimeConfig` 中分别设置严格的正整数门槛：

```python
from powercontext.builtin.runtime import RuntimeConfig

runtime_policy = RuntimeConfig(
    memory_source_count_threshold=3,
    topic_memory_source_count_threshold=5,
    source_window_limit=1,
    topic_memory_source_window_limit=2,
)
```

两个门槛默认均为 `None`，表示关闭数量触发。Python 配置拒绝布尔值、字符串、浮点数、零和负数。
Server 环境变量使用十进制整数文本，例如 `POWERCONTEXT_SERVER_RUNTIME_MEMORY_SOURCE_COUNT_THRESHOLD=3`
和 `POWERCONTEXT_SERVER_RUNTIME_TOPIC_MEMORY_SOURCE_COUNT_THRESHOLD=5`。仍需配置生成服务并启用对应处理族。
通过 HTTP、MCP 采集的 Source 同样受这些配置控制；采集完成即返回，生成在后台异步执行。

每个 Scope、每个处理族独立计数：已提交的 Source journal 末尾位置减去该处理族最后一次成功提交的 cursor。
重复采集同一身份、升级已有 receipt 的信任信息都不增加条目。仅供 lineage 使用的 Source 参与启动计数，
但仍不会进入生成证据。原生 supervisor 分页检查待处理元数据，每完成一轮检查后等待一秒。
检查不读取 Source 正文，也不调用模型；工作量随脏 Scope 数量增长，其中包含尚未达到门槛的 Scope。

数量条件与时间条件独立，任一满足即可启动；显式调用 Memory 或 Topic Memory 的 `flush()` 也会绕过门槛。
例如 Memory 门槛为 3、`source_window_limit=1` 时，三个新条目只启动一窗；剩余两个等待另一个新条目、
定时条件或显式 flush。Topic Memory 已接受的 wave 会继续完成全部分窗，下一 wave 才重新应用门槛。

已接受的工作沿用现有重试机制，发布失败不会推进成功 cursor。重开同一数据库仍会保留待处理条目和已接受请求，
成功处理后照常提供可检索结果和精确 Source 引用。数量检查不会重置定时调度的 checkpoint。

## 在 Python 中逐行采集 CSV

使用 `powercontext.sources.csv_rows` 将每条 CSV 记录采集为独立 Source。解析完全离线，不调用模型或网络服务。
传入完整 UTF-8 字节内容、稳定的文档 ID，以及精确匹配表头的主键列名：

```python
from powercontext.builtin.runtime import SubmitSourceObservation
from powercontext.sources import (
    SourceDefinitionRegistry,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.csv_rows import (
    CSV_ROW_SOURCE_DEFINITION,
    CSVDocumentInput,
    parse_csv_document,
)


async def capture_csv(runtime, scope_id: str, csv_bytes: bytes) -> None:
    rows = parse_csv_document(
        CSVDocumentInput(document_id="airports", primary_key="id", content=csv_bytes)
    )
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    await runtime.ingestion.register(manifest_for_definition(CSV_ROW_SOURCE_DEFINITION))
    for row in rows:
        source = await registry.resolve(row)
        observation = project_source_for_transport(registry, source)
        await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope_id, observation=observation))
```

`parse_csv_document` 先验证整个文档，再返回 tuple。支持文件开头的 UTF-8 BOM、引号内的逗号、双引号转义和多行字段。
忽略表头之后的完全空物理记录；只有表头的文档返回 `()`。编码、引号、表头、字段宽度、缺失或重复主键，以及 Source
身份长度不合法时均抛出 `ValueError`。解析失败不会返回部分行；后续各条 Runtime 提交是独立写入。

列名和字段值保留原始字符串及顺序。列名必须唯一且非空白；`primary_key` 必须精确匹配列名，包括首尾空格。
文档 ID 必须非空且没有首尾空白。主键值不能是空字符串或纯空白，非空主键首尾的空白仍有意义。

每行形成类型为 `csv-row`、定义版本为 `1` 的 captured Source，身份格式为
`csv:{编码后的 document_id}:{编码后的 primary_key_value}`。两个组件分别使用
`urllib.parse.quote(value, safe="")` 编码，完整身份最多 256 个字符。重排行或修改非主键字段不会改变该行的逻辑 ID。
复用已采集身份仍受现有 ingestion 规则约束，此适配器没有新增更新 API。

`powercontext.text-evidence` 投影将整行表示为按原列顺序排列的紧凑 JSON 对象。metadata 恰好包含
`document_id`、`primary_key`、`primary_key_value`、`columns` 和 `row` 五个键；空字段、数字文本等所有值均保留为字符串。
注册 manifest 并提交 observation 后，Runtime 重启仍能读取相同证据。配置好的 Memory pipeline 可以消费该投影，
检索命中的精确 `MemoryCitation` 可回查对应的 Memory 条目与 Source 引用。CSV 解析和采集本身不负责配置提取流程。
