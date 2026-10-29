// server.js — seekdb embedded backend + REST API + static hosting for the mini KB app.
//
// Responsibilities:
//   1. Boot a local seekdb embedded engine (data under ./data), create database `kb`
//      and named collections (default `docs`; `eval` used by the in-app benchmark).
//      Each collection: HNSW vector index + IK fulltext index, embeddingFunction=null —
//      embeddings are computed in the browser and passed explicitly, NO server-side inference.
//   2. Expose REST API: init / add / search (hybrid & vector) / delete / reset / stats / health.
//      Hybrid search (fulltext + vector + RRF fusion) is performed inside seekdb via
//      collection.hybridSearch() — the client never merges two result sets itself.
//   3. Serve the built frontend (../app/dist), local model files (../models), the eval data
//      (../data/eval) and onnxruntime-web wasm assets (../app/dist/wasm).
//
// Note on index refresh: seekdb builds vector/fulltext index deltas asynchronously;
// approximate vector queries only see new writes after `refresh_index()` (dbms_index_manager.refresh).
// We therefore always refresh after add and report refresh latency.

import express from "express";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { existsSync, mkdirSync } from "node:fs";
import { SeekdbClient, SeekdbAdminClient, Schema, VectorIndexConfig, FulltextIndexConfig } from "seekdb";

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = process.env.PORT || 3000;
const HOST = process.env.HOST || "127.0.0.1";

const DB_PATH = process.env.SEEKDB_DB_PATH || join(__dirname, "data", "seekdb.db");
const DB_NAME = process.env.SEEKDB_DB || "kb";
const DEFAULT_COLLECTION = process.env.SEEKDB_COLLECTION || "docs";
// Session query timeout: refresh_index builds the HNSW index which can exceed the
// engine default; raise it to 600 s on the embedded session.
const QUERY_TIMEOUT_US = 600_000_000;

mkdirSync(join(__dirname, "data"), { recursive: true });

// ---------------------------------------------------------------------------
// seekdb bootstrap
// ---------------------------------------------------------------------------
let client = null;
const collectionCache = new Map(); // name -> collection

async function ensureDatabase() {
  const admin = new SeekdbAdminClient({ path: DB_PATH });
  try {
    await admin.createDatabase(DB_NAME);
  } finally {
    await admin.close();
  }
}

async function ensureSessionTimeout(c) {
  try {
    await c.execute(`SET SESSION ob_query_timeout = ${QUERY_TIMEOUT_US}`);
  } catch (e) {
    console.warn("[seekdb] failed to raise session timeout:", e.message);
  }
}

function makeSchema(dimension) {
  return new Schema({
    vectorIndex: new VectorIndexConfig({
      hnsw: { dimension, distance: "cosine" },
      embeddingFunction: null,
    }),
    fulltextIndex: new FulltextIndexConfig("ik", { ik_mode: "smart" }),
  });
}

async function getCollection(name, dimension = 512, { create = true } = {}) {
  if (collectionCache.has(name)) return collectionCache.get(name);
  if (client && (await client.hasCollection(name))) {
    // embeddingFunction: null keeps browser-supplied vectors; without it seekdb
    // tries to resolve the optional 'default-embed' package and fails on restart.
    const col = await client.getCollection({ name, embeddingFunction: null });
    collectionCache.set(name, col);
    return col;
  }
  if (!create) return null;
  const col = await client.createCollection({ name, schema: makeSchema(dimension) });
  collectionCache.set(name, col);
  return col;
}

export async function initCollection(dimension = 512) {
  await ensureDatabase();
  client = new SeekdbClient({ path: DB_PATH, database: DB_NAME });
  await ensureSessionTimeout(client);
  const col = await getCollection(DEFAULT_COLLECTION, dimension);
  return { db: DB_NAME, collection: col.name, dimension: col.dimension, distance: col.distance };
}

export async function resetCollection(name, dimension = 512) {
  collectionCache.delete(name);
  if (client && (await client.hasCollection(name))) {
    await client.deleteCollection(name);
  }
  const col = await getCollection(name, dimension);
  return { db: DB_NAME, collection: col.name, dimension: col.dimension, distance: col.distance };
}

