# Stage 4 规格：演示数据 + 一键验证样例

## 1. scripts/setup-demo-data.mjs
- 演示知识库（内置 8 段中文资料，覆盖：向量数据库索引、考研数学、数据库大赛、组会、PowerContext 记忆、周报写作、嵌入式数据库、NLP 文献）：
  每条 `{ id: "d1"... , text, source: "样例资料.md" }` → knowledge.importTexts。
- 演示记忆（写入 PowerContext，kind + 文本）：
  - status: "本周完成数据库大赛 Qoder 赛题方案设计，确定 seekdb + PowerContext 技术选型"
  - status: "考研数学：高数中值定理过完一轮，下周进入定积分应用刷题"
  - decision: "研习台采用 Node.js + 本地向量化，不依赖外部 API，数据全部本地保存"
  - constraint: "组会周报需包含：本周完成、下周计划、风险与求助三项"
  - weakpoint: "向量数据库 HNSW 与 IVF 索引的区别还没吃透，需要复习"
- 打印执行摘要（导入 N 条、写入 M 条记忆）。
- 可重复执行（幂等：重复导入会再写入一遍；记忆重复写入无害，可在 .env 换 scope 重来）。

## 2. scripts/scenario-demo.mjs（验证样例：评审一键复现）
- 依次执行并**断言**，全部通过输出 `SCENARIO OK`，失败输出断言信息并 exit 1：
  1. 知识库计数 ≥ 8（setup 后）；
  2. 语义检索：查询"数据库 索引结构" top1 应包含"索引"字样（命中资料 d1 关于 HNSW/IVF 的段落）；
  3. 混合检索：keyword="向量" + 语义查询"论文调研" 结果非空；
  4. 记忆写入：写入 status "验证：scenario-demo 运行于 {时间}"；
  5. 记忆召回：searchMemory("数学 复习") 应命中包含"数学"的记忆；
  6. 周报生成：generateWeeklyReport 返回的报告包含 "本周进展" 且 stats.status ≥ 1；
  7. 输出 JSON 汇总（写入 `data/scenario-result.json`）：
     `{ runAt, assertions: [{name, pass, detail}] , techEvidence: { seekdb: {search: true, hybrid: true, count: N}, powercontext: {write: artifact_id, recallHits: N} } }`
- 注意脚本运行前自动执行 setup-demo-data 的逻辑（直接 import 并调用）。

## 3. 验收自检（评审角度）
- `npm install` → `npm run demo-data` → `npm run demo` 三步可跑通。
- `npm run web` 后浏览器打开 http://127.0.0.1:8787 可完成导入/检索/记录/召回/周报。
- PowerContext Server 需先启动（运行说明中给出 `powercontext server run --env-file .env`）。
