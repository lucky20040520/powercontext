// 研习台 StudyDesk Web 服务：Express API + 静态页面
import express from "express";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

import { loadConfig } from "../config.js";
import { withClient } from "../knowledge.js";
import { recordMemory, searchMemory, listMemory, ensureScope } from "../memory.js";
import { generateWeeklyReport, generateReviewList } from "../reports.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = resolve(__dirname, "public");

const app = express();
app.use(express.json({ limit: "2mb" }));
app.use(express.static(PUBLIC_DIR));

function asyncWrap(fn) {
  return (req, res) => {
    fn(req, res).catch((err) => res.status(500).json({ error: err.message }));
  };
}

app.get("/api/health", asyncWrap(async (req, res) => {
  const config = loadConfig();
  let seekdbOk = false;
  let powercontextOk = false;
  try {
    await withClient(async (client) => { await client.count(); });
    seekdbOk = true;
  } catch {
    seekdbOk = false;
  }
  try {
    await ensureScope(config);
    powercontextOk = true;
  } catch {
    powercontextOk = false;
  }
  res.json({ ok: seekdbOk && powercontextOk, seekdb: seekdbOk, powercontext: powercontextOk });
}));

app.post("/api/import", asyncWrap(async (req, res) => {
  const config = loadConfig();
  const { text, source } = req.body || {};
  if (!text || typeof text !== "string") {
    return res.status(400).json({ error: "缺少 text 字段" });
  }
  const chunk = text.replace(/\s+/g, " ").trim();
  if (chunk.length < 8) return res.status(400).json({ error: "内容太短（至少 8 字）" });
  const imported = await withClient((client) =>
    client.importTexts([{ id: `web_${Date.now()}_${Math.floor(Math.random() * 1e6)}`, text: chunk, meta: { source: source || "web" } }])
  );
  res.json({ imported });
}));

app.post("/api/search", asyncWrap(async (req, res) => {
  const config = loadConfig();
  const { query, mode = "semantic", keyword } = req.body || {};
  if (!query) return res.status(400).json({ error: "缺少 query 字段" });
  const results = await withClient((client) =>
    mode === "hybrid"
      ? client.hybridSearch(query, keyword || query, { nResults: 5 })
      : client.search(query, { nResults: 5 })
  );
  res.json({ results });
}));

app.post("/api/record", asyncWrap(async (req, res) => {
  const config = loadConfig();
  const { kind, text } = req.body || {};
  if (!kind || !text) return res.status(400).json({ error: "缺少 kind 或 text" });
  const r = await recordMemory(config, kind, text);
  res.json(r);
}));

app.post("/api/recall", asyncWrap(async (req, res) => {
  const config = loadConfig();
  const { query } = req.body || {};
  if (!query) return res.status(400).json({ error: "缺少 query 字段" });
  const { mode, hits } = await searchMemory(config, query, { limit: 5 });
  res.json({ mode, hits });
}));

app.get("/api/memories", asyncWrap(async (req, res) => {
  const config = loadConfig();
  const { items } = await listMemory(config, { limit: 50 });
  res.json({ items });
}));

app.post("/api/weekly", asyncWrap(async (req, res) => {
  const config = loadConfig();
  const { report, stats } = await generateWeeklyReport(config);
  res.json({ report, stats });
}));

app.post("/api/review", asyncWrap(async (req, res) => {
  const config = loadConfig();
  const { report, stats } = await generateReviewList(config);
  res.json({ report, stats });
}));

app.get("/api/count", asyncWrap(async (req, res) => {
  const n = await withClient((client) => client.count());
  res.json({ docs: n });
}));

const config = loadConfig();
const port = config.webPort;
app.listen(port, () => {
  console.log(`研习台 StudyDesk Web 已启动：http://127.0.0.1:${port}`);
});
