import { loadConfig } from "./config.js";

export const DIMENSION = 512;

let extractorPromise = null;

async function getEmbedder() {
  if (!extractorPromise) {
    extractorPromise = (async () => {
      const config = loadConfig();
      const { pipeline, env } = await import("@huggingface/transformers");
      env.remoteHost = config.hfEndpoint;
      const extractor = await pipeline("feature-extraction", config.embedModel, {
        dtype: config.embedDtype,
        cache_dir: config.embedCache,
      });
      return extractor;
    })();
  }
  return extractorPromise;
}

export async function embedTexts(texts) {
  const extractor = await getEmbedder();
  const out = await extractor(texts, { pooling: "mean", normalize: true });
  return out.tolist();
}

export async function embedText(text) {
  const [vec] = await embedTexts([text]);
  return vec;
}
