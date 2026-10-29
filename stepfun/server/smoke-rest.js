// smoke-rest.js — quick REST-level smoke test against the running server.
const BASE = "http://127.0.0.1:3000";

async function post(path, body) {
  const res = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  console.log(path, "->", res.status, JSON.stringify(data).slice(0, 300));
  if (!res.ok || data.ok === false) throw new Error(path + ": " + (data.error || res.status));
  return data;
}

function vec512(seed) {
  const v = new Array(512);
  for (let i = 0; i < 512; i++) v[i] = Math.sin(seed * (i + 1)) * 0.5 + 0.5;
  const norm = Math.sqrt(v.reduce((s, x) => s + x * x, 0));
  return v.map((x) => x / norm);
}

(async () => {
  await post("/api/kb/init", { dimension: 512 });
  await post("/api/kb/reset", { collection: "docs", dimension: 512 }); // idempotent run: clear docs first
  const ids = ["smoke-1", "smoke-2", "smoke-3"];
  const documents = [
    "数据库索引是一种用于加速数据查询的数据结构，常见的有 B 树索引和哈希索引。",
    "向量数据库专门用于存储和检索高维向量，通过余弦相似度衡量语义相关性。",
    "混合检索结合了向量语义检索和关键词全文检索两种方式，常见融合算法是 RRF 倒数排名融合。",
  ];
  const embeddings = [vec512(1), vec512(2), vec512(3)];
  await post("/api/kb/add", { collection: "docs", dimension: 512, ids, documents, metadatas: ids.map((id) => ({ filename: id, chunk: 0 })), embeddings });
  await post("/api/kb/reset", { collection: "eval", dimension: 512 });
  const s = await post("/api/kb/search", {
    collection: "docs",
    dimension: 512,
    mode: "hybrid",
    queryEmbedding: vec512(2),
    whereDocument: "向量数据库",
    nResults: 3,
  });
  console.log("hybrid items:", JSON.stringify(s.items?.map((i) => ({ id: i.id, score: i.score, doc: (i.document || "").slice(0, 20) })), null, 1));
  const st = await (async () => {
    const res = await fetch(BASE + "/api/kb/stats?collection=docs&dimension=512");
    const data = await res.json();
    console.log("/api/kb/stats", "->", res.status, JSON.stringify(data).slice(0, 300));
    if (!res.ok || data.ok === false) throw new Error("/api/kb/stats: " + (data.error || res.status));
    return data;
  })();
  console.log("stats:", JSON.stringify(st));
})().catch((e) => {
  console.error("SMOKE FAIL:", e.message);
  process.exit(1);
});
