import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
export const PROJECT_ROOT = resolve(__dirname, "..");

function parseEnv(filePath) {
  const result = {};
  try {
    const content = readFileSync(filePath, "utf-8");
    for (const line of content.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eqIdx = trimmed.indexOf("=");
      if (eqIdx === -1) continue;
      const key = trimmed.slice(0, eqIdx).trim();
      const value = trimmed.slice(eqIdx + 1).trim();
      result[key] = value;
    }
  } catch {
    // .env not found, use defaults
  }
  return result;
}

export function loadConfig() {
  const env = parseEnv(resolve(PROJECT_ROOT, ".env"));

  return {
    projectRoot: PROJECT_ROOT,
    dbDir: resolve(PROJECT_ROOT, env.STUDYDESK_DB_DIR || "./data/seekdb"),
    dbName: env.STUDYDESK_DB_NAME || "studydesk",

    embedModel: env.STUDYDESK_EMBED_MODEL || "Xenova/bge-small-zh-v1.5",
    embedDtype: env.STUDYDESK_EMBED_DTYPE || "q8",
    embedCache: resolve(PROJECT_ROOT, env.STUDYDESK_EMBED_CACHE || "./.cache"),
    hfEndpoint: env.STUDYDESK_HF_ENDPOINT || "https://hf-mirror.com",

    pcUrl: env.POWERCONTEXT_SERVER_URL || "http://127.0.0.1:8000",
    scopeId: env.POWERCONTEXT_SCOPE_ID || "",
    webPort: parseInt(env.STUDYDESK_WEB_PORT || "8787", 10),
    userName: env.STUDYDESK_USER_NAME || "同学",
  };
}