async function engineVersion() {
  try {
    const rows = await client.execute("SELECT VERSION() AS version");
    return rows?.[0]?.version ?? "unknown";
  } catch {
    return "unknown";
  }
}

// ---------------------------------------------------------------------------
// serialized executor: seekdb embedded shares one native connection; serialize
// DB operations to avoid interleaved SQL on the same session.
// ---------------------------------------------------------------------------
let queue = Promise.resolve();
function enqueue(fn) {
  const run = queue.then(fn, fn);
  queue = run.catch(() => {});
  return run;
}

// ---------------------------------------------------------------------------
// app
// ---------------------------------------------------------------------------
const app = express();
app.use(express.json({ limit: "64mb" }));

app.get("/health", async (req, res) => {
  try {
    const info = await enqueue(async () => {
      const col = await getCollection(DEFAULT_COLLECTION, 512);
      const count = await col.count();
      return { engine: await engineVersion(), count, dimension: col.dimension, distance: col.distance };
    });
    res.json({ ok: true, db: DB_NAME, collection: DEFAULT_COLLECTION, ...info });
  } catch (e) {
    res.status(500).json({ ok: false, error: String(e?.message ?? e) });
  }
});

// POST /api/kb/init { dimension } — idempotent init of the default collection
app.post("/api/kb/init", async (req, res) => {
  try {
    const dimension = Number(req.body?.dimension) || 512;
    const info = await enqueue(() => initCollection(dimension));
    res.json({ ok: true, ...info });
  } catch (e) {
    res.status(500).json({ ok: false, error: String(e?.message ?? e) });
  }
});

// POST /api/kb/add { collection?, dimension?, ids, documents, metadatas, embeddings }
app.post("/api/kb/add", async (req, res) => {
  try {
    const { ids, documents, metadatas, embeddings } = req.body ?? {};
    if (!Array.isArray(ids) || !Array.isArray(documents) || !Array.isArray(embeddings) || ids.length === 0) {
      return res.status(400).json({ ok: false, error: "ids/documents/embeddings arrays required" });
    }
    if (ids.length !== documents.length || ids.length !== embeddings.length) {
      return res.status(400).json({ ok: false, error: "ids/documents/embeddings length mismatch" });
    }
    const name = req.body?.collection || DEFAULT_COLLECTION;
    const dimension = Number(req.body?.dimension) || 512;
    const result = await enqueue(async () => {
      const col = await getCollection(name, dimension);
      const t0 = performance.now();
      await col.add({ ids, documents, metadatas: metadatas ?? undefined, embeddings });
      const addMs = performance.now() - t0;
      const t1 = performance.now();
      await col.refresh_index();
      const refreshMs = performance.now() - t1;
      const count = await col.count();
      return { addMs: Math.round(addMs * 10) / 10, refreshMs: Math.round(refreshMs * 10) / 10, count };
    });
    res.json({ ok: true, collection: name, added: ids.length, ...result });
  } catch (e) {
    res.status(500).json({ ok: false, error: String(e?.message ?? e) });
  }
});

// POST /api/kb/search { collection?, dimension?, mode: 'hybrid'|'vector', queryEmbedding, whereDocument?, nResults }
app.post("/api/kb/search", async (req, res) => {
  try {
    const { mode = "hybrid", queryEmbedding, whereDocument, nResults = 10 } = req.body ?? {};
    if (!Array.isArray(queryEmbedding)) {
      return res.status(400).json({ ok: false, error: "queryEmbedding array required" });
    }
    const name = req.body?.collection || DEFAULT_COLLECTION;
    const dimension = Number(req.body?.dimension) || queryEmbedding.length;
    const result = await enqueue(async () => {
      const col = await getCollection(name, dimension);
      const t0 = performance.now();
      let out;
      if (mode === "hybrid") {
        out = await col.hybridSearch({
          query: { whereDocument: whereDocument ?? { $contains: "" } },
          knn: { queryEmbeddings: [queryEmbedding] },
          nResults,
          include: ["documents", "metadatas"],
        });
      } else {
        out = await col.query({
          queryEmbeddings: [queryEmbedding],
          nResults,
          include: ["documents", "metadatas"],
        });
      }
      const dbMs = performance.now() - t0;
      const ids = out.ids?.[0] ?? [];
      const docs = out.documents?.[0] ?? [];
      const metas = out.metadatas?.[0] ?? [];
      const scores = out.distances?.[0] ?? [];
      const items = ids.map((id, i) => ({
        id,
        document: docs[i] ?? null,
        metadata: metas[i] ?? null,
        score: scores[i] != null ? Number(scores[i]) : null,
      }));
      return { items, dbMs: Math.round(dbMs * 10) / 10 };
    });
    res.json({ ok: true, collection: name, mode, ...result });
  } catch (e) {
    res.status(500).json({ ok: false, error: String(e?.message ?? e) });
  }
});

