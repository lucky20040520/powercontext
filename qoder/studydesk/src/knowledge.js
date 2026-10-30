// 知识库引擎：seekdb 嵌入式（主） + PowerContext 资料存储（自动降级）
//
// 为什么这么设计：seekdb 嵌入式是进程内原生插件，若其初始化被环境阻塞（例如
// 残留进程持有全局句柄），主线程会直接卡死、无法恢复。因此 seekdb 一律
// 懒加载，并在首次使用时用【子进程】探测可用性：子进程卡住只会超时被杀，
// 主进程无感，自动降级为 PowerContext atomic-memory 资料存储。
// 干净环境下 seekdb 正常，2 秒内完成探测，全部功能由 seekdb 提供。
import { spawn } from "node:child_process";
import { existsSync, unlinkSync, rmSync } from "node:fs";
import { embedTexts, embedText, DIMENSION } from "./embedding.js";
import { recordMemory, searchMemory, listMemory, ensureScope } from "./memory.js";

export const KB_KIND = "kb"; // PowerContext 降级路径的资料记忆 kind

let backend = null; // null(未探测) | "seekdb" | "powercontext"

export function getBackend() {
  return backend;
}

async function loadSeekdb() {
  // 懒加载：只有确认 seekdb 可用后才在【本进程】加载原生插件
  return await import("seekdb");
}

// ============ seekdb 探测（子进程，不阻塞主线程） ============

const PROBE_SCRIPT = `
(async () => {
  const { SeekdbAdminClient } = await import("seekdb");
  const a = new SeekdbAdminClient({ path: process.argv[1] });
  await a.createDatabase("probe");
  await a.close();
  console.log("SEEKDB_OK");
  process.exit(0);
})().catch((e) => { console.error("PROBE_ERR " + e.message); process.exit(1); });
`;

