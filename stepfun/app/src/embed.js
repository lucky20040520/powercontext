// embed.js — Transformers.js wrapper: WebGPU-first with automatic WASM fallback,
// explicit device/dtype selection, local model files, load/warmup timing.

import { pipeline, env } from "@huggingface/transformers";
import { MODELS, DTYPES } from "./config.js";

// onnxruntime-web wasm assets are served from /wasm (copied at build time).
env.backends.onnx.wasm.wasmPaths = "/wasm/";
env.allowLocalModels = true;
env.useBrowserCache = true;

let extractor = null;
let current = null; // { model, variant, device }

/** Detect WebGPU availability. */
export async function detectBackend() {
  if (typeof navigator !== "undefined" && navigator.gpu) {
    try {
      const adapter = await navigator.gpu.requestAdapter();
      if (adapter) return "webgpu";
    } catch {
      /* fall through */
    }
  }
  return "wasm";
}

/**
 * Load the feature-extraction pipeline for (model, variant) on the given device.
 * @param {string} model  key in MODELS
 * @param {string} variant key in DTYPES (fp32/fp16/int8)
 * @param {string} device 'webgpu' | 'wasm'
 * @param {(p: {file:string, progress:number, loaded:number, total:number}) => void} [onProgress]
 * @returns {Promise<{loadMs:number, warmupMs:number, dim:number}>}
 */
export async function loadModel(model, variant, device, onProgress) {
  const cfg = MODELS[model];
  const dt = DTYPES[variant];
  const url = `/models/${cfg.id}/${variant}`;
  const t0 = performance.now();
  extractor = await pipeline("feature-extraction", url, {
    dtype: dt.dtype,
    device,
    progress_callback: onProgress,
  });
  const loadMs = performance.now() - t0;
  // warm-up: first real inference (session compile etc.)
  const w0 = performance.now();
  await embed(["warm up"]);
  const warmupMs = performance.now() - w0;
  current = { model, variant, device };
  return { loadMs, warmupMs, dim: cfg.dim };
}

/** True if a model is loaded (and extractor usable). */
export function isLoaded() {
  return extractor !== null && current !== null;
}

export function currentConfig() {
  return current ? { ...current } : null;
}

/**
 * Embed a batch of texts. Returns number[][] (L2-normalized, dim per model).
 * @param {string[]} texts
 */
export async function embed(texts) {
  if (!extractor) throw new Error("模型未加载");
  const output = await extractor(texts, { pooling: "mean", normalize: true });
  // feature-extraction returns a Tensor of shape [batch, dim]
  return output.tolist();
}
