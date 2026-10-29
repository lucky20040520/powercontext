# 雾谷镇夜话：守夜人老钟 —— Dify 赛道作品

> PowerContext 2026 竞赛 · Dify 赛道 · Just for Fun 题目
> 基线分支：`2026-competition-ecosystem`
> 作品：一个"会记仇的 NPC"互动聊天应用（Dify Chatflow × PowerContext 记忆）

## 作品一句话

雾谷镇的守夜人老钟记性好到吓人——你承诺过的事、骗过他的谎、送过他的酒，他全都记得，下次见面就翻旧账或念你的好。

## 文件用途与导入顺序（赛题 4.1）

| 顺序 | 文件 | 用途 |
|---|---|---|
| 0 | `docs/方案设计.md` | （背景）人设、玩法、记忆格式与架构定稿，评审可先读此了解设计 |
| 1 | `scripts/init_powercontext.sh` / `.ps1` | 启动 PowerContext Server（作品依赖的外部服务） |
| 2 | `workflows/雾谷镇夜话_守夜人老钟.yml`（与 `dify/雾谷镇夜话_守夜人老钟.yml` 为同一 DSL 的两个副本，内容一致，任选其一导入） | **需要导入 Dify 的 DSL**：工作室 → 导入 DSL 即得完整应用 |
| 3 | （可选）`scripts/seed_demo_memory.py` | 预置"老钟记得旧事"的演示记忆，按提示选择执行 |
| 4 | `docs/运行说明.md` | 从零复现：部署 → 导入 → 验证样例 → 故障排查（评审主文档） |
| 5 | `docs/验证记录.md`、`docs/节点执行记录.md` | 运行证据：PowerContext 记忆闭环与 Dify HTTP 节点真实调用日志 |

## 目录结构

```
dify/
├── README.md                    # 本文件
├── workflows/
│   └── 雾谷镇夜话_守夜人老钟.yml  # Dify Chatflow DSL（可导入，唯一交付 DSL）
├── docs/
│   ├── 方案设计.md               # 设计定稿（人设/玩法/架构/记忆格式）
│   ├── 运行说明.md               # 部署步骤 + 验证样例 + 预期输出 + 故障排查（评审主文档）
│   ├── 验证记录.md               # 运行证据①：PowerContext 记忆闭环实测
│   ├── 节点执行记录.md            # 运行证据②：Dify 三个 HTTP 节点真实请求/响应日志
│   ├── validate_dsl.py           # DSL 结构校验脚本（可复跑）
│   ├── verify_memory_loop.py     # 记忆闭环复现脚本（对应验证记录）
│   └── produce_execution_record.py # 节点执行记录复现脚本
└── scripts/
    ├── init_powercontext.ps1     # Windows 初始化 PowerContext Server
    ├── init_powercontext.sh      # Linux/WSL 初始化 PowerContext Server
    └── seed_demo_memory.py       # （可选）预置演示记忆
```

## 快速开始（详见 docs/运行说明.md）

1. 启动 PowerContext Server：`bash scripts/init_powercontext.sh`（或 PowerShell 版本），健康检查 `http://127.0.0.1:8000/health/live`
2. 部署 Dify 社区版（**1.18.0**，Docker Compose 2.24+），配置 LLM 模型（推荐 gpt-4o-mini / deepseek-chat）
3. 工作室 → 导入 DSL：`workflows/雾谷镇夜话_守夜人老钟.yml`（自动关联 `langgenius/openai` 插件 0.0.26，按提示安装）
4. 发布 → 预览对话（推荐用内置建议问题开始）
5. 按 docs/运行说明.md 的验证样例体验"记仇 / 记恩 / 跨轮引用"

## 技术结合

- **Dify**：Chatflow 全流程编排（建Scope → 读记忆 → LLM 生成 → 事件提取 → 写记忆 → 输出），承担核心流程
- **PowerContext**：会话级记忆（Scope 按会话隔离，`prepare` 召回 / `remember` 写入），是老钟"记得你"的全部能力来源
- **运行证据**：`docs/节点执行记录.md`（真实请求/响应：写前 `empty`、写入 `changed:true`、再读 `ready` 且召回成功）

## 提交与评测说明

- 开发分支：`2026-competition-ecosystem`
- 提测：仓库 `https://github.com/lucky20040520/powercontext`，分支 `2026-competition-ecosystem`，commit 以最新推送为准
