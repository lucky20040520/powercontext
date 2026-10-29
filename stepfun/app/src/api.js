// api.js — thin REST client for the seekdb embedded backend.

const BASE = "";

async function post(path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}

async function get(path) {
  const res = await fetch(`${BASE}${path}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}

export const api = {
  health: () => get("/health"),
  init: (dimension) => post("/api/kb/init", { dimension }),
  add: ({ collection, dimension, ids, documents, metadatas, embeddings }) =>
    post("/api/kb/add", { collection, dimension, ids, documents, metadatas, embeddings }),
  search: ({ collection, dimension, mode, queryEmbedding, whereDocument, nResults }) =>
    post("/api/kb/search", { collection, dimension, mode, queryEmbedding, whereDocument, nResults }),
  del: ({ collection, dimension, ids }) => post("/api/kb/delete", { collection, dimension, ids }),
  reset: ({ collection, dimension }) => post("/api/kb/reset", { collection, dimension }),
  stats: (collection, dimension) => get(`/api/kb/stats?collection=${encodeURIComponent(collection)}&dimension=${dimension}`),
};