// POST /api/kb/delete { collection?, dimension?, ids }
app.post("/api/kb/delete", async (req, res) => {
  try {
    const { ids } = req.body ?? {};
    if (!Array.isArray(ids)) return res.status(400).json({ ok: false, error: "ids array required" });
    const name = req.body?.collection || DEFAULT_COLLECTION;
    const dimension = Number(req.body?.dimension) || 512;
    const result = await enqueue(async () => {
      const col = await getCollection(name, dimension);
      const t0 = performance.now();
      await col.delete({ ids });
      await col.refresh_index();
      const count = await col.count();
      return { delMs: Math.round((performance.now() - t0) * 10) / 10, count };
    });
    res.json({ ok: true, collection: name, ...result });
  } catch (e) {
    res.status(500).json({ ok: false, error: String(e?.message ?? e) });
  }
});

// POST /api/kb/reset { collection?, dimension? } — drop & recreate a collection
app.post("/api/kb/reset", async (req, res) => {
  try {
    const name = req.body?.collection || DEFAULT_COLLECTION;
    const dimension = Number(req.body?.dimension) || 512;
    const info = await enqueue(() => resetCollection(name, dimension));
    res.json({ ok: true, ...info });
  } catch (e) {
    res.status(500).json({ ok: false, error: String(e?.message ?? e) });
  }
});

// GET /api/kb/stats { collection?, dimension? }
app.get("/api/kb/stats", async (req, res) => {
  try {
    const name = req.query?.collection || DEFAULT_COLLECTION;
    const dimension = Number(req.query?.dimension) || 512;
    const stats = await enqueue(async () => {
      const col = await getCollection(name, dimension);
      return { name: col.name, count: await col.count(), dimension: col.dimension, distance: col.distance };
    });
    res.json({ ok: true, ...stats });
  } catch (e) {
    res.status(500).json({ ok: false, error: String(e?.message ?? e) });
  }
});

// ---------------------------------------------------------------------------
// static hosting: frontend build, model files, eval data, onnxruntime wasm
// ---------------------------------------------------------------------------
const DIST = join(__dirname, "..", "app", "dist");
const MODELS = join(__dirname, "..", "models");
const EVAL = join(__dirname, "..", "data", "eval");
const CORPUS = join(__dirname, "..", "data", "corpus");
if (existsSync(DIST)) app.use(express.static(DIST));
if (existsSync(MODELS)) app.use("/models", express.static(MODELS));
if (existsSync(EVAL)) app.use("/eval-data", express.static(EVAL));
if (existsSync(CORPUS)) app.use("/corpus", express.static(CORPUS));
app.get("/", (req, res) => res.sendFile(join(DIST, "index.html")));

// ---------------------------------------------------------------------------
// boot
// ---------------------------------------------------------------------------
await initCollection(512);
const engine = await engineVersion();
app.listen(PORT, HOST, () => {
  console.log(`[seekdb-kb] listening on http://${HOST}:${PORT}`);
  console.log(`[seekdb-kb] database=${DB_NAME} default_collection=${DEFAULT_COLLECTION} engine=${engine}`);
  console.log(`[seekdb-kb] frontend at http://${HOST}:${PORT}/`);
});
