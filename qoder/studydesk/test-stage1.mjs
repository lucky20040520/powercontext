import { loadConfig, PROJECT_ROOT } from "./src/config.js";
import { embedText, embedTexts, DIMENSION } from "./src/embedding.js";
import { ensureDb, getCollection, importTexts, search, count, withClient } from "./src/knowledge.js";
import { ensureScope, recordMemory, searchMemory, listMemory, MEMORY_KINDS } from "./src/memory.js";

console.log("=== Stage 1 模块测试 ===\n");

// 测试 1: Config
console.log("1️⃣  测试 config.js");
const config = loadConfig();
console.log("   ✓ 配置加载成功");
console.log("   - dbDir:", config.dbDir);
console.log("   - dbName:", config.dbName);
console.log("   - embedModel:", config.embedModel);
console.log("   - PROJECT_ROOT:", PROJECT_ROOT);
console.log();

// 测试 2: Embedding
console.log("2️⃣  测试 embedding.js（首次运行会下载模型，请耐心等待）");
try {
  const vec = await embedText("测试文本");
  console.log("   ✓ 单文本向量化成功，维度:", vec.length);
  console.log("   - 预期维度:", DIMENSION);
  console.log("   - 维度匹配:", vec.length === DIMENSION ? "✓" : "✗");

  const vecs = await embedTexts(["文本1", "文本2", "文本3"]);
  console.log("   ✓ 批量向量化成功，数量:", vecs.length);
  console.log("   - 每个向量维度:", vecs[0].length);
} catch (err) {
  console.log("   ✗ 向量化失败:", err.message);
}
console.log();

// 测试 3: Knowledge (seekdb)
console.log("3️⃣  测试 knowledge.js");
try {
  await withClient(async (client) => {
    console.log("   ✓ 数据库连接成功");

    const collection = await getCollection(client, "test_collection");
    console.log("   ✓ 集合创建/获取成功");

    const testItems = [
      { id: "doc1", text: "JavaScript 是一种编程语言", meta: { category: "programming" } },
      { id: "doc2", text: "Python 也很流行", meta: { category: "programming" } },
      { id: "doc3", text: "机器学习是人工智能的一个分支", meta: { category: "ai" } },
    ];

    const imported = await importTexts(client, testItems);
    console.log("   ✓ 导入文档成功，数量:", imported);

    const total = await count(client);
    console.log("   ✓ 文档总数:", total);

    const results = await search(client, "编程语言", { nResults: 2 });
    console.log("   ✓ 向量搜索成功，返回结果:", results.length);
    console.log("   - 第一条:", results[0].text, "(距离:", results[0].distance.toFixed(4), ")");
  });
} catch (err) {
  console.log("   ✗ 知识库操作失败:", err.message);
}
console.log();

// 测试 4: Memory (PowerContext)
console.log("4️⃣  测试 memory.js");
console.log("   注意：需要 PowerContext Server 运行在", config.pcUrl);
try {
  const scopeId = await ensureScope(config);
  console.log("   ✓ Scope 已就绪:", scopeId);

  const { artifact_id, revision } = await recordMemory(
    config,
    MEMORY_KINDS.STATUS,
    "测试记忆：Stage 1 模块实现完成"
  );
  console.log("   ✓ 记录记忆成功");
  console.log("   - artifact_id:", artifact_id);
  console.log("   - revision:", revision);

  const searchResult = await searchMemory(config, "Stage 1", { limit: 3 });
  console.log("   ✓ 搜索记忆成功，命中:", searchResult.hits?.length || 0);

  const listResult = await listMemory(config, { kind: MEMORY_KINDS.STATUS, limit: 5 });
  console.log("   ✓ 列表记忆成功，数量:", listResult.items?.length || 0);
} catch (err) {
  console.log("   ⚠  记忆服务不可用（可能未启动）:", err.message);
  console.log("   提示：请先启动 PowerContext Server");
}
console.log();

console.log("=== 测试完成 ===");
