// probe-refresh.js — verify ob_query_timeout + refresh_index + vector query on embedded seekdb
import { SeekdbClient, SeekdbAdminClient, Schema, VectorIndexConfig, FulltextIndexConfig } from "seekdb";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const dbPath = join(here, "probe-data-" + Date.now());

const admin = new SeekdbAdminClient({ path: dbPath });
await admin.createDatabase("probe");
await admin.close();

const client = new SeekdbClient({ path: dbPath, database: "probe" });

// engine version
try {
  const rows = await client.execute("SELECT VERSION() AS version");
  console.log("VERSION:", JSON.stringify(rows));
} catch (e) {
  console.log("VERSION failed:", e.message);
}

// raise session query timeout (microseconds)
try {
  await client.execute("SET SESSION ob_query_timeout = 600000000");
  console.log("ob_query_timeout raised to 600s");
} catch (e) {
  console.log("SET timeout failed:", e.message);
}

const schema = new Schema({
  vectorIndex: new VectorIndexConfig({ hnsw: { dimension: 384, distance: "cosine" }, embeddingFunction: null }),
  fulltextIndex: new FulltextIndexConfig("ik", { ik_mode: "smart" }),
});
const collection = await client.createCollection({ name: "docs", schema });
console.log("collection ok");

function fakeVec(seed) {
  const v = new Array(384);
  let x = seed + 1;
  for (let i = 0; i < 384; i++) {
    x = (x * 1103515245 + 12345) % 2147483648;
    v[i] = (x / 2147483648) * 2 - 1;
  }
  return v;
}

const docs = [
  "OceanBase seekdb is an AI-native hybrid search database",
  "Python is a popular programming language for data science",
  "Vector databases enable semantic search over embeddings",
  "Neural networks are inspired by the human brain",
  "Natural language processing helps computers understand text",
];
await collection.add({
  ids: ["id1", "id2", "id3", "id4", "id5"],
  documents: docs,
  metadatas: [{ tag: "ai" }, { tag: "code" }, { tag: "db" }, { tag: "ai" }, { tag: "ai" }],
  embeddings: docs.map((_, i) => fakeVec(i)),
});
console.log("added 5");

const t0 = Date.now();
try {
  await collection.refresh_index();
  console.log("refresh_index ok in", Date.now() - t0, "ms; supported =", await collection.isRefreshIndexVersionSupported());
} catch (e) {
  console.log("refresh_index FAILED after", Date.now() - t0, "ms:", e.message);
}

const vq = await collection.query({ queryEmbeddings: [fakeVec(0)], nResults: 3, include: ["documents"] });
console.log("vector ids:", JSON.stringify(vq.ids), "docs:", JSON.stringify(vq.documents), "distances:", JSON.stringify(vq.distances));

await client.close();
console.log("== PROBE DONE ==");
