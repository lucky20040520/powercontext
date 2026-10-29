#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
prepare_models.py — download & organize ONNX embedding models for the local KB app.

Model source: Xenova ONNX conversions on Hugging Face (mirror-friendly).
Variants per model:
  fp32 : onnx/model.onnx          (32-bit float baseline)
  fp16 : onnx/model_fp16.onnx     (16-bit float, WebGPU native)
  int8 : onnx/model_quantized.onnx (int8 dynamic quantization, WASM friendly)

Output layout (served by the app at /models/<modelId>/<variant>/):
  models/<modelId>/<variant>/{config.json,tokenizer.json,tokenizer_config.json,
                               special_tokens_map.json,vocab.txt,onnx/*.onnx}

Usage:
  python prepare_models.py            # all models & variants
  python prepare_models.py --model bge-small-zh-v1.5 --variant fp16
  HF_ENDPOINT=https://hf-mirror.com python prepare_models.py   # China mirror
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # stepfun/
MODELS_DIR = ROOT / "models"
MANIFEST = ROOT / "docs" / "模型清单.json"

HF_ENDPOINT = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")

MODELS = {
    "bge-small-zh-v1.5": {"id": "Xenova/bge-small-zh-v1.5", "dim": 512, "lang": "zh"},
    "all-MiniLM-L6-v2": {"id": "Xenova/all-MiniLM-L6-v2", "dim": 384, "lang": "en"},
}

VARIANT_FILES = {
    "fp32": {"dtype": "fp32", "file": "onnx/model.onnx", "target": "onnx/model.onnx"},
    "fp16": {"dtype": "fp16", "file": "onnx/model_fp16.onnx", "target": "onnx/model_fp16.onnx"},
    "int8": {"dtype": "q8", "file": "onnx/model_quantized.onnx", "target": "onnx/model_quantized.onnx"},
}

# small config files copied as-is into every variant dir
AUX_FILES = ["config.json", "tokenizer.json", "tokenizer_config.json", "special_tokens_map.json", "vocab.txt"]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, retries: int = 4) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [skip] {dest.name} exists ({dest.stat().st_size} bytes)")
        return
    for attempt in range(1, retries + 1):
        try:
            print(f"  [get ] {url} (attempt {attempt})")
            req = urllib.request.Request(url, headers={"User-Agent": "prepare_models/1.0"})
            with urllib.request.urlopen(req, timeout=300) as resp, open(tmp, "wb") as out:
                total = int(resp.headers.get("Content-Length") or 0)
                done = 0
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if total:
                        pct = done * 100 // total
                        sys.stdout.write(f"\r  {done//1048576}MB/{total//1048576}MB {pct}%  ")
                        sys.stdout.flush()
            sys.stdout.write("\n")
            os.replace(tmp, dest)
            return
        except Exception as e:  # noqa: BLE001 — network flakiness, retry
            sys.stdout.write(f"\n  [retry {attempt}/{retries}] {e}\n")
            sys.stdout.flush()
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            if attempt == retries:
                raise


def prepare_model(model_id: str, variants: list[str], force: bool = False) -> dict:
    meta = MODELS[model_id]
    hf_id = meta["id"]
    entry = {"model": model_id, "hf": hf_id, "dim": meta["dim"], "lang": meta["lang"], "variants": {}}
    for variant in variants:
        spec = VARIANT_FILES[variant]
        vdir = MODELS_DIR / model_id / variant
        (vdir / "onnx").mkdir(parents=True, exist_ok=True)

        # aux files
        for aux in AUX_FILES:
            url = f"{HF_ENDPOINT}/{hf_id}/resolve/main/{aux}"
            dest = vdir / aux
            if force or not dest.exists():
                download(url, dest)

        # onnx weight file
        url = f"{HF_ENDPOINT}/{hf_id}/resolve/main/{spec['file']}"
        dest = vdir / spec["target"]
        if force or not dest.exists():
            download(url, dest)

        size = dest.stat().st_size if dest.exists() else 0
        sha = sha256_of(dest) if size else None
        entry["variants"][variant] = {
            "dtype": spec["dtype"],
            "file": spec["target"],
            "size_bytes": size,
            "sha256": sha,
        }
        print(f"[ok] {model_id}/{variant}: {size} bytes sha256={sha[:12]}…")
    return entry


def main():
    ap = argparse.ArgumentParser(description="prepare ONNX embedding models")
    ap.add_argument("--model", choices=list(MODELS), default=None)
    ap.add_argument("--variant", choices=list(VARIANT_FILES), default=None)
    ap.add_argument("--force", action="store_true", help="re-download even if file exists")
    args = ap.parse_args()

    models = [args.model] if args.model else list(MODELS)
    variants = [args.variant] if args.variant else list(VARIANT_FILES)

    manifest = {"source": f"{HF_ENDPOINT}", "generated": None, "models": {}}
    for m in models:
        entry = prepare_model(m, variants, force=args.force)
        manifest["models"][m] = entry

    manifest["generated"] = None  # filled by caller or left as-is
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[ok] manifest written to {MANIFEST}")


if __name__ == "__main__":
    main()
