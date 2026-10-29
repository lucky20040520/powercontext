export const MEMORY_KINDS = {
  STATUS: "status",
  DECISION: "decision",
  CONSTRAINT: "constraint",
  WEAKPOINT: "weakpoint",
};

async function request(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`HTTP ${res.status}: ${text}`);
  }

  return res.json();
}

export async function ensureScope(config) {
  if (config.scopeId) return config.scopeId;

  const data = await request(`${config.pcUrl}/v1/scopes`, {
    title: "studydesk",
    summary: "研习台记忆空间",
    idempotency_key: randomUUID(), // 当前 PowerContext 服务端要求 scope 创建必须携带幂等键
  });

  config.scopeId = data.scope_id; // 缓存到 config，后续调用不再重复创建
  console.log(`[memory] 已创建 scope: ${data.scope_id}（建议写入 .env: POWERCONTEXT_SCOPE_ID=${data.scope_id}）`);
  return data.scope_id;
}

import { randomUUID } from "node:crypto";

export async function recordMemory(config, kind, text) {
  const scopeId = await ensureScope(config);
  const body = { family: "atomic-memory", content: { kind, text } };
  const data = await request(`${config.pcUrl}/v1/scopes/${scopeId}/artifacts`, body);

  return { artifact_id: data.artifact_id, revision: data.revision };
}

export async function searchMemory(config, query, { limit = 5 } = {}) {
  const scopeId = await ensureScope(config);
  const data = await request(`${config.pcUrl}/v1/atomic-memory/search`, {
    scope_id: scopeId,
    query,
    limit,
  });

  return { mode: data.mode, hits: data.hits };
}

export async function listMemory(config, { kind, limit = 20 } = {}) {
  const scopeId = await ensureScope(config);
  const body = { scope_id: scopeId, limit };
  if (kind) body.kind = kind;

  const data = await request(`${config.pcUrl}/v1/atomic-memory/list`, body);
  return { items: data.items };
}
