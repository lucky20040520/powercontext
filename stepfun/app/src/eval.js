// eval.js — in-browser evaluation: retrieval quality (Recall@K / nDCG@K) and
// stage-by-stage performance, all driven by the real running app.

import { api } from "./api.js";
import { embed, loadModel } from "./embed.js";
import { MODELS } from "./config.js";

const STOPWORDS = new Set(
  "的 了 是 在 和 与 及 或 我 你 他 她 它 我们 你们 他们 一个 这个 那个 这些 那些 怎么 什么 如何 为什么 吗 呢 啊 吧 有 没有 不 很 太 就 都 也 还 而 但 却 之 其 该 个 对 把 被 从 到 向 为 于 用 以 由 中 上 下 请 想 要 能 会 可以 应该 需要 知道 了解 介绍 说说 讲 讲解 一下 一点 一种 哪些 哪些方面 主要 相关 包括 关于".split(
    /\s+/
  )
);

/** Extract a full-text query string for seekdb's MATCH...AGAINST (NATURAL LANGUAGE MODE). */
export function extractKeywords(query) {
  let q = (query || "").replace(/[？！。，、；：""''（）《》【】\n\t]/g, " ").trim();
  if (!q) return "";
  const words = q.split(/\s+/).filter((w) => w && !STOPWORDS.has(w));
  const cleaned = words.join(" ");
  return (cleaned || q).slice(0, 60);
}

