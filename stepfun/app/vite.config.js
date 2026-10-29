import { defineConfig } from "vite";
import { copyFileSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

// Copy onnxruntime-web wasm assets (incl. WebGPU "jsep" builds) into dist/wasm
// so the app is fully self-contained and needs no CDN.
function copyOrtWasm() {
  return {
    name: "copy-ort-wasm",
    closeBundle() {
      const src = join(__dirname, "node_modules", "onnxruntime-web", "dist");
      const dst = join(__dirname, "dist", "wasm");
      mkdirSync(dst, { recursive: true });
      let n = 0;
      for (const f of readdirSync(src)) {
        if (f.endsWith(".wasm") || f.endsWith(".mjs")) {
          copyFileSync(join(src, f), join(dst, f));
          n++;
        }
      }
      console.log(`[copy-ort-wasm] copied ${n} files to dist/wasm`);
    },
  };
}

export default defineConfig({
  base: "./",
  plugins: [copyOrtWasm()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:3000",
      "/models": "http://127.0.0.1:3000",
      "/eval-data": "http://127.0.0.1:3000",
    },
  },
});
