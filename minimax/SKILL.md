---
name: sdd-context-management
description: "面向软件持续演进的规格驱动开发（SDD）工程上下文模块。当 AI 开发助手需要判断当前任务应遵守什么规格/契约、哪些历史决策已失效、先前验证是否仍适用于当前代码，或需要在跨会话/任务交接时携带项目上下文时使用。提供：按任务检索当前有效规格与相关代码/测试（valid/stale/invalid 分级）、失效决策警示、快照交接与磁盘对账。纯 Python 标准库实现，无第三方依赖。"
---

# SDD 工程上下文管理（规有所依）

本模块为 AI 开发助手解决一个持续演进项目中的根本问题：

> 项目里需求规格、接口契约、设计决策、代码、测试都在变，
> 我凭什么相信自己拿到的要求、决策和验证结果还是“当前有效”的？

## 何时使用

- 开发助手开始一个新任务，需要知道“应该遵守哪些要求”（有效规格 + 相关代码 + 相关测试）；
- 任务涉及历史决策，需要知道“哪些决策已失效、不能再作为依据”；
- 改动代码/规格后，需要知道“哪些先前验证还能采信、哪些必须重跑、哪些已作废”；
- 跨会话、交接给另一个助手时，需要把“当前有效的知识状态”完整带过去。

## 核心概念

- **规格 SpecVersion**：需求的唯一事实来源。有状态机
  `active → superseded / retired`。新版本登记时，旧 active 版自动 superseded。
- **决策 DecisionRecord**：设计决策，可被规格失效**级联失效**。
- **代码快照 CodeSnapshot**：登记时的 SHA-256 指纹，用于检测代码是否被改动。
- **测试 TestRecord**：验证记录，绑定 `spec_ref + spec_version`（登记时所依据的规格版本）、
  `covered_files`（覆盖的代码）、`last_status`。
- **验证有效性三态**：
  - `VALID`：规格仍有效 + 契约符号未变 + 覆盖代码未变 → 先前结果可直接采信；
  - `STALE`：覆盖代码已变更 → 结果可能过期，重跑后再采信；
  - `INVALID`：依据的规格已失效，或测试引用的接口符号已不在当前契约 → 不得使用。
- **任务上下文 TaskContext**：按任务关键词组装，只含 active 规格 + 相关代码/测试 +
  失效决策警示 + 过期验证警示。

## 使用步骤（AI 助手侧）

1. **登记**：当看到一份需求/契约文档、一个决策、一次测试通过，调用
   `SpecRegistry.register_spec / register_decision / register_test / record_code`
   记入注册表（版本化、保留历史）。
2. **组装**：接到开发任务后，调用
   `ContextAssembler.assemble(task, current_hashes)` 得到任务上下文。
3. **执行**：只依据上下文中的 active 规格与 VALID 测试行事；
   STALE 测试先重跑；INVALID 测试与失效决策忽略并提示用户更新。
4. **交接**：任务收尾时 `HandoffManager.export_snapshot()`；
   新会话 `import_snapshot()` 后重复步骤 2。
5. **对账**：代码被外部改动时 `HandoffManager.reconcile([...])` 得到变更清单，
   据此将相关验证标记为 STALE。

## 判定规则（ValidityEngine，三条规则依次生效）

1. **依据的规格是否仍有效**：取测试登记时的规格版本
   （`TestRecord.spec_version`），若已 superseded / retired → `INVALID`；
2. **引用的契约符号是否仍存在**：测试 `from X import Y` 的接口名 / HTTP 端点
   是否仍被 active 契约声明 → 缺符号 → `INVALID`；
3. **覆盖代码是否已变更**：`covered_files` 的登记指纹 vs 磁盘当前指纹
   → 不一致（或缺失指纹）→ `STALE`；
   全过 → `VALID`。

## 边界与注意

- 模块只做**判定与组装**，不替你改代码；改完代码记得 `record_code` 更新快照。
- 不提供 current_hashes 时保守判 `STALE`（无法证明一致性，宁可重跑）。
- 与 PowerContext Server 集成是可选的：`powercontext_bridge.py` 把规格与失效决策
  写入记忆；Server 不可用时自动降级，不阻塞主流程。
- 纯标准库实现（urllib / hashlib / json / dataclasses），无第三方依赖。
