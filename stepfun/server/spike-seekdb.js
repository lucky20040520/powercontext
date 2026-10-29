// spike-seekdb.js — smoke-test seekdb embedded on this machine before building the app.
// Exercises: embedded client, schema with vector+fulltext indexes, add with explicit
// embeddings, refresh_index, vector query, hybrid search ($contains + knn), incremental refresh.
import { SeekdbClient, SeekdbAdminClient, Schema, VectorIndexConfig, FulltextIndexConfig } from "seekdb";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const dbPath = join(here, "spike-data-" + Date.now());

console.log("== connect embedded (admin) and create database ==");
const admin = new SeekdbAdminClient({ path: dbPath });
await admin.createDatabase("spike");
const dbs = await admin.listDatabases();
console.log("databases:", dbs.map((d) => d.name));
await admin.close();

console.log("== connect client ==");
const client = new SeekdbClient({ path: dbPath, database: "spike" });

console.log("== create collection (vector+fulltext, embeddingFunction: null) ==");
const schema = new Schema({
  vectorIndex: new VectorIndexConfig({ hnsw: { dimension: 384, distance: "cosine" }, embeddingFunction: null }),
  fulltextIndex: new FulltextIndexConfig("ik", { ik_mode: "smart" }),
});
const collection = await client.createCollection({ name: "docs", schema });
console.log("collection ok, dim =", collection.dimension, "distance =", collection.distance);

function fakeVec(seed) {
  const v = new Array(384);
  let x = seed + 1;
  for (let i = 0; i < 384; i++) {
    x = (x * 1103515245 + 12345) % 2147483648;
    v[i] = (x / 2147483648) * 2 - 1;
  }
  return v;
}

console.log("== add 5 docs with explicit embeddings ==");
const docs = [
  "OceanBase seekdb is an AI-native hybrid search database",
  "Python is a popular programming language for data science",
  "Vector databases enable semantic search over embeddings",
  "Neural networks are inspired by the human brain",
  "Natural language processing helps computers understand text",
];
const t0 = Date.now();
await collection.add({
  ids: ["id1", "id2", "id3", "id4", "id5"],
  documents: docs,
  metadatas: [{ tag: "ai" }, { tag: "code" }, { tag: "db" }, { tag: "ai" }, { tag: "ai" }],
  embeddings: docs.map((_, i) => fakeVec(i)),
});
console.log("added 5 in", Date.now() - t0, "ms");

console.log("== refresh_index ==");
const tr = Date.now();
await collection.refresh_index();
console.log("refresh_index in", Date.now() - tr, "ms; supported =", await collection.isRefreshIndexVersionSupported());

console.log("== vector query (after refresh) ==");
const vq = await collection.query({ queryEmbeddings: [fakeVec(0)], nResults: 3, include: ["documents"] });
console.log("ids:", JSON.stringify(vq.ids), "distances:", JSON.stringify(vq.distances));
console.log("docs:", JSON.stringify(vq.documents));

console.log("== hybrid search: $contains 'database' + knn vec(3) ==");
const hq = await collection.hybridSearch({
  query: { whereDocument: { $contains: "database" } },
  knn: { queryEmbeddings: [fakeVec(3)] },
  nResults: 5,
  include: ["documents", "metadatas"],
});
console.log("ids:", JSON.stringify(hq.ids));
console.log("docs:", JSON.stringify(hq.documents));
console.log("distances/scores:", JSON.stringify(hq.distances));

console.log("== incremental refresh: add 2 more (Chinese), refresh, search again ==");
await collection.add({
  ids: ["id6", "id7"],
  documents: ["学习向量数据库的混合检索方法", "嵌入式数据库非常适合个人知识库应用"],
  metadatas: [{ tag: "zh" }, { tag: "zh" }],
  embeddings: [fakeVec(5), fakeVec(6)],
});
await collection.refresh_index();
console.log("count after incremental add:", await collection.count());

const hq2 = await collection.hybridSearch({
  query: { whereDocument: { $contains: "知识库" } },
  knn: { queryEmbeddings: [fakeVec(6)] },
  nResults: 5,
  include: ["documents"],
});
console.log("hybrid after refresh ids:", JSON.stringify(hq2.ids));
console.log("docs after refresh:", JSON.stringify(hq2.documents));

const vq2 = await collection.query({ queryEmbeddings: [fakeVec(6)], nResults: 3, include: ["documents"] });
console.log("vector after refresh ids:", JSON.stringify(vq2.ids));
console.log("vector after refresh docs:", JSON.stringify(vq2.documents));

await client.close();
console.log("== SPIKE OK ==");
