// 周报 / 复习清单生成：记忆召回（PowerContext）+ 资料检索（seekdb）组合
import { listMemory } from "./memory.js";
import { withClient } from "./knowledge.js";

function fmtDate(d = new Date()) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

// 从一条记忆文本里取检索关键词：去掉常见引导词后取前 8 个字符
function keywordOf(text) {
  const cleaned = text.replace(/^(本周|上周|下周|今天|昨天|已完成|完成了|需要|计划|继续|进行|决定|确认|要求|约束|正在|准备)/, "");
  return cleaned.slice(0, 8) || text.slice(0, 8);
}

async function relatedMaterials(config, text, nResults = 2) {
  try {
    const keyword = keywordOf(text);
    return await withClient((client) => client.search(keyword, { nResults }));
  } catch (err) {
    return [{ error: `资料检索失败：${err.message}` }];
  }
}

/**
 * 生成周报草稿
 * @param {object} config 配置
 * @param {{since?: string}} opts 可选：since（ISO 时间，仅统计该时间之后写入的记忆；items 无时间字段时忽略）
 * @returns {Promise<{report: string, stats: object}>}
 */
export async function generateWeeklyReport(config, { since } = {}) {
  const { items } = await listMemory(config, { limit: 100 });
  const sinceMs = since ? new Date(since).getTime() : 0;
  const active = items.filter((it) => {
    if (it.state !== "active") return false;
    if (sinceMs && it.updated_at) return new Date(it.updated_at).getTime() >= sinceMs;
    return true;
  });
  const byKind = { status: [], decision: [], constraint: [], weakpoint: [], other: [] };
  for (const it of active) {
    const k = byKind[it.kind] ? it.kind : "other";
    byKind[k].push(it);
  }

  const lines = [];
  lines.push(`# 周报（${config.userName} · ${fmtDate()}）`);
  lines.push("");
  lines.push("> 由研习台 StudyDesk 自动生成：进展/决策来自 PowerContext 记忆，相关资料来自 seekdb 知识库混合检索。");
  lines.push("");

  lines.push("## 本周进展");
  if (byKind.status.length === 0) lines.push("- （暂无进展记录，可用 `study record --kind status \"...\"` 记录）");
  else byKind.status.forEach((it) => lines.push(`- ${it.text}`));
  lines.push("");

  lines.push("## 关键决策");
  if (byKind.decision.length === 0) lines.push("- （暂无决策记录）");
  else byKind.decision.forEach((it) => lines.push(`- ${it.text}`));
  lines.push("");

  lines.push("## 约束与约定");
  if (byKind.constraint.length === 0) lines.push("- （暂无约束记录）");
  else byKind.constraint.forEach((it) => lines.push(`- ${it.text}`));
  lines.push("");

  lines.push("## 薄弱点 / 待复习");
  if (byKind.weakpoint.length === 0) lines.push("- （暂无薄弱点记录）");
  else byKind.weakpoint.forEach((it) => lines.push(`- ${it.text}`));
  lines.push("");

  lines.push("## 相关资料检索");
  let searchCount = 0;
  const sources = [];
  const pairs = [
    ...byKind.status.slice(0, 3).map((it) => ({ label: keywordOf(it.text), it })),
    ...byKind.weakpoint.slice(0, 3).map((it) => ({ label: keywordOf(it.text), it })),
  ];
  for (const { label, it } of pairs) {
    const hits = await relatedMaterials(config, it.text);
    searchCount += 1;
    if (hits[0] && !hits[0].error) {
      lines.push(`- 关于「${label}」：`);
      for (const h of hits.slice(0, 2)) {
        lines.push(`  - ${h.text.length > 60 ? h.text.slice(0, 60) + "…" : h.text}（来源：${h.meta?.source || "未知"}）`);
        sources.push(h.meta?.source || "未知");
      }
    }
  }
  lines.push("");

  const report = lines.join("\n");
  const stats = {
    status: byKind.status.length,
    decision: byKind.decision.length,
    constraint: byKind.constraint.length,
    weakpoint: byKind.weakpoint.length,
    memoryTotal: active.length,
    searchCount,
    sources: [...new Set(sources)],
  };
  return { report, stats };
}

/**
 * 生成复习清单：薄弱点 + 关联资料
 */
export async function generateReviewList(config) {
  const { items } = await listMemory(config, { limit: 100 });
  const active = items.filter((it) => it.state === "active");
  const weak = active.filter((it) => it.kind === "weakpoint");
  const status = active.filter((it) => it.kind === "status");

  const lines = [];
  lines.push(`# 复习清单（${config.userName} · ${fmtDate()}）`);
  lines.push("");
  lines.push("> 薄弱点来自 PowerContext 记忆，关联资料来自 seekdb 混合检索。");
  lines.push("");

  lines.push("## 薄弱点与关联资料");
  if (weak.length === 0) {
    lines.push("- （暂无薄弱点记录，可用 `study record --kind weakpoint \"...\"` 添加）");
  }
  for (const it of weak) {
    lines.push(`- ${it.text}`);
    const hits = await relatedMaterials(config, it.text);
    for (const h of hits.slice(0, 2)) {
      if (h.error) lines.push(`  - ${h.error}`);
      else lines.push(`  - ${h.text}（来源：${h.meta?.source || "未知"}）`);
    }
  }
  lines.push("");

  lines.push("## 进行中的任务");
  if (status.length === 0) lines.push("- （暂无进展记录）");
  else status.forEach((it) => lines.push(`- ${it.text}`));

  // 进行中的任务也关联检索资料（规格：为每条 status 检索 2 条相关资料）
  let statusSearchCount = 0;
  for (const it of status.slice(0, 5)) {
    const hits = await relatedMaterials(config, it.text);
    statusSearchCount += 1;
    for (const h of hits.slice(0, 2)) {
      if (!h.error) lines.push(`  - 关联：${h.text.length > 50 ? h.text.slice(0, 50) + "…" : h.text}（来源：${h.meta?.source || "未知"}）`);
    }
  }

  const report = lines.join("\n");
  return { report, stats: { weakpoint: weak.length, status: status.length, statusSearchCount } };
}
