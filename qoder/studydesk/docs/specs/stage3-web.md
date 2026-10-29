# Stage 3 规格：Web 界面（Express + 原生前端）

基于 Stage 1/2 的引擎模块，实现：

## 1. src/web/server.js
- Express 应用，监听 `config.webPort`（默认 8787）。
- 中间件：`express.json()`；静态资源指向 `src/web/public`。
- API（全部 JSON，UTF-8）：
  - `GET /api/health` → `{ ok: true, seekdb: bool, powercontext: bool }`（分别探测：count 是否可执行 / scope 或服务器是否可访问）。
  - `POST /api/import` `{ text }`（一次导入一段文本，meta.source="web"）→ `{ imported }`
  - `POST /api/search` `{ query, mode: "semantic"|"hybrid", keyword? }` → `{ results: [{id, text, meta, distance?}] }`
  - `POST /api/record` `{ kind, text }` → `{ artifact_id, revision }`
  - `POST /api/recall` `{ query }` → `{ hits }`
  - `POST /api/weekly` → `{ report }`
  - `POST /api/review` → `{ report }`
  - `GET /api/count` → `{ docs }`
- 每次请求实时调用引擎（不缓存 client；用 knowledge.withClient）。
- 错误统一 `{ error: message }` 500。

## 2. src/web/public/index.html（单文件，内联 CSS/JS，无构建工具）
- 中文界面，浅色主题，卡片式布局，顶部标题「研习台 StudyDesk」+ 副标题「记忆 + 检索，让学习科研更高效」。
- 功能区块（Tab 或卡片均可）：
  1. **资料导入**：textarea + 「导入知识库」按钮 → POST /api/import，显示导入条数。
  2. **混合检索**：查询词 + 关键词输入 + 「检索」按钮；模式下拉（语义/混合）；结果列表显示文本、来源、相似度。
  3. **记忆记录**：kind 下拉（进展/决策/约束/薄弱点）+ 文本输入 + 「写入记忆」。
  4. **记忆召回**：输入话题 → 显示命中记忆（kind 徽标 + 文本）。
  5. **周报生成**：「生成周报」→ 展示 Markdown 报告（简单渲染：保留 ## 标题样式）。
  6. **复习清单**：「生成复习清单」→ 展示。
  7. 底部状态栏：知识库文档数、PowerContext 连接状态（/api/health）。
- 不引入外部 CDN（全部内联），页面无需构建即可用。
