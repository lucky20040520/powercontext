---
title: 配置向量检索
description: 启用基于 embedding 的 vector 和 hybrid Memory 检索，并验证 Runtime capability。
---

# 配置向量检索

向量检索需要 embedding model、稳定的 profile ID 和该模型的输出 dimension。

## 1. 设置一份 embedding profile

```bash
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_MODEL=provider:embedding-model
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_PROFILE_ID=embedding-model-v1
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_DIMENSION=1024
```

将示例值替换为一个受支持的 provider model、该模型保持稳定的 profile ID，以及其文档给出的输出 dimension。
`POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_NORMALIZATION` 默认值为 `unit`。

输出维度始终要配置，它决定本地向量索引的宽度，并用来校验模型返回的向量。默认还会把这个值作为请求参数 `dimensions` 发给模型。有些 OpenAI 兼容服务不接受该参数，例如硅基流动上的 `BAAI/bge-m3`。这类模型保留文档中的输出维度（bge-m3 为 1024），并关闭发送：

```bash
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_SEND_DIMENSIONS=false
```

## 2. 启动 Server

```bash
powercontext server run
```

使用 SQLite 时，PowerContext 会在打开数据库时加载内置 sqlite-vec extension。extension 与当前 platform 或 SQLite build
不兼容时，启动会失败。

## 3. 验证 capability

```bash
powercontext capabilities
```

结果会报告已启用的 search mode。未配置 embedding profile 时，SQLite full-text search 仍可使用。

能力标记只说明 Runtime 已加载向量通道，还需要用一条合成 Source 验证模型调用、索引写入和实际命中。完整的
Source → flush → entry → vector search 验收命令见[启用 Memory 提取与向量搜索](../get-started/configure-models.md)。
其中搜索响应必须包含 `mode: "vector"`、目标 `entry_id`，并且 `matched_by` 包含 `vector`；如果使用 `hybrid`，应把请求
中的 `mode` 改为 `hybrid` 并核对实际返回模式。显式 `vector`/`hybrid` 不会在 Embedding 不可用时静默降级。

如果在已有 Memory 上首次启用 Embedding，先用一条临时 Scope 完成上述闭环，再对真实 Scope 运行受控的重处理/索引流程，
并确认旧 citation 没有变化。不要仅修改 profile ID 或 dimension 来绕过已有向量与模型不匹配的错误。

timeout、batch size、storage 设置和准确默认值见[配置](../operate/configuration.md)。

## seekdb 原生混合候选查询

配置 seekdb 后端和 embedding profile 后，`Memory.search(mode="hybrid")` 在已有连接上通过一条 SQL 获取两路
有序候选。每路查询都在数据库内应用 Scope、请求的 Memory artifact、可选标签条件和独立候选上限，使用原生全文索引
和 HNSW 向量索引。后续候选准入与倒数排名融合仍由 Memory 服务负责。

单 statement 保证只覆盖候选检索。当前 head 校验、向量完整性校验和精确正文读取仍是独立操作。增量投影无需为了更新
head revision 而重写所有条目：返回引用采用请求中已经验证的当前 Memory head，以及命中的 entry version。正文修订、
停用、恢复和投影重建继续使用现有事务写入流程。

此功能无需新增配置或迁移 schema。全文单通道和向量单通道沿用原路径，OceanBase 和 SQLite 保持各自后端行为。
减少候选 SQL 数量本身不代表端到端加速或语义检索质量提升，需要使用实际语料和向量模型测量。
