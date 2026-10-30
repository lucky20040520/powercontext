# Stage 1 规格：核心引擎（embedding / knowledge / memory / config）

请实现以下 4 个文件（ESM，Node >=22）。所有 API 用法已经过本机实测验证，请严格照此实现，不要发明其他 API。

## 1. src/config.js
- 从项目根目录 `.env` 读取配置（自己实现极简解析即可，不需要 dotenv 依赖；.env 不存在则用默认值）。
- 返回对象：
  - dbDir（默认 `./data/seekdb`，相对项目根）、dbName（默认 `studydesk`）
  - embedModel（默认 `Xenova/bge-small-zh-v1.5`）、embedDtype（默认 `q8`）、embedCache（默认 `./.cache`）、hfEndpoint（默认 `https://hf-mirror.com`）
  - pcUrl（默认 `http://127.0.0.1:8000`）、scopeId（默认空字符串）、webPort（默认 8787）、userName（默认 `同学`）
- 导出 `loadConfig()`（同步）、`PROJECT_ROOT`（项目根绝对路径）。

## 2. src/embedding.js
- 模块级懒加载单例：`getEmbedder()` 返回 Promise，首次调用时：
  ```js
  import { pipeline, env } from "@huggingface/transformers";
  env.remoteHost = config.hfEndpoint;
  const extractor = await pipeline("feature-extraction", config.embedModel, {
    dtype: config.embedDtype,
    cache_dir: config.embedCache,   // 支持绝对路径（如 D:/qoder-model-cache）
  });
  ```
- 导出 `embedTexts(texts: string[]) -> Promise<number[][]>`：调用 `extractor(texts, { pooling: "mean", normalize: true })` 再 `out.tolist()`。
- 导出 `embedText(text) -> Promise<number[]>`（单条）。
- 导出 `DIMENSION = 512` 常量。

## 3. src/knowledge.js（seekdb 引擎封装）
- import 自 `seekdb`：`{ SeekdbClient, SeekdbAdminClient, Schema, VectorIndexConfig, FulltextIndexConfig }`（npm 包名 `seekdb@1.4.0`）。
- `ensureDb(config)`：若库不存在则用 `SeekdbAdminClient({ path: dbDir })` + `createDatabase(dbName)` 建库并 close；然后 `SeekdbClient({ path: dbDir, database: dbName })` 返回 client。
- `getCollection(client, name)`：`client.createCollection({ name, schema: new Schema({ vectorIndex: new VectorIndexConfig({ hnsw: { dimension: 512, distance: "cosine" }, embeddingFunction: null }), fulltextIndex: new FulltextIndexConfig("ik", { ik_mode: "smart" }) }) })`；若已存在集合（尝试 create 抛错）则跳过创建。
- `importTexts(client, items)`：items = `[{ id, text, meta }]`。先 `embedTexts` 批量向量化（分批 8 条），再 `collection.add({ ids, documents, metadatas, embeddings })`，随后 `collection.refresh_index()`。返回写入条数。
- `search(client, query, opts)`：`embedText(query)` → `collection.query({ queryEmbeddings: [vec], nResults, include: ["documents","metadatas","distances"] })`，把结果映射为 `[{ id, text, meta, distance }]`。
- `hybridSearch(client, query, keyword, opts)`：`embedText(query)` → `collection.hybridSearch({ query: { whereDocument: { $contains: keyword } }, knn: { queryEmbeddings: [vec], nResults }, nResults, include: ["documents","metadatas"] })`，映射为 `[{ id, text, meta }]`。
- `count(client)`：`collection.count()`。
- 注意：同一进程同一时间只保持一个 client 连接；每次用完后 `await client.close()`（重要，否则占端口 2881）。提供 `withClient(cb)` 帮助函数：ensureDb → cb(client) → close。

## 4. src/memory.js（PowerContext HTTP 客户端，Node 原生 fetch）
- `ensureScope(config)`：若 config.scopeId 为空，`POST {pcUrl}/v1/scopes` body `{ title: "studydesk", summary: "研习台记忆空间" }`，取返回的 scope_id，写回 config.scopeId（并提示用户可写入 .env）。
- `recordMemory(config, kind, text)`：`POST {pcUrl}/v1/scopes/{scopeId}/artifacts` body `{ family: "atomic-memory", content: { kind, text } }`，返回 `{ artifact_id, revision }`。
- `searchMemory(config, query, { limit = 5 } = {})`：`POST {pcUrl}/v1/atomic-memory/search` body `{ scope_id, query, limit }`，返回 `{ mode, hits }`（hits 元素含 `memory.kind/memory.text/memory.artifact.artifact_id/score/matched_by`）。
- `listMemory(config, { kind, limit = 20 } = {})`：`POST {pcUrl}/v1/atomic-memory/list` body `{ scope_id, ...(kind && {kind}), limit }`，返回 `{ items }`（元素含 `kind/text/state/artifact.artifact_id`）。
- 所有请求 JSON UTF-8；失败时抛出带状态码与响应体的错误。
- 导出常量 `MEMORY_KINDS = { STATUS:"status", DECISION:"decision", CONSTRAINT:"constraint", WEAKPOINT:"weakpoint" }`。
