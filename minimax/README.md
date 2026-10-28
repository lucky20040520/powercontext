# 规有所依：面向软件持续演进的 SDD 工程上下文管理系统

> PowerContext 2026 竞赛 · MiniMax 赛道
> 基线分支：`2026-competition-ecosystem`
> 作品：为 AI 开发助手（MiniMax Code / PowerContext 生态）实现的工程上下文模块
> 核心价值：**让 AI 开发助手只看到“当前有效”的规格、代码与测试，绝不依据已失效的旧要求干活**

## 作品一句话

持续维护的项目里，规格、契约、决策、代码、测试都在演进；本模块替 AI 开发助手
把“哪些要求还作数、哪些决策已失效、哪些验证还能信”这件事管起来——任务来了，
只给当前有效的规格、相关代码与测试，并在交接时完整带过去。

## 目录结构

```
minimax/
├── README.md                    # 本文件
├── SKILL.md                     # AI 开发助手使用本模块的行为规约（MiniMax Code 可加载）
├── scenario_demo.py             # 端到端场景演示（实际修改代码验证效果）
├── sdd_context/                 # 核心工程上下文模块（纯 Python 标准库）
│   ├── model.py                 # 数据模型：规格/决策/代码快照/测试/任务上下文
│   ├── registry.py              # 规格注册表：版本化登记、状态机、决策失效传播
│   ├── validity.py              # 验证有效性判定：valid / stale / invalid
│   ├── assembly.py              # 任务上下文组装：按任务检索有效规格+代码+测试
│   ├── handoff.py               # 跨会话交接：快照导出/导入、磁盘代码对账
│   └── powercontext_bridge.py   # 与 PowerContext Server 可选对接（MCP 记忆落库/召回）
├── demo_project/                # 示例项目：订单折扣服务（用于实际代码修改验证）
│   ├── specs/                   # 需求/契约/决策的 v1.0 与 v2.0 规格文档
│   ├── src/order_discount.py    # 实现代码（v1.0 → v1.1 → v2.0 演进）
│   └── tests/                   # 测试（v1 引用旧接口 → v2 引用新接口）
├── tests/                       # 单元测试（19 个用例，标准库 unittest）
│   └── run_all.py               # 一键运行全部测试
└── docs/
    ├── 方案设计.md               # 设计定稿
    ├── 运行说明.md               # 复现步骤
    └── 验证记录.md               # 验证结果
```

## 快速开始（详见 docs/运行说明.md）

```powershell
# 1) 运行全部单元测试（19 个用例）
python tests/run_all.py

# 2) 运行端到端场景演示（实际修改代码，验证 5 个演进阶段）
python scenario_demo.py

# 3) 运行示例项目自身的测试（v2.0 实现）
python demo_project/tests/test_order_discount.py
```

无需任何第三方依赖（纯标准库），无需模型 API Key，Windows / Linux / macOS 均可运行。

## 核心能力（对应题目要求）

| 题目要求 | 模块实现 |
|---|---|
| 当前任务应遵守什么要求 | `ContextAssembler.assemble()` 只返回 **active** 规格，superseded/retired 一律不进上下文 |
| 哪些决策已经失效 | 决策生命周期 + 规格演进**级联失效**（`cascade_invalidate_decisions`），失效决策作为警示列出 |
| 先前验证是否仍适用于当前代码 | `ValidityEngine` 三规则判定：**valid**（可采信）/ **stale**（代码已变更需重跑）/ **invalid**（规格/契约已失效） |
| 跨会话和任务交接 | `HandoffManager`：快照导出/导入 + 磁盘代码对账（`reconcile`），新会话无缝接续 |
| 通过实际代码修改验证效果 | `scenario_demo.py`：v1→bug修复→需求升级→契约变更→交接，5 阶段真实修改代码并校验 |

## 技术结合

- **SDD（规格驱动开发）**：以规格文档为唯一事实来源，代码与测试视为规格的可验证实现；
- **工程上下文模块**：独立于 IDE / 宿主，纯逻辑可单测，可通过 SKILL.md 接入
  MiniMax Code 等已有 AI 开发助手；
- **PowerContext 对接**（可选增强）：`powercontext_bridge.py` 将规格与失效决策
  写入 PowerContext 记忆（constraint/decision），实现跨会话无感召回；Server
  不可用时自动降级为纯本地模式。

## 提交与评测说明

- 开发分支：`2026-competition-ecosystem`
- 提测：仓库 `https://github.com/lucky20040520/powercontext`，分支 `2026-competition-ecosystem`，commit 以最新推送为准
