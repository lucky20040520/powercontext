// config.js — model / dtype registry used across the app.

export const MODELS = {
  bge: {
    id: "bge-small-zh-v1.5",
    label: "bge-small-zh-v1.5",
    dim: 512,
    lang: "zh",
    note: "BAAI/bge-small-zh-v1.5（Xenova ONNX 版）",
  },
  mini: {
    id: "all-MiniLM-L6-v2",
    label: "all-MiniLM-L6-v2",
    dim: 384,
    lang: "en",
    note: "sentence-transformers/all-MiniLM-L6-v2（Xenova ONNX 版，与 seekdb 默认 embedding 同款）",
  },
};

export const DTYPES = {
  fp32: { label: "FP32 基线", dtype: "fp32", file: "model.onnx" },
  fp16: { label: "FP16", dtype: "fp16", file: "model_fp16.onnx" },
  int8: { label: "INT8 (Q8)", dtype: "q8", file: "model_quantized.onnx" },
};

export const MODEL_VARIANTS = ["fp32", "fp16", "int8"];
