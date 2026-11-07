# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0

"""Independent relevance audit using original PDFs and the public evidence pipeline.

The annotations in this benchmark were authored independently from the original
PDFs. They are not FinanceBench gold and do not establish the platform's score.
Product src never imports this script or its annotations. Downloads are an
explicit preparation operation; evaluation itself is entirely offline.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import re
import tempfile
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _prepare(manifest: dict[str, Any], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for document in manifest["documents"]:
        path = directory / document["file"]
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == document["sha256"]:
            continue
        url = document["url"]
        _require(url.startswith("https://raw.githubusercontent.com/patronus-ai/financebench/"), "Unexpected PDF host")
        with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 - pinned HTTPS original-PDF URLs
            content = response.read()
        _require(hashlib.sha256(content).hexdigest() == document["sha256"], f"PDF digest mismatch: {path.name}")
        path.write_bytes(content)
        print(json.dumps({"downloaded_original_pdf": path.name, "bytes": len(content)}), flush=True)


async def _evaluate(manifest: dict[str, Any], directory: Path, minimum: float) -> dict[str, Any]:
    from powercontext.builtin.runtime import GetMemoryEntryRequest, open_builtin_runtime
    from powercontext.sources import SourceDefinitionRegistry, project_source_for_transport
    from powercontext.sources.pdf_pages import (
        PDF_PAGE_SOURCE_DEFINITION,
        PDFDocumentInput,
        parse_pdf_document,
        search_pdf_pages,
    )
    from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY

    # The organizer-owned public helper captures all Sources, retries one input,
    # applies the fixed text pipeline, drains it and reopens the real Runtime.
    persist = importlib.import_module("selftest_support.source_acceptance").persist
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    observations = []
    maximum_page_bytes = 0
    started = time.monotonic()
    for document in manifest["documents"]:
        content = (directory / document["file"]).read_bytes()
        _require(hashlib.sha256(content).hexdigest() == document["sha256"], "Original PDF digest mismatch")
        pages = parse_pdf_document(PDFDocumentInput(document_id=document["document_id"], content=content))
        _require(len(pages) == len(document["independent_term_counts"]), "Physical-page coverage mismatch")
        document_page_bytes = 0
        for page, expected_count in zip(pages, document["independent_term_counts"], strict=True):
            document_page_bytes = max(
                document_page_bytes, len(f"{page.document_id}\n{page.text}".strip().encode("utf-8"))
            )
            terms = Counter(re.findall(r"[a-z]+|\d+", page.text.lower()))
            count = terms.total()
            reference_terms = document.get("independent_page_tokens", {}).get(str(page.page_number))
            if reference_terms is not None:
                reference = Counter(reference_terms)
                f1 = 2 * (terms & reference).total() / (count + reference.total()) if count or reference else 1.0
                _require(f1 >= 0.95, f"Independent whole-page F1 below 0.95: {page.document_id}:{page.page_number}")
            _require(
                count == 0 if expected_count == 0 else 0.9 <= count / expected_count <= 1.1,
                f"Independent page term-count mismatch: {page.document_id}:{page.page_number}",
            )
            source = await registry.resolve(page)
            observations.append(project_source_for_transport(registry, source))
        maximum_page_bytes = max(maximum_page_bytes, document_page_bytes)
        print(
            json.dumps({
                "parsed_original_pdf": document["document_id"],
                "physical_pages": len(pages),
                "maximum_page_utf8_bytes": document_page_bytes,
            }),
            flush=True,
        )
    parsing_seconds = time.monotonic() - started
    with tempfile.TemporaryDirectory(prefix="pdf-relevance-") as work:
        started = time.monotonic()
        config, scope_id, stored = await persist(Path(work), PDF_PAGE_SOURCE_DEFINITION, observations)
        persistence_seconds = time.monotonic() - started
        print(json.dumps({"persisted_pages": len(observations), "seconds": persistence_seconds}), flush=True)
        results: list[dict[str, Any]] = []
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            for case in manifest["cases"]:
                started = time.monotonic()
                citations = await search_pdf_pages(memory, case["question"], limit=20)
                seconds = time.monotonic() - started
                _require(0 < len(citations) <= 20, "Invalid result limit")
                locations = []
                for citation in citations:
                    record = await memory.get(GetMemoryEntryRequest(citation=citation))
                    _require(record.citation == citation and len(record.entry.sources) == 1, "Inexact page citation")
                    source = stored[record.entry.sources[0].source_id].projection(TEXT_EVIDENCE_PROJECTION_KEY)
                    _require(record.entry.text == source["content"].strip(), "Citation text mismatch")
                    metadata = source["metadata"]
                    _require(metadata["document_id"] == case["document_id"], "Wrong report returned")
                    locations.append(metadata["page_number"])
                _require(len(locations) == len(set(locations)), "Duplicate pages")
                expected = set(case["physical_pages"])
                result = {**case, "retrieved": locations, "hits": sorted(expected & set(locations)), "seconds": seconds}
                results.append(result)
                print(
                    json.dumps({"case": case["id"], "hits": result["hits"], "expected": sorted(expected)}), flush=True
                )
    summary = {}
    for split in dict.fromkeys(case["split"] for case in results):
        group = [case for case in results if case["split"] == split]
        counts = {"questions": len(group), "evidence_pages": sum(len(set(case["physical_pages"])) for case in group)}
        counts["hits"] = sum(len(case["hits"]) for case in group)
        summary[split] = {**dict(counts), "recall_at_20": counts["hits"] / counts["evidence_pages"]}
    report = {
        "kind": "independent benchmark, not official gold or platform recall",
        "documents": len(manifest["documents"]),
        "physical_pages": len(observations),
        "maximum_page_utf8_bytes": maximum_page_bytes,
        "parsing_seconds": parsing_seconds,
        "persistence_seconds": persistence_seconds,
        "maximum_query_seconds": max(case["seconds"] for case in results),
        "summary": summary,
        "results": results,
    }
    print(json.dumps({key: value for key, value in report.items() if key != "results"}), flush=True)
    for split, metrics in summary.items():
        _require(metrics["recall_at_20"] >= minimum, f"Independent recall below {minimum}: {split}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--minimum-recall", type=float, default=0.95)
    args = parser.parse_args()
    manifest = json.loads(args.cases.read_text(encoding="utf-8"))
    if args.download_only:
        _prepare(manifest, args.pdf_dir)
    else:
        report = asyncio.run(_evaluate(manifest, args.pdf_dir, args.minimum_recall))
        if args.output is not None:
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Public check annotations expose the failing gate without requiring
        # authenticated log access. Preserve the traceback and failing exit.
        message = str(error).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error title=Independent PDF audit::{type(error).__name__}: {message}", flush=True)
        raise