function probeSeekdb(config) {
  return new Promise((resolve) => {
    const probeDir = `${config.dbDir}.probe`;
    const child = spawn(process.execPath, ["-e", PROBE_SCRIPT, probeDir], {
      cwd: config.projectRoot,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
    let out = "";
    let done = false;
    const finish = (ok, why) => {
      if (done) return;
      done = true;
      try { child.kill(); } catch { /* 子进程可能已退出 */ }
      resolve(ok);
    };
    child.stdout.on("data", (d) => { out += d; if (out.includes("SEEKDB_OK")) finish(true, "ok"); });
    child.on("error", () => finish(false, "spawn-error"));
    child.on("exit", (code) => finish(code === 0 && out.includes("SEEKDB_OK"), `exit=${code}`));
    setTimeout(() => finish(false, "timeout-15s"), 15000);
  });
}

// ============ seekdb 路径 ============

// 清理本数据目录的引擎运行残留（pid/管道等）。
// seekdb 嵌入式引擎异常退出后会留下 stale 锁文件，阻塞下次打开；
// 若文件正被另一个活跃引擎占用，删除会失败（静默跳过，随后 open 报错走降级）。
function cleanupRunDir(dbDir) {
  const runDir = `${dbDir}/run`;
  for (const name of ["seekdb.pid", "seekdb.clients", "sql.pipe"]) {
    try {
      const p = `${runDir}/${name}`;
      if (existsSync(p)) unlinkSync(p);
    } catch {
      // 被占用时忽略
    }
  }
}

async function ensureDb(seekdb, config) {
  const { SeekdbClient, SeekdbAdminClient } = seekdb;
  cleanupRunDir(config.dbDir);
  const admin = new SeekdbAdminClient({ path: config.dbDir });
  try {
    await admin.createDatabase(config.dbName);
  } catch {
    // database already exists
  }
  await admin.close();

  const client = new SeekdbClient({ path: config.dbDir, database: config.dbName });
  return client;
}

async function getCollection(seekdb, client, name) {
  const { Schema, VectorIndexConfig, FulltextIndexConfig } = seekdb;
  try {
    const collection = await client.createCollection({
      name,
      schema: new Schema({
        vectorIndex: new VectorIndexConfig({
          hnsw: { dimension: DIMENSION, distance: "cosine" },
          embeddingFunction: null,
        }),
        fulltextIndex: new FulltextIndexConfig("ik", { ik_mode: "smart" }),
      }),
    });
    return collection;
  } catch {
    return await client.getCollection(name);
  }
}

let collection = null;

async function getOrCreateCollection(seekdb, client) {
  if (!collection) {
    collection = await getCollection(seekdb, client, "knowledge");
  }
  return collection;
}

async function importTextsSeekdb(seekdb, client, items) {
  const BATCH_SIZE = 8;
  const ids = [];
  const documents = [];
  const metadatas = [];
  const embeddings = [];

  for (let i = 0; i < items.length; i += BATCH_SIZE) {
    const batch = items.slice(i, i + BATCH_SIZE);
    const batchEmbeddings = await embedTexts(batch.map((item) => item.text));

    for (let j = 0; j < batch.length; j++) {
      ids.push(batch[j].id);
      documents.push(batch[j].text);
      // 兼容 item.meta.source 与顶层 item.source 两种写法
      metadatas.push({ source: batch[j].meta?.source || batch[j].source || "unknown", ...(batch[j].meta || {}) });
      embeddings.push(batchEmbeddings[j]);
    }
  }

  const col = await getOrCreateCollection(seekdb, client);
  await col.add({ ids, documents, metadatas, embeddings });
  await col.refresh_index();

  return items.length;
}

async function searchSeekdb(seekdb, client, query, opts = {}) {
  const { nResults = 5 } = opts;
  const vec = await embedText(query);
  const col = await getOrCreateCollection(seekdb, client);
  const result = await col.query({
    queryEmbeddings: [vec],
    nResults,
    include: ["documents", "metadatas", "distances"],
  });

  return result.ids[0].map((id, i) => ({
    id,
    text: result.documents[0][i],
    meta: result.metadatas[0][i],
    distance: result.distances[0][i],
  }));
}

async function hybridSearchSeekdb(seekdb, client, query, keyword, opts = {}) {
  const { nResults = 5 } = opts;
  const vec = await embedText(query);
  const col = await getOrCreateCollection(seekdb, client);
  const result = await col.hybridSearch({
    query: { whereDocument: { $contains: keyword } },
    knn: { queryEmbeddings: [vec], nResults },
    nResults,
    include: ["documents", "metadatas"],
  });

  return result.ids[0].map((id, i) => ({
    id,
    text: result.documents[0][i],
    meta: result.metadatas[0][i],
  }));
}

async function countSeekdb(seekdb, client) {
  const col = await getOrCreateCollection(seekdb, client);
  return await col.count();
}

// ============ PowerContext 降级路径 ============
// 资料作为 atomic-memory（kind=kb）存入 scope，检索走记忆搜索/列表过滤（纯 HTTP）。

function parseSource(text) {
  const m = text.match(/^【来源：(.+?)】/);
  return m ? m[1] : "powercontext";
}

function stripSource(text) {
  return text.replace(/^【来源：.+?】/, "").trim();
}

async function importTextsPc(config, items) {
  await ensureScope(config);
  for (const item of items) {
    const src = item.meta?.source || item.source || "unknown";
    await recordMemory(config, KB_KIND, `【来源：${src}】${item.text}`);
  }
  return items.length;
}

// 降级路径的文本匹配查询：去掉空格等噪声，提高命中率（如 "数学 复习" → "数学复习"）
function normalizeQuery(q) {
  return String(q || "").replace(/\s+/g, "");
}

async function searchPc(config, query, opts = {}) {
  const { nResults = 5 } = opts;
  const { hits } = await searchMemory(config, normalizeQuery(query), { limit: nResults * 3 });
  return hits
    .filter((h) => h.memory.kind === KB_KIND)
    .slice(0, nResults)
    .map((h) => ({
      id: h.artifact_id,
      text: stripSource(h.memory.text),
      meta: { source: parseSource(h.memory.text), degraded: true },
      distance: 0,
    }));
}

async function hybridSearchPc(config, query, keyword, opts = {}) {
  const { nResults = 5 } = opts;
  const { items } = await listMemory(config, { kind: KB_KIND, limit: 100 });
  const kw = normalizeQuery(keyword || query);
  const filtered = items
    .filter((it) => normalizeQuery(it.text).includes(kw))
    .slice(0, nResults)
    .map((it) => ({
      id: it.artifact_id,
      text: stripSource(it.text),
      meta: { source: parseSource(it.text), degraded: true },
    }));
  return filtered;
}

async function countPc(config) {
  const { items } = await listMemory(config, { kind: KB_KIND, limit: 100 });
  return items.length;
}

// ============ 统一入口 ============

/**
 * 探测并确定后端，然后调用 cb(client)。
 * client 始终提供 importTexts / search / hybridSearch / count 四件套。
 */
export async function withClient(cb) {
  const { loadConfig } = await import("./config.js");
  const config = loadConfig();

  if (backend === null) {
    const ok = await probeSeekdb(config);
    backend = ok ? "seekdb" : "powercontext";
    console.log(
      ok
        ? "[知识库] 引擎：seekdb（嵌入式，本地向量 + ik 全文混合检索）"
        : "[知识库] seekdb 引擎当前环境不可用，自动降级为 PowerContext 资料存储（纯 HTTP）"
    );
  }

  if (backend === "seekdb") {
    const seekdb = await loadSeekdb(); // 探测通过后才在本进程加载，不会卡主线程
    const pcClient = {
      importTexts: (items) => importTextsPc(config, items),
      search: (q, o) => searchPc(config, q, o),
      hybridSearch: (q, k, o) => hybridSearchPc(config, q, k, o),
      count: () => countPc(config),
    };

    // 一次完整尝试：打开引擎 + 执行调用方操作。
    let clientRef = null;
    async function attempt() {
      const client = await ensureDb(seekdb, config);
      clientRef = client;
      const seekdbClient = {
        importTexts: (items) => importTextsSeekdb(seekdb, client, items),
        search: (q, o) => searchSeekdb(seekdb, client, q, o),
        hybridSearch: (q, k, o) => hybridSearchSeekdb(seekdb, client, q, k, o),
        count: () => countSeekdb(seekdb, client),
      };
      try {
        return await cb(seekdbClient);
      } finally {
        await client.close().catch(() => {});
        clientRef = null;
      }
    }

    // 带重试地删除数据目录（Windows 下句柄释放可能有延迟）
    async function wipeDataDir() {
      for (let i = 0; i < 4; i++) {
        try {
          rmSync(config.dbDir, { recursive: true, force: true });
          return true;
        } catch {
          await new Promise((r) => setTimeout(r, 500));
        }
      }
      return false;
    }

    try {
      return await attempt();
    } catch (err) {
      const msg = String(err?.message || "");
      if (/pid file locked|already opened|initialized twice/.test(msg)) {
        // 数据目录被残留锁污染 → 重建后重试一次（自愈）
        if (clientRef) await clientRef.close().catch(() => {});
        await new Promise((r) => setTimeout(r, 300));
        const wiped = await wipeDataDir();
        if (wiped) {
          try {
            return await attempt();
          } catch (err2) {
            backend = "powercontext";
            console.log(`[知识库] seekdb 数据目录异常（${err2?.message || msg}），降级为 PowerContext 资料存储`);
            return await cb(pcClient);
          }
        }
        backend = "powercontext";
        console.log(`[知识库] seekdb 数据目录无法重建（仍被占用），降级为 PowerContext 资料存储`);
        return await cb(pcClient);
      }
      throw err;
    }
  }

  // powercontext 降级
  return await cb({
    importTexts: (items) => importTextsPc(config, items),
    search: (q, o) => searchPc(config, q, o),
    hybridSearch: (q, k, o) => hybridSearchPc(config, q, k, o),
    count: () => countPc(config),
  });
}
