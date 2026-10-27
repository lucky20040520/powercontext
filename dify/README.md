# 雾谷镇夜话：守夜人老钟 —— Dify 赛道作品

> PowerContext 2026 竞赛 · Dify 赛道 · Just for Fun 题目
> 基线分支：`2026-competition-ecosystem`
> 作品：一个"会记仇的 NPC"互动聊天应用（Dify Chatflow × PowerContext 记忆）

## 作品一句话

雾谷镇的守夜人老钟记性好到吓人——你承诺过的事、骗过他的谎、送过他的酒，他全都记得，下次见面就翻旧账或念你的好。

## 目录结构

```
dify/
├── README.md                    # 本文件
├── workflows/
│   └── 雾谷镇夜话_守夜人老钟.yml  # Dify Chatflow DSL（可导入）
├── docs/
│   ├── 方案设计.md               # 设计定稿（人设/玩法/架构/记忆格式）
│   ├── 运行说明.md               # 部署步骤 + 验证样例（评审按此复现）
│   └── validate_dsl.py           # DSL 结构校验脚本
├── scripts/
│   ├── init_powercontext.ps1     # Windows 初始化 PowerContext Server
│   └── init_powercontext.sh      # Linux/WSL 初始化 PowerContext Server
└── plugins/                      # （暂未使用自定义插件）
```

## 快速开始（详见 docs/运行说明.md）

1. 启动 PowerContext Server：`bash scripts/init_powercontext.sh`（或 PowerShell 版本），健康检查 `http://127.0.0.1:8000/health/live`
2. 部署 Dify 社区版（Docker Compose），配置 LLM 模型
3. 工作室 → 导入 DSL：`workflows/雾谷镇夜话_守夜人老钟.yml`
4. 发布 → 预览对话（推荐用内置建议问题开始）
5. 按 docs/运行说明.md 的验证样例体验"记仇 / 记恩 / 跨轮引用"

## 技术结合

- **Dify**：Chatflow 全流程编排（读记忆 → LLM 生成 → 事件提取 → 写记忆）
- **PowerContext**：会话级记忆（Scope 按会话隔离，`prepare` 召回 / `remember` 写入）

## 提交与评测说明

- 开发分支：`2026-competition-ecosystem`
- 提测：仓库 `https://github.com/lucky20040520/powercontext`，分支 `2026-competition-ecosystem`，commit 以最新推送为准
