"""Probe: persist PepsiCo pages into a real runtime and inspect search results.

Runs each public question through search_pdf_pages and prints the returned
page numbers with text snippets, to sanity-check evidence-page behavior
(segment note, legal proceedings, income statement, cash flow statement).
"""
import asyncio
import json
import sys
from pathlib import Path

from powercontext.builtin.runtime import GetMemoryEntryRequest, open_builtin_runtime
from powercontext.sources import SourceDefinitionRegistry, project_source_for_transport
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    parse_pdf_document,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY

sys.path.insert(0, r"C:\Users\wh-yin\Doubao\chats\2026-10-28\new-chat-1\powercontext-eval\competition")

from selftest_support.source_acceptance import EvidencePipeline, persist  # noqa: E402

WORKLOAD = Path(
    r"C:\Users\wh-yin\Doubao\chats\2026-10-28\new-chat-1\powercontext-eval\competition\challenges\source-03-pdf-retrieval\workload\public"
)
OUT = Path(r"C:\Users\wh-yin\Doubao\chats\2026-10-28\new-chat-1\powercontext-product\tools\search-probe-out")
OUT.mkdir(exist_ok=True)


async def main() -> None:
    cases = json.loads((WORKLOAD / "cases.json").read_text())["cases"]
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    observations = []
    for case in cases:
        pages = parse_pdf_document(
            PDFDocumentInput(document_id=case["document_id"], content=(WORKLOAD / case["file"]).read_bytes())
        )
        for page in pages:
            source = await registry.resolve(page)
            observations.append(project_source_for_transport(registry, source))

    config, scope_id, stored = await persist(OUT / "sources.db", PDF_PAGE_SOURCE_DEFINITION, observations)
    async with open_builtin_runtime(config, candidate_pipeline=EvidencePipeline()) as runtime:
        memory = runtime.memory.for_scope(scope_id)
        for _ in range(len(observations) + 1):
            if not (await memory.flush()).processed:
                break
        async with open_builtin_runtime(config) as runtime2:
            memory2 = runtime2.memory.for_scope(scope_id)
            for case in cases:
                for question in case["questions"]:
                    citations = await search_pdf_pages(memory2, question["question"], limit=20)
                    print(f"\n=== {question['financebench_id']} ===")
                    print("Q:", question["question"])
                    print("hits:", len(citations))
                    for i, citation in enumerate(citations, start=1):
                        entry = (await memory2.get(GetMemoryEntryRequest(citation=citation))).entry
                        src = stored[entry.sources[0].source_id]
                        meta = src.projection(TEXT_EVIDENCE_PROJECTION_KEY)["metadata"]
                        text = entry.text.replace("\n", " ")
                        print(f"  #{i} page={meta['page_number']} :: {text[:90]}")


asyncio.run(main())
