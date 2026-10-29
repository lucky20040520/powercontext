// scenario-demo.mjs —— 验证样例：一键执行并断言（评审复现入口）
// 运行：node scripts/scenario-demo.mjs （或 npm run demo）
// 后端自适应：seekdb 可用则用 seekdb，否则自动降级 PowerContext 资料存储，断言均适用。
// 演示数据复用 setup-demo-data.mjs 的 DEMO_DOCS（8 条），保证两个脚本数据口径一致。
import { writeFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

import { loadConfig } from "../src/config.js";
import { withClient, getBackend } from "../src/knowledge.js";
import { recordMemory, searchMemory } from "../src/memory.js";
import { generateWeeklyReport } from "../src/reports.js";
import { DEMO_DOCS } from "./setup-demo-data.mjs";

const config = loadConfig();
const assertions = [];
const runAt = new Date().toISOString();

function assert(name, pass, detail = "") {
  assertions.push({ name, pass, detail });
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? " — " + detail : ""}`);
}

console.log("=== 研习台 StudyDesk 验证样例 ===\n");

// 0. 准备：写入规格要求的 8 条演示资料（幂等：可重复跑；重复导入由库内去重/追加处理）
await withClient(async (client) => { await client.importTexts(DEMO_DOCS); });

// 1. 知识库计数（规格：≥ 8）
const n = await withClient((client) => client.count());
assert("知识库可读写", n >= 8, `当前文档数 ${n}`);

// 2. 检索：规格语义查询「数据库 索引结构」应命中索引结构资料
const s1 = await withClient((client) => client.search("数据库 索引结构", { nResults: 3 }));
assert("检索命中相关资料", s1.length > 0 && /索引/.test(s1[0].text), `top1: ${s1[0]?.text.slice(0, 30)}…`);

// 3. 混合检索：规格关键词「向量」+ 语义「论文调研」
const h1 = await withClient((client) => client.hybridSearch("论文调研", "向量", { nResults: 5 }));
assert("混合检索（关键词+语义）非空", h1.length > 0, `命中 ${h1.length} 条`);

// 4. 记忆写入
const stamp = `验证：scenario-demo 运行于 ${runAt.slice(0, 19)}`;
const wr = await recordMemory(config, "status", stamp);
assert("记忆写入成功", !!wr.artifact_id, `artifact_id=${wr.artifact_id}`);

// 5. 记忆召回：规格召回查询「数学 复习」应命中相关记忆
const recall = await searchMemory(config, "数学 复习", { limit: 5 });
assert("记忆召回命中", recall.hits.length > 0 && /数学/.test(recall.hits[0].memory.text), `top: ${recall.hits[0]?.memory.text.slice(0, 30)}…`);

// 6. 周报生成：包含"本周进展"且至少有 status 记忆
const weekly = await generateWeeklyReport(config);
assert("周报生成包含进展与检索", weekly.report.includes("本周进展") && weekly.stats.status >= 1, `status=${weekly.stats.status}, 检索 ${weekly.stats.searchCount} 次`);

// 7. 汇总输出（技术作用证据，字段与规格一致）
const backend = getBackend();
const summary = {
  runAt,
  backend,
  assertions,
  techEvidence: {
    seekdb: {
      available: backend === "seekdb",
      note: backend === "seekdb" ? "本次验证实际由 seekdb 提供检索" : "当前环境 seekdb 引擎不可用，自动降级 PowerContext 资料存储（详见 docs/验证记录.md）",
      search: { query: "数据库 索引结构", topHit: s1[0]?.text.slice(0, 40) },
      hybrid: { keyword: "向量", semantic: "论文调研", hits: h1.length },
      count: n,
    },
    powercontext: {
      write: { artifact_id: wr.artifact_id, text: stamp },
      recallHits: recall.hits.length,
      role: "长期记忆（跨会话复用）+ 降级路径的资料存储",
    },
  },
};
const outDir = resolve(config.dbDir, "..");
mkdirSync(outDir, { recursive: true });
writeFileSync(resolve(outDir, "scenario-result.json"), JSON.stringify(summary, null, 2), "utf-8");
console.log(`\n结果已写入 ${resolve(outDir, "scenario-result.json")}`);

const failed = assertions.filter((a) => !a.pass);
console.log(`\n${failed.length === 0 ? "SCENARIO OK ✅（全部断言通过）" : `SCENARIO FAILED ❌（${failed.length} 项失败）`}`);
process.exit(failed.length === 0 ? 0 : 1);
