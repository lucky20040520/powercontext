// main.js — app assembly: state, model loading, ingestion, search, eval, session.

import "./style.css";
import { api } from "./api.js";
import { detectBackend, loadModel, embed, isLoaded, currentConfig } from "./embed.js";
import { chunkDocument } from "./chunk.js";
import { runSingleEval, extractKeywords } from "./eval.js";
import { MODELS, DTYPES, MODEL_VARIANTS } from "./config.js";

const $ = (id) => document.getElementById(id);
const state = {
  backend: "wasm",
  model: "bge",
  variant: "fp32",
  loaded: false,
  docCount: 0,
  engine: "--",
};

const LS_KEY = "seekdb-kb-session-v1";

function saveSession() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({ model: state.model, variant: state.variant, backend: state.backend }));
  } catch {}
}
function loadSession() {
  try {
    const s = JSON.parse(localStorage.getItem(LS_KEY) || "{}");
    if (s.model && MODELS[s.model]) state.model = s.model;
    if (s.variant && DTYPES[s.variant]) state.variant = s.variant;
    if (s.backend === "wasm" || s.backend === "webgpu") state.backend = s.backend;
  } catch {}
}

function fmt(ms) {
  if (ms == null) return "--";
  return ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(2)} s`;
}

function setBadge(el, text, kind = "gray") {
  $(el).textContent = text;
  $(el).className = `badge badge-${kind}`;
}

function refreshBadges() {
  setBadge("badge-backend", `后端：${state.backend.toUpperCase()}${$("chk-force-wasm").checked ? "（强制）" : ""}`, state.backend === "webgpu" ? "green" : "orange");
  setBadge("badge-model", `模型：${MODELS[state.model].label} · ${DTYPES[state.variant].label}`, state.loaded ? "blue" : "gray");
  setBadge("badge-docs", `文档：${state.docCount}`);
  setBadge("badge-engine", `seekdb：${state.engine}`);
}

async function refreshStats() {
  try {
    const s = await api.stats("docs", MODELS[state.model].dim);
    state.docCount = s.count;
  } catch {
    state.docCount = 0;
  }
  refreshBadges();
}

// ---------------------------------------------------------------------------
// boot
// ---------------------------------------------------------------------------
async function boot() {
  loadSession();
  $("sel-model").value = state.model;
  $("sel-dtype").value = state.variant;
  const forced = $("chk-force-wasm").checked;
  state.backend = forced ? "wasm" : await detectBackend();
  refreshBadges();

  try {
    const h = await api.health();
    state.engine = h.engine ?? "--";
    state.docCount = h.count ?? 0;
    setBadge("badge-engine", `seekdb：${state.engine}`);
  } catch (e) {
    setBadge("badge-engine", `seekdb：连接失败（${e.message}）`, "red");
  }
  refreshBadges();
}

// ---------------------------------------------------------------------------
// model loading
// ---------------------------------------------------------------------------
$("btn-load").addEventListener("click", async () => {
  const model = $("sel-model").value;
  const variant = $("sel-dtype").value;
  const forced = $("chk-force-wasm").checked;
  state.model = model;
  state.variant = variant;
  state.backend = forced ? "wasm" : await detectBackend();
  saveSession();
  refreshBadges();
  $("load-status").textContent = `加载 ${MODELS[model].label} ${DTYPES[variant].label}（${state.backend.toUpperCase()}）…`;
  try {
    const r = await loadModel(model, variant, state.backend, (p) => {
      const pct = p?.progress != null ? Math.round(p.progress * 100) : p?.loaded != null && p?.total ? Math.round((p.loaded / p.total) * 100) : null;
      if (pct != null) $("load-status").textContent = `加载模型… ${pct}%`;
    });
    state.loaded = true;
    saveSession();
    $("load-status").textContent = `模型就绪：加载 ${fmt(r.loadMs)}，预热 ${fmt(r.warmupMs)}，维度 ${r.dim}`;
    setBadge("badge-model", `模型：${MODELS[model].label} · ${DTYPES[variant].label} · ${r.dim}维`, "blue");
  } catch (e) {
    state.loaded = false;
    $("load-status").textContent = `模型加载失败：${e.message}`;
    setBadge("badge-model", "模型：加载失败", "red");
  }
});

$("sel-model").addEventListener("change", () => { state.model = $("sel-model").value; state.loaded = false; saveSession(); refreshBadges(); });
$("sel-dtype").addEventListener("change", () => { state.variant = $("sel-dtype").value; state.loaded = false; saveSession(); refreshBadges(); });
$("chk-force-wasm").addEventListener("change", () => {
  state.backend = $("chk-force-wasm").checked ? "wasm" : null;
  state.loaded = false;
  refreshBadges();
});

// ---------------------------------------------------------------------------
// ingestion
// ---------------------------------------------------------------------------
function readFiles() {
  return new Promise((resolve) => {
    const input = $("file-input");
    const files = [...(input.files ?? [])];
    if (!files.length) return resolve([]);
    const out = [];
    let pending = files.length;
    for (const f of files) {
      const reader = new FileReader();
      reader.onload = () => {
        out.push({ filename: f.name, text: String(reader.result ?? "") });
        if (--pending === 0) resolve(out);
      };
      reader.onerror = () => {
        if (--pending === 0) resolve(out);
      };
      reader.readAsText(f);
    }
  });
}

async function fetchSample(url, filename) {
  const res = await fetch(url);
  const text = await res.text();
  return [{ filename, text }];
}

function setProgress(pct, text) {
  const wrap = $("import-progress-wrap");
  wrap.classList.remove("hidden");
  $("import-progress").querySelector("span").style.width = `${Math.max(0, Math.min(100, pct))}%`;
  $("import-progress-text").textContent = text;
}
function hideProgress() {
  $("import-progress-wrap").classList.add("hidden");
}

$("btn-import").addEventListener("click", async () => {
  if (!state.loaded) {
    $("import-status").textContent = "请先加载模型";
    return;
  }
  const pasted = $("txt-paste").value.trim();
  const files = await readFiles();
  const sampleUrl = $("sample-source")?.dataset?.url;
  const docs = [];
  let base = 0;
  if (pasted) {
    docs.push(...chunkDocument(pasted, { filename: "粘贴文本", size: Number($("chunk-size").value) || 180, base: base++ }));
  }
  for (const f of files) {
    docs.push(...chunkDocument(f.text, { filename: f.filename, size: Number($("chunk-size").value) || 180, base: base++ }));
  }
  if (!docs.length) {
    $("import-status").textContent = "没有可导入的内容（粘贴文本或选择文件）";
    return;
  }
  const batch = Math.max(1, Number($("batch-size").value) || 16);
  $("import-status").textContent = `共 ${docs.length} 个分块，开始本地向量化…`;
  const t0 = performance.now();
  try {
    const vectors = [];
    for (let i = 0; i < docs.length; i += batch) {
      const slice = docs.slice(i, i + batch);
      const vecs = await embed(slice.map((d) => d.text));
      vectors.push(...vecs);
      setProgress(((i + slice.length) / docs.length) * 100, `向量化 ${Math.min(i + slice.length, docs.length)}/${docs.length}`);
    }
    const embedMs = performance.now() - t0;
    // write in batches of 100
    let addTotal = 0;
    let refreshTotal = 0;
    for (let i = 0; i < docs.length; i += 100) {
      const ids = [];
      const texts = [];
      const metas = [];
      const vecs = [];
      for (let j = i; j < Math.min(i + 100, docs.length); j++) {
        ids.push(docs[j].id);
        texts.push(docs[j].text);
        metas.push(docs[j].meta);
        vecs.push(vectors[j]);
      }
      const r = await api.add({ collection: "docs", dimension: MODELS[state.model].dim, ids, documents: texts, metadatas: metas, embeddings: vecs });
      addTotal += r.addMs;
      refreshTotal += r.refreshMs;
      setProgress(((i + ids.length) / docs.length) * 100, `写入 seekdb ${Math.min(i + ids.length, docs.length)}/${docs.length}`);
    }
    state.docCount = (await api.stats("docs", MODELS[state.model].dim)).count;
    refreshBadges();
    $("import-status").textContent = `导入完成：${docs.length} 个分块；向量化 ${fmt(embedMs)}（${(docs.length / (embedMs / 1000)).toFixed(1)} doc/s），写入 ${fmt(addTotal)}，索引刷新 ${fmt(refreshTotal)}`;
  } catch (e) {
    $("import-status").textContent = `导入失败：${e.message}`;
  }
  hideProgress();
});

$("btn-sample").addEventListener("click", async () => {
  try {
    const files = await fetchSample("/corpus/zh.txt", "示例语料-中文72篇.txt");
    let base = 0;
    const docs = [];
    for (const f of files) docs.push(...chunkDocument(f.text, { filename: f.filename, size: Number($("chunk-size").value) || 180, base: base++ }));
    $("txt-paste").value = docs.map((d) => d.text).join("\n\n---\n\n");
    $("import-status").textContent = `已载入 ${docs.length} 个分块到输入框，点击「开始导入」写入知识库`;
  } catch (e) {
    $("import-status").textContent = `载入示例失败：${e.message}`;
  }
});
$("btn-sample-en").addEventListener("click", async () => {
  try {
    const files = await fetchSample("/corpus/en.txt", "示例语料-英文24篇.txt");
    let base = 0;
    const docs = [];
    for (const f of files) docs.push(...chunkDocument(f.text, { filename: f.filename, size: Number($("chunk-size").value) || 180, base: base++ }));
    $("txt-paste").value = docs.map((d) => d.text).join("\n\n---\n\n");
    $("import-status").textContent = `已载入 ${docs.length} 个分块到输入框，点击「开始导入」写入知识库`;
  } catch (e) {
    $("import-status").textContent = `载入示例失败：${e.message}`;
  }
});

// ---------------------------------------------------------------------------
// search
// ---------------------------------------------------------------------------
$("btn-search").addEventListener("click", async () => {
  const q = $("inp-query").value.trim();
  if (!q) return;
  if (!state.loaded) {
    $("search-status").textContent = "请先加载模型";
    return;
  }
  const mode = $("sel-mode").value;
  const topk = Number($("inp-topk").value) || 8;
  $("search-status").textContent = "检索中…";
  const t0 = performance.now();
  try {
    const qv = (await embed([q]))[0];
    const embedMs = performance.now() - t0;
    const res = await api.search({
      collection: "docs",
      dimension: MODELS[state.model].dim,
      mode,
      queryEmbedding: qv,
      whereDocument: extractKeywords(q),
      nResults: topk,
    });
    const e2e = performance.now() - t0;
    renderResults(res.items, mode);
    $("search-status").textContent = `${mode === "hybrid" ? "混合检索" : "向量检索"}：查询向量化 ${fmt(embedMs)} · seekdb 检索 ${fmt(res.dbMs)} · 端到端 ${fmt(e2e)} · 全文条件 "${extractKeywords(q)}"`;
  } catch (e) {
    $("search-status").textContent = `检索失败：${e.message}`;
  }
});

function renderResults(items, mode) {
  const box = $("results");
  if (!items.length) {
    box.innerHTML = '<div class="empty">无结果</div>';
    return;
  }
  box.innerHTML = items
    .map(
      (it, i) => `
    <div class="result">
      <div class="result-head">
        <span class="rank">#${i + 1}</span>
        <span class="score">${mode === "hybrid" ? "RRF" : "余弦距离"}：${it.score == null ? "--" : it.score.toFixed(4)}</span>
        <span class="meta">${escapeHtml(it.metadata?.filename ?? it.id)} · chunk ${it.metadata?.chunk ?? ""}</span>
      </div>
      <div class="result-doc">${escapeHtml(it.document)}</div>
    </div>`
    )
    .join("");
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

$("inp-query").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("btn-search").click();
});

// ---------------------------------------------------------------------------
// eval
// ---------------------------------------------------------------------------
const evalLog = [];

async function runOneEvalUI(model, variant, device) {
  $("eval-status").textContent = `评测中：${MODELS[model].label} / ${DTYPES[variant].label} / ${device.toUpperCase()}…（完成后自动继续）`;
  try {
    const r = await runSingleEval({
      model,
      variant,
      device,
      topk: Number($("eval-topk").value) || 5,
      repeats: Number($("eval-repeats").value) || 3,
      onProgress: (p) => {
        $("eval-status").textContent = `评测中：${MODELS[model].label} / ${DTYPES[variant].label} / ${device.toUpperCase()}… ${Math.round(p)}%`;
      },
    });
    evalLog.push(r);
    renderEvalTable();
    $("eval-status").textContent = `完成：${MODELS[model].label} / ${DTYPES[variant].label} / ${device.toUpperCase()}`;
    return r;
  } catch (e) {
    $("eval-status").textContent = `评测失败（${MODELS[model].label}/${DTYPES[variant].label}/${device.toUpperCase()}）：${e.message}`;
    throw e;
  }
}

function renderEvalTable() {
  if (!evalLog.length) {
    $("eval-out").innerHTML = "";
    return;
  }
  const rows = evalLog
    .map((r) => {
      const c = r.config;
      return `<tr>
        <td>${MODELS[c.model].label}</td>
        <td>${DTYPES[c.variant].label}</td>
        <td>${c.device.toUpperCase()}</td>
        <td>${fmt(r.loaded.loadMs)} / ${fmt(r.loaded.warmupMs)}</td>
        <td>${r.ingest.throughput} doc/s</td>
        <td>${fmt(r.ingest.embedMs)}</td>
        <td>${fmt(r.ingest.addMsTotal)}</td>
        <td>${fmt(r.ingest.refreshMsTotal)}</td>
        <td>${fmt(r.perf.queryEmbedMsMedian)}</td>
        <td>${fmt(r.perf.dbMsMedian)}</td>
        <td>${fmt(r.perf.e2eMsMedian)}</td>
        <td>${(r.quality.hybrid.recall * 100).toFixed(1)}% / ${(r.quality.hybrid.ndcg * 100).toFixed(1)}%</td>
        <td>${(r.quality.vector.recall * 100).toFixed(1)}% / ${(r.quality.vector.ndcg * 100).toFixed(1)}%</td>
      </tr>`;
    })
    .join("");
  $("eval-out").innerHTML = `<div class="table-scroll"><table class="eval-table">
    <thead><tr>
      <th>模型</th><th>精度</th><th>后端</th><th>加载/预热</th><th>向量化吞吐</th><th>向量化</th><th>写入</th><th>索引刷新</th>
      <th>查询向量化*</th><th>seekdb检索*</th><th>端到端*</th>
      <th>混合 Recall@K/nDCG@K</th><th>向量 Recall@K/nDCG@K</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table></div>
  <p class="note">* 热查询中位数（重复 ${$("eval-repeats").value} 次，前 3 条查询）；K=${$("eval-topk").value}；评测集：中文 72 篇 / 英文 24 篇。</p>`;
}

$("btn-eval").addEventListener("click", async () => {
  const model = $("sel-model").value;
  const variant = $("sel-dtype").value;
  const forced = $("chk-force-wasm").checked;
  const device = forced ? "wasm" : await detectBackend();
  await runOneEvalUI(model, variant, device);
});

$("btn-eval-all").addEventListener("click", async () => {
  const forced = $("chk-force-wasm").checked;
  const devices = forced ? ["wasm"] : await detectBackend().then((d) => (d === "webgpu" ? ["webgpu", "wasm"] : ["wasm"]));
  $("btn-eval-all").disabled = true;
  try {
    for (const model of Object.keys(MODELS)) {
      for (const variant of MODEL_VARIANTS) {
        for (const device of devices) {
          await runOneEvalUI(model, variant, device);
        }
      }
    }
    $("eval-status").textContent = "全矩阵评测完成";
  } finally {
    $("btn-eval-all").disabled = false;
  }
});

$("btn-export-log").addEventListener("click", () => {
  if (!evalLog.length) {
    $("eval-status").textContent = "尚无评测数据";
    return;
  }
  const blob = new Blob([JSON.stringify({ app: "seekdb-kb", generatedAt: new Date().toISOString(), runs: evalLog }, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "seekdb-kb-eval-log.json";
  a.click();
  URL.revokeObjectURL(a.href);
});

// ---------------------------------------------------------------------------
// session / reset
// ---------------------------------------------------------------------------
$("btn-reset").addEventListener("click", async () => {
  if (!confirm("确定清空知识库（docs 集合并重建）？此操作不可撤销。")) return;
  try {
    await api.reset({ collection: "docs", dimension: MODELS[state.model].dim });
    state.docCount = 0;
    refreshBadges();
    $("foot-info").textContent = "知识库已清空";
  } catch (e) {
    $("foot-info").textContent = `清空失败：${e.message}`;
  }
});

$("btn-sample").textContent = "导入示例语料（中文 72 篇）";
boot();
