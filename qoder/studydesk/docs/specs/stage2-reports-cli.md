# Stage 2 规格：周报/复习清单生成 + CLI 入口

基于 Stage 1 的 `src/config.js`、`src/embedding.js`、`src/knowledge.js`、`src/memory.js` 实现：

## 1. src/reports.js
- `generateWeeklyReport(config, { since } = {})`：
  1. `listMemory(config, { limit: 100 })` 取全部记忆；
  2. 按 `state === "active"` 过滤，按 kind 分组：status/decision/constraint/weakpoint/其他；
  3. 组装周报草稿（Markdown）：
     - 标题 `# 周报（{userName} · {生成日期}）`
     - `## 本周进展`：status 类记忆逐条；若为空写"暂无进展记录"
     - `## 关键决策`：decision 类
     - `## 约束与约定`：constraint 类
     - `## 薄弱点/待复习`：weakpoint 类
     - `## 相关资料检索`：取进展文本里出现过的关键词（简单取每条第 1 个关键词候选：用记忆文本的前 8 个字符做查询），调用 `search`（knowledge 模块）各返回 2 条资料段落，列出出处。
  4. 返回 `{ report, stats }`（stats 含各类记忆条数与检索次数）。
- `generateReviewList(config)`：只召回 weakpoint + status 记忆，为每条检索 2 条相关资料，输出 `# 复习清单`（薄弱点 + 关联资料出处）。

## 2. src/cli.js
- 解析 `process.argv` 子命令：
  - `node src/cli.js import <fileOrDir>`：递归读取 `.md`/`.txt` 文件（每文件按空行分块，每块 1 条记录；meta 含 source=文件名），调用 knowledge.importTexts，打印"已导入 N 条资料"。
  - `node src/cli.js search <query>`：knowledge.search 打印 top 5（id/相似度/来源/文本前 80 字）。
  - `node src/cli.js hybrid <keyword> <query>`：knowledge.hybridSearch 打印结果。
  - `node src/cli.js record --kind <kind> "<text>"`：memory.recordMemory。
  - `node src/cli.js recall <query>`：memory.searchMemory 打印 hits。
  - `node src/cli.js weekly`：reports.generateWeeklyReport 打印报告。
  - `node src/cli.js review`：reports.generateReviewList 打印清单。
  - `node src/cli.js count`：knowledge.count。
  - 未知命令打印用法。
- 每个命令执行前 `loadConfig()`；执行后 `process.exit(0)`；异常打印 `[错误] ...` 并 exit 1。
- CLI 帮助文本用中文，清晰说明每条命令。