function mean(arr) {
  return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0;
}
function median(arr) {
  if (!arr.length) return 0;
  const s = [...arr].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export function ndcgAtK(hitIds, relevant, k) {
  const rel = hitIds.slice(0, k).map((id) => (relevant.includes(id) ? 1 : 0));
  let dcg = 0;
  rel.forEach((r, i) => {
    if (r) dcg += 1 / Math.log2(i + 2);
  });
  const idealCount = Math.min(relevant.length, k);
  let idcg = 0;
  for (let i = 0; i < idealCount; i++) idcg += 1 / Math.log2(i + 2);
  return idcg > 0 ? dcg / idcg : 0;
}

/**
 * Run one full evaluation for (model, variant, device).
 * Returns a structured result object with everything needed for the report.
 */
export async function runSingleEval({ model, variant, device, topk = 5, repeats = 3, onStatus, onProgress }) {
  const cfg = MODELS[model];
  const dataUrl = cfg.lang === "zh" ? "/eval-data/zh.json" : "/eval-data/en.json";
  const data = await (await fetch(dataUrl)).json();
  const docs = data.docs;
  const queries = data.queries;

  onStatus?.("加载模型…");
  const loaded = await loadModel(model, variant, device, (p) => {
    onProgress?.(Math.round(((p?.loaded ?? 0) / Math.max(p?.total ?? 1, 1)) * 25));
  });

  onStatus?.("重置评测集合…");
  await api.reset({ collection: "eval", dimension: cfg.dim });

  // ---- document vectorization (batched) ----
  const BATCH = 16;
  const vectors = [];
  const tEmbed0 = performance.now();
  for (let i = 0; i < docs.length; i += BATCH) {
    const slice = docs.slice(i, i + BATCH);
    const vecs = await embed(slice.map((d) => d.text));
    vectors.push(...vecs);
    onProgress?.(25 + Math.round(((i + slice.length) / docs.length) * 25));
  }
  const embedMs = performance.now() - tEmbed0;
  const throughput = docs.length / (embedMs / 1000);

  // ---- write to seekdb (batched) + refresh ----
  onStatus?.("写入 seekdb 并刷新索引…");
  let addMsTotal = 0;
  let refreshMsTotal = 0;
  const ADD_BATCH = 100;
  for (let i = 0; i < docs.length; i += ADD_BATCH) {
    const ids = [];
    const texts = [];
    const metas = [];
    const vecs = [];
    for (let j = i; j < Math.min(i + ADD_BATCH, docs.length); j++) {
      ids.push(docs[j].id);
      texts.push(docs[j].text);
      metas.push({ source: docs[j].source ?? "eval", idx: j });
      vecs.push(vectors[j]);
    }
    const r = await api.add({ collection: "eval", dimension: cfg.dim, ids, documents: texts, metadatas: metas, embeddings: vecs });
    addMsTotal += r.addMs;
    refreshMsTotal += r.refreshMs;
    onProgress?.(50 + Math.round(((i + ids.length) / docs.length) * 10));
  }

  // ---- quality: every query, hybrid + vector ----
  onStatus?.("质量评测（Recall@K / nDCG@K）…");
  async function runQuery(q, mode) {
    const tQ = performance.now();
    const qv = (await embed([q.text]))[0];
    const queryEmbedMs = performance.now() - tQ;
    const tD = performance.now();
    const res = await api.search({
      collection: "eval",
      dimension: cfg.dim,
      mode,
      queryEmbedding: qv,
      whereDocument: extractKeywords(q.text),
      nResults: topk,
    });
    const dbMs = performance.now() - tD;
    const hitIds = res.items.map((i) => i.id);
    const recall = q.relevant.filter((r) => hitIds.includes(r)).length / q.relevant.length;
    const ndcg = ndcgAtK(hitIds, q.relevant, topk);
    return { recall, ndcg, queryEmbedMs, dbMs, hitIds };
  }

  const hQuality = [];
  const vQuality = [];
  for (let i = 0; i < queries.length; i++) {
    hQuality.push(await runQuery(queries[i], "hybrid"));
    vQuality.push(await runQuery(queries[i], "vector"));
    onProgress?.(60 + Math.round(((i + 1) / queries.length) * 20));
  }
  const agg = (arr) => ({
    recall: mean(arr.map((x) => x.recall)),
    ndcg: mean(arr.map((x) => x.ndcg)),
  });

  // ---- performance: hot-query repeats (median) ----
  onStatus?.("性能基准（热查询 ×" + repeats + "）…");
  const hotQueries = queries.slice(0, Math.min(3, queries.length));
  const e2eTimes = [];
  const qEmbeds = [];
  const dbTimes = [];
  for (let r = 0; r < repeats; r++) {
    for (const q of hotQueries) {
      const t0 = performance.now();
      const tQ0 = performance.now();
      const qv = (await embed([q.text]))[0];
      qEmbeds.push(performance.now() - tQ0);
      const res = await api.search({
        collection: "eval",
        dimension: cfg.dim,
        mode: "hybrid",
        queryEmbedding: qv,
        whereDocument: extractKeywords(q.text),
        nResults: topk,
      });
      e2eTimes.push(performance.now() - t0);
      dbTimes.push(res.dbMs);
    }
    onProgress?.(80 + Math.round(((r + 1) / repeats) * 20));
  }

  return {
    config: { model, variant, device },
    model: { id: cfg.id, dim: cfg.dim, label: cfg.label },
    loaded,
    ingest: {
      docs: docs.length,
      embedMs: Math.round(embedMs),
      throughput: Math.round(throughput * 10) / 10,
      addMsTotal: Math.round(addMsTotal),
      refreshMsTotal: Math.round(refreshMsTotal),
    },
    quality: {
      topk,
      hybrid: agg(hQuality),
      vector: agg(vQuality),
      perQuery: queries.map((q, i) => ({
        query: q.text,
        hybrid: { recall: hQuality[i].recall, ndcg: hQuality[i].ndcg },
        vector: { recall: vQuality[i].recall, ndcg: vQuality[i].ndcg },
      })),
    },
    perf: {
      repeats,
      hotQueries: hotQueries.length,
      e2eMsMedian: Math.round(median(e2eTimes) * 10) / 10,
      queryEmbedMsMedian: Math.round(median(qEmbeds) * 10) / 10,
      dbMsMedian: Math.round(median(dbTimes) * 10) / 10,
    },
    ts: new Date().toISOString(),
  };
}
