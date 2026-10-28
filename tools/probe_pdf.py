"""Probe: extract all pages of the PepsiCo 10-K with pypdf 6.19.0.

Reports per-page UTF-8 byte length of "document_id\npage_text" and token counts
under the competition tokenizer ([a-z]+|\d+), to check the 8192-byte memory limit.
"""
import io
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

PDF = Path(
    r"C:\Users\wh-yin\Doubao\chats\2026-10-28\new-chat-1\powercontext-eval\competition\challenges\source-03-pdf-retrieval\workload\public\pdfs\PEPSICO_2022_10K.pdf"
)
DOCUMENT_ID = "PEPSICO_2022_10K"
TOKEN = re.compile(r"[a-z]+|\d+")

raw = PDF.read_bytes()
reader = PdfReader(io.BytesIO(raw))

over = []
sizes = []
page = 0
total_tokens = 0
empty_pages = 0
for number, pdf_page in enumerate(reader.pages, start=1):
    text = pdf_page.extract_text() or ""
    content = f"{DOCUMENT_ID}\n{text}"
    nbytes = len(content.encode("utf-8"))
    tokens = TOKEN.findall(text.lower())
    sizes.append(nbytes)
    total_tokens += len(tokens)
    if not text.strip():
        empty_pages += 1
    if nbytes > 8192:
        over.append((number, nbytes, len(tokens)))

print(f"pages={len(reader.pages)} bytes={len(raw)} empty_pages={empty_pages}")
print(f"max_bytes={max(sizes)} min_bytes={min(sizes)} total_tokens={total_tokens}")
print(f"pages_over_8192={len(over)}")
for row in over[:50]:
    print(f"  over: page={row[0]} bytes={row[1]} tokens={row[2]}")

# print size histogram
hist = {}
for nbytes in sizes:
    bucket = (nbytes // 1024) * 1024
    hist[bucket] = hist.get(bucket, 0) + 1
print("byte histogram (bucket: count):")
for bucket in sorted(hist):
    print(f"  {bucket}-{bucket+1023}: {hist[bucket]}")
