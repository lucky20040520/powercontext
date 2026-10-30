// setup-demo-data.mjs —— 一键准备演示数据（知识库样例 + 记忆样例），可重复执行
// DEMO_DOCS / DEMO_MEMORIES 同时导出，供 scenario-demo.mjs 复用（保证两脚本数据口径一致）
import { loadConfig } from "../src/config.js";
import { withClient } from "../src/knowledge.js";
import { recordMemory, ensureScope } from "../src/memory.js";

export const DEMO_DOCS = [
  { id: "d1", text: "向量数据库的索引结构：HNSW 与 IVF 是两种主流方案。HNSW 通过多层跳表结构加速近邻搜索，内存占用高但查询快；IVF 通过倒排聚类先缩小候选集，适合大规模数据。实际选型要权衡写入吞吐、查询延迟与内存成本。", meta: { source: "向量数据库调研笔记.md" } },
  { id: "d2", text: "考研数学复习：泰勒展开、拉格朗日中值定理与定积分应用是高频考点。建议先过一遍定理证明，再刷历年真题，错题按知识点归类反复巩固。", meta: { source: "考研数学复习笔记.md" } },
  { id: "d3", text: "数据库大赛 Qoder 赛题：用 Qoder 开发一个提升学习科研效率的项目，必须实际使用 seekdb 或 PowerContext，并通过 Qoder Sites 发布项目网站。总分 20 分，评审按运行说明复现主要功能。", meta: { source: "赛题说明.md" } },
  { id: "d4", text: "组会汇报结构：先讲本周做了什么，再讲遇到的难点与解决思路，最后给出下周计划与需要的支持。汇报要准备一页关键结果，避免罗列全部细节。", meta: { source: "组会经验.md" } },
  { id: "d5", text: "PowerContext 是面向 AI Agent 的开源上下文服务，支持 HTTP API、MCP 与 Python SDK。它把决定、约束与进展保存为长期记忆，跨会话、跨 Agent 复用，避免每次从头开始。", meta: { source: "PowerContext 笔记.md" } },
  { id: "d6", text: "周报写作技巧：用「本周完成 / 下周计划 / 风险与求助」三段式结构，每条事项带上可核对的产出（仓库链接、文档、数据），避免空泛描述。", meta: { source: "周报写作指南.md" } },
  { id: "d7", text: "嵌入式数据库非常适合个人知识库应用：数据保存在本地目录，无需部署服务，启动快、隐私好。seekdb 提供嵌入式模式，一条 npm 依赖即可在 Node.js 里使用。", meta: { source: "嵌入式数据库笔记.md" } },
  { id: "d8", text: "NLP 文献阅读方法：先读摘要与结论判断相关性，再读实验设置复现要点，最后做知识卡片记录创新点与局限，定期用语义检索回看卡片。", meta: { source: "文献阅读方法.md" } },
];

export const DEMO_MEMORIES = [
  { kind: "status", text: "本周完成数据库大赛 Qoder 赛题方案设计，确定 seekdb + PowerContext 技术选型" },
  { kind: "status", text: "考研数学：高数中值定理过完一轮，下周进入定积分应用刷题" },
  { kind: "decision", text: "研习台采用 Node.js + 本地向量化，不依赖外部 API，数据全部本地保存" },
  { kind: "constraint", text: "组会周报需包含：本周完成、下周计划、风险与求助三项" },
  { kind: "weakpoint", text: "向量数据库 HNSW 与 IVF 索引的区别还没吃透，需要复习" },
];

const config = loadConfig();

const docCount = await withClient(async (client) => {
  await client.importTexts(DEMO_DOCS);
  return await client.count();
});
console.log(`[知识库] 已导入 ${DEMO_DOCS.length} 条演示资料，当前文档总数 ${docCount}`);

const scopeId = await ensureScope(config);
console.log(`[记忆] scope=${scopeId}`);
for (const m of DEMO_MEMORIES) {
  const r = await recordMemory(config, m.kind, m.text);
  console.log(`[记忆] 已写入 kind=${m.kind} → ${r.artifact_id}`);
}

console.log("\n演示数据准备完成。接下来可运行：npm run demo （一键验证）或 npm run web （启动 Web 界面）");
