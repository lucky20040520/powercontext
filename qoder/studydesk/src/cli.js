// 研习台 StudyDesk CLI 入口
import { readFileSync, readdirSync, statSync } from "node:fs";
import { resolve, extname, join, basename } from "node:path";
import { randomUUID } from "node:crypto";

import { loadConfig } from "./config.js";
import { withClient } from "./knowledge.js";
import { recordMemory, searchMemory, MEMORY_KINDS } from "./memory.js";
import { generateWeeklyReport, generateReviewList } from "./reports.js";

const USAGE = `
研习台 StudyDesk —— 记忆 + 检索，让学习科研更高效

用法：
  node src/cli.js import <file|dir>            导入资料（.md/.txt，按空行分块）到知识库
  node src/cli.js search <查询词>              语义检索知识库，返回相关段落与来源
  node src/cli.js hybrid <关键词> <查询词>      全文 + 语义混合检索
  node src/cli.js record --kind <kind> <文本>  写入长期记忆（kind: status|decision|constraint|weakpoint）
  node src/cli.js recall <话题>                从长期记忆召回相关内容
  node src/cli.js weekly                       生成周报草稿（记忆召回 + 资料检索）
  node src/cli.js review                       生成复习清单
  node src/cli.js count                        知识库文档数量
  node src/cli.js help                         显示本帮助
`;

function help() {
  console.log(USAGE);
}

function splitChunks(text) {
  return text
    .split(/\n\s*\n/)
    .map((s) => s.replace(/\s+/g, " ").trim())
    .filter((s) => s.length >= 8);
}

function collectFiles(target) {
  const files = [];
  const walk = (p) => {
    const st = statSync(p);
    if (st.isDirectory()) {
      for (const name of readdirSync(p)) walk(join(p, name));
    } else if (extname(p).toLowerCase() === ".md" || extname(p).toLowerCase() === ".txt") {
      files.push(p);
    }
  };
  walk(target);
  return files;
}

async function cmdImport(config, target) {
  const files = collectFiles(resolve(target));
  if (files.length === 0) {
    console.log("[错误] 未找到 .md/.txt 文件");
    process.exit(1);
  }
  const items = [];
  for (const f of files) {
    const text = readFileSync(f, "utf-8");
    for (const chunk of splitChunks(text)) {
      items.push({
        id: `doc_${randomUUID().replace(/-/g, "").slice(0, 16)}`,
        text: chunk,
        meta: { source: basename(f) },
      });
    }
  }
  const imported = await withClient((client) => client.importTexts(items));
  console.log(`已导入 ${imported} 条资料（来源文件 ${files.length} 个）`);
}

async function cmdSearch(config, query) {
  const results = await withClient((client) => client.search(query, { nResults: 5 }));
  if (results.length === 0) {
    console.log("没有检索到相关内容");
    return;
  }
  results.forEach((r, i) => {
    const text = r.text.length > 80 ? r.text.slice(0, 80) + "…" : r.text;
    console.log(`[${i + 1}] id ${r.id} | 相似度 ${(1 - r.distance).toFixed(3)} | 来源 ${r.meta?.source || "未知"}`);
    console.log(`    ${text}`);
    console.log("");
  });
}

async function cmdHybrid(config, keyword, query) {
  const results = await withClient((client) => client.hybridSearch(query, keyword, { nResults: 5 }));
  if (results.length === 0) {
    console.log("没有检索到相关内容");
    return;
  }
  results.forEach((r, i) => {
    const text = r.text.length > 80 ? r.text.slice(0, 80) + "…" : r.text;
    console.log(`[${i + 1}] id ${r.id} | 来源 ${r.meta?.source || "未知"}`);
    console.log(`    ${text}`);
    console.log("");
  });
}

async function cmdRecord(config, kind, text) {
  if (!Object.values(MEMORY_KINDS).includes(kind)) {
    console.log(`[错误] kind 必须为 ${Object.values(MEMORY_KINDS).join("|")}`);
    process.exit(1);
  }
  const r = await recordMemory(config, kind, text);
  console.log(`已写入记忆（kind=${kind}）：${text}`);
  console.log(`artifact_id=${r.artifact_id} revision=${r.revision}`);
}

async function cmdRecall(config, query) {
  const { mode, hits } = await searchMemory(config, query, { limit: 5 });
  console.log(`召回模式：${mode}，命中 ${hits.length} 条`);
  for (const h of hits) {
    console.log(`- [${h.memory.kind}] ${h.memory.text}`);
  }
}

async function cmdWeekly(config) {
  const { report, stats } = await generateWeeklyReport(config);
  console.log(report);
  console.log(`\n[统计] 记忆 ${stats.memoryTotal} 条（进展 ${stats.status} / 决策 ${stats.decision} / 约束 ${stats.constraint} / 薄弱点 ${stats.weakpoint}），资料检索 ${stats.searchCount} 次`);
}

async function cmdReview(config) {
  const { report, stats } = await generateReviewList(config);
  console.log(report);
  console.log(`\n[统计] 薄弱点 ${stats.weakpoint} 条，进行中任务 ${stats.status} 条`);
}

async function cmdCount() {
  const n = await withClient((client) => client.count());
  console.log(`知识库文档数：${n}`);
}

async function main() {
  const args = process.argv.slice(2);
  const cmd = args[0] || "help";

  try {
    const config = loadConfig();
    switch (cmd) {
      case "import":
        if (!args[1]) return help();
        await cmdImport(config, args[1]);
        break;
      case "search":
        if (!args[1]) return help();
        await cmdSearch(config, args[1]);
        break;
      case "hybrid": {
        if (!args[1] || !args[2]) return help();
        await cmdHybrid(config, args[1], args[2]);
        break;
      }
      case "record": {
        const kindIdx = args.indexOf("--kind");
        const kind = kindIdx >= 0 ? args[kindIdx + 1] : undefined;
        const text = args.slice(kindIdx >= 0 ? kindIdx + 2 : 1).join(" ");
        if (!kind || !text) return help();
        await cmdRecord(config, kind, text);
        break;
      }
      case "recall":
        if (!args[1]) return help();
        await cmdRecall(config, args.slice(1).join(" "));
        break;
      case "weekly":
        await cmdWeekly(config);
        break;
      case "review":
        await cmdReview(config);
        break;
      case "count":
        await cmdCount();
        break;
      default:
        help();
    }
    // 规格约定：正常完成后显式退出 0
    process.exit(0);
  } catch (err) {
    console.error(`[错误] ${err.message}`);
    process.exit(1);
  }
}

main();
