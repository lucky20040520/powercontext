# 研习台 StudyDesk

> **项目网站（Qoder Sites 发布，未登录可访问）：https://studydesk-kz5n01y4si9.qoder.zone**

**记忆 + 检索，让学习、科研和工作更高效。** 一个本地运行的提效助手：用 **seekdb** 做知识库混合检索（论文/笔记/实验记录语义定位），用 **PowerContext** 做长期记忆（进展/决策/约束/薄弱点跨会话复用），并把两者组合成**周报草稿**与**复习清单**。

- 2026 OceanBase 数据库大赛 · Qoder 赛题作品（总分 20）
- 用 Qoder 开发（Stage 1 编码 + Stage 2~4 复审均经 Qoder 完成，见 `docs/开发记录.md`）
- seekdb × PowerContext 双技术结合（检索 / 记忆各司其职 + 自动降级）

> 数据库大赛 Qoder 赛题作品 · 基于 [oceanbase/powercontext](https://github.com/oceanbase/powercontext/tree/2026-competition-ecosystem) `2026-competition-ecosystem` 分支开发

## 解决的痛点

| 痛点 | 方案 |
| --- | --- |
| 几十篇论文/笔记散落各处，找不到相关段落 | 导入 seekdb，语义 + 关键词混合检索，返回段落与出处 |
| 跨会话忘了上周做到哪、确认过什么 | PowerContext 长期记忆，跨会话召回 |
| 周报要从聊天记录一条条拼 | 记忆召回 + 资料检索自动生成周报草稿 |

## 功能

- `import <file|dir>`：导入 .md/.txt 资料，分块向量化写入 seekdb
- `search <词>`：语义检索；`hybrid <关键词> <词>`：全文 + 语义混合检索
- `record --kind <kind> <文本>`：写入 PowerContext 记忆（status/decision/constraint/weakpoint）
- `recall <话题>`：从记忆召回相关内容
- `weekly`：生成周报草稿；`review`：生成复习清单
- `npm run web`：浏览器 Web 界面（导入/检索/记录/召回/周报/状态）

## 快速开始

```bash
# 1. 依赖（Node.js 22+）
npm install

# 2. 配置
copy .env.example .env        # Windows
# 修改 STUDYDESK_EMBED_CACHE 可指向 D 盘；POWERCONTEXT_SERVER_URL 指向已启动的 PowerContext Server

# 3. 启动 PowerContext Server（提供记忆能力）
#   安装：uv tool install --force "powercontext[cli,server]==1.4.1"
powercontext config init --language zh --output .env --template --force
powercontext server run --env-file .env        # 默认 http://127.0.0.1:8000

# 4. 准备演示数据 + 一键验证
npm run demo-data
npm run demo          # 断言通过输出 SCENARIO OK

# 5. Web 界面
npm run web           # 打开 http://127.0.0.1:8787
```

## 技术结合（题目要求）

- **seekdb**：知识库的存储与混合检索（向量索引 hnsw 512 维 + ik 全文索引，`hybridSearch` RRF 融合）。检索结果直接用于资料问答与周报相关资料段落。
- **PowerContext**：长期记忆（HTTP API 写入 `atomic-memory`、`search/list` 跨会话召回）。周报与复习清单的数据来源；seekdb 引擎不可用时自动降级为资料存储。
- **鲁棒性**：seekdb 通过子进程探测 + 失败自愈 + 自动降级，保证任何环境可运行（详见 `docs/验证记录.md` §4）。
- 向量化：本地 transformers.js（bge-small-zh-v1.5 q8），无外部 API，模型可缓存到任意盘。

详细说明见 `docs/`：方案设计、运行说明、验证记录、开发记录。

## 目录结构

```
qoder/studydesk/
├── package.json / .env.example / .gitignore
├── src/
│   ├── config.js       配置读取
│   ├── embedding.js    transformers.js 本地向量化
│   ├── knowledge.js    seekdb 引擎（导入/检索/混合检索/计数）
│   ├── memory.js       PowerContext 客户端（记录/召回/列表）
│   ├── reports.js      周报/复习清单生成
│   ├── cli.js          CLI 入口
│   └── web/            Express API + 前端页面
├── scripts/
│   ├── setup-demo-data.mjs   演示数据
│   └── scenario-demo.mjs     一键验证样例（评审入口）
└── docs/               方案设计 / 运行说明 / 验证记录 / 开发记录
```

## 提交材料索引

- 项目网站：Qoder Sites（见站点 README / 提交材料.md）
- 代码仓库：本目录（powercontext 仓库 `qoder/studydesk`）
- 运行说明：`docs/运行说明.md`
- 验证样例：`scripts/scenario-demo.mjs` + `docs/验证记录.md`
- Qoder 开发记录：`docs/开发记录.md`（含 Qoder 账号 UID）
