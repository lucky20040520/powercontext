// chunk.js — text chunking for knowledge-base ingestion.

/**
 * Split a piece of text into chunks of ~size chars with overlap, preferring to
 * break at paragraph / sentence / punctuation boundaries.
 */
export function chunkText(text, size = 180, overlap = 20) {
  const clean = (text || "").replace(/\r\n/g, "\n").trim();
  if (!clean) return [];
  if (clean.length <= size) return [clean];

  const chunks = [];
  let start = 0;
  while (start < clean.length) {
    let end = Math.min(start + size, clean.length);
    if (end < clean.length) {
      // back off to the last sentence/line/punct boundary within the window
      const windowText = clean.slice(start, end);
      const boundary = Math.max(
        windowText.lastIndexOf("\n"),
        windowText.lastIndexOf("。"),
        windowText.lastIndexOf("！"),
        windowText.lastIndexOf("？"),
        windowText.lastIndexOf("；"),
        windowText.lastIndexOf("；"),
        windowText.lastIndexOf("."),
        windowText.lastIndexOf(";"),
        windowText.lastIndexOf(" ")
      );
      if (boundary > Math.floor(size * 0.5)) {
        end = start + boundary + 1;
      }
    }
    chunks.push(clean.slice(start, end).trim());
    if (end >= clean.length) break;
    start = Math.max(end - overlap, start + 1);
  }
  return chunks.filter((c) => c.length > 0);
}

/**
 * Split a whole document (file content) into named chunks with metadata.
 * Returns [{ id, text, meta }] where meta carries filename/chunk index.
 */
export function chunkDocument(text, { filename = "粘贴文本", size = 180, overlap = 20, base = 0 } = {}) {
  const parts = chunkText(text, size, overlap);
  return parts.map((t, i) => ({
    id: `doc-${base}-${i}`,
    text: t,
    meta: { filename, chunk: i, total: parts.length },
  }));
}
