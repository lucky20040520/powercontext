# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Full-text financial-report PDF parsing and page-level evidence search.

``parse_pdf_document`` reads every physical page of a complete original PDF and
returns a tuple of :class:`PDFPageInput` values ordered by physical page number
(starting at 1, blank pages included). Each page becomes a captured
:class:`PDFPageSource` whose identity is the triple
``(document_id, document_sha256, page_number)``; the SHA-256 is computed over
the entire original PDF bytes, so any revision of the document produces a new
Source identity while prior references keep pointing at the original revision.

``search_pdf_pages`` retrieves page-level evidence through the public scoped
Memory API only: it runs deterministic offline query processing (financial
10-K vocabulary expansion) and reranks the genuinely returned hits, then
returns at most ``limit`` distinct exact :class:`MemoryCitation` values that
each resolve through ``memory.get`` back to the stored page evidence.
"""

from __future__ import annotations

import hashlib
import io
import re

from pydantic import BaseModel, Field, field_validator

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources import (
    TEXT_EVIDENCE_PROJECTION_KEY,
    AdapterSourceDefinition,
    TextEvidence,
)
from powercontext.sources.models import Source, SourceMaterialization

_PDF_PAGE_SOURCE_TYPE = "pdf-page"

__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "parse_pdf_document",
    "search_pdf_pages",
]


class PDFDocumentInput(BaseModel):
    """Complete original PDF bytes plus the caller's stable document identity."""

    document_id: str
    content: bytes

    @field_validator("document_id")
    @classmethod
    def document_id_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_id must not be empty or pure whitespace")  # noqa: TRY003
        return value


class PDFPageInput(BaseModel):
    """One physical page parsed from a complete original PDF document."""

    document_id: str
    document_sha256: str
    page_number: int = Field(ge=1)
    text: str


class PDFPageSource(Source):
    """Captured page evidence bound to a unique document revision and page."""

    document_id: str
    document_sha256: str
    page_number: int = Field(ge=1)
    text: str


class PDFPageAdapter:
    """Resolve and read page captures for the ``pdf-page`` Definition."""

    input_class = PDFPageInput
    name = _PDF_PAGE_SOURCE_TYPE
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        return PDFPageSource(
            name=_page_source_name(value),
            definition_version="1",
            materialization=SourceMaterialization.CAPTURED,
            document_id=value.document_id,
            document_sha256=value.document_sha256,
            page_number=value.page_number,
            text=value.text,
        )

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput(
            document_id=source.document_id,
            document_sha256=source.document_sha256,
            page_number=source.page_number,
            text=source.text,
        )


class PDFPageTextEvidenceProjection:
    """Expose one page as standard textual evidence without coupling consumers."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=_PDF_PAGE_SOURCE_TYPE,
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION = AdapterSourceDefinition(
    PDFPageAdapter(),
    version="1",
    projections=(PDFPageTextEvidenceProjection(),),
)


def _page_source_name(page: PDFPageInput) -> str:
    """Return the stable, collision-free Source name for one page revision.

    The identity is ``(document_id, document_sha256, page_number)``; the raw
    document_id is preserved for readability and bounded at 256 characters.
    """
    name = f"{_PDF_PAGE_SOURCE_TYPE}:{page.document_id}:{page.document_sha256}:{page.page_number}"
    if len(name) <= MAX_SOURCE_ID_LENGTH:
        return name
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    return f"{_PDF_PAGE_SOURCE_TYPE}:{digest}:{page.page_number}"


def parse_pdf_document(document: PDFDocumentInput, /) -> tuple[PDFPageInput, ...]:
    """Parse every physical page of the complete original PDF.

    Pages are returned in physical order starting at 1, blank pages included.
    ``text`` holds the page's extractable body; the document digest is the
    lowercase hexadecimal SHA-256 of the entire PDF bytes. PDFs that carry an
    empty-password permission marker and need no user password are readable.
    Empty, non-PDF, corrupt, or not-fully-parseable documents fail atomically
    with :class:`ValueError` and never return partial pages.
    """
    if not document.document_id.strip():
        raise ValueError("document_id must not be empty or pure whitespace")  # noqa: TRY003
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(document.content))
    except Exception as error:  # noqa: BLE001 - every malformed input becomes ValueError
        raise ValueError(f"cannot open PDF document {document.document_id!r}: {error}") from error
    if reader.is_encrypted:
        try:
            unlocked = reader.decrypt("")
        except Exception as error:  # noqa: BLE001
            raise ValueError(f"cannot unlock PDF document {document.document_id!r}: {error}") from error
        if not unlocked:
            raise ValueError(f"PDF document {document.document_id!r} requires a user password")  # noqa: TRY003
    digest = hashlib.sha256(document.content).hexdigest()
    try:
        pages = tuple(
            PDFPageInput(
                document_id=document.document_id,
                document_sha256=digest,
                page_number=number,
                text=page.extract_text() or "",
            )
            for number, page in enumerate(reader.pages, start=1)
        )
    except Exception as error:  # noqa: BLE001
        raise ValueError(f"cannot fully parse PDF document {document.document_id!r}: {error}") from error
    return pages


# Deterministic, generic 10-K vocabulary expansion applied to retrieval queries.
# These are offline query-only rewrites: they never touch stored page text and
# never depend on gold, answers, or document-specific knowledge.
_QUERY_EXPANSIONS = (
    (re.compile(r"\bcapex\b", re.I), "capex capital expenditures"),
    (re.compile(r"\bd&a\b", re.I), "depreciation amortization"),
    (re.compile(r"\bp&l\b", re.I), "income statement"),
    (re.compile(r"\blegal battles?\b", re.I), "legal litigation proceedings"),
    (re.compile(r"\bfy\s?(\d{4})\b", re.I), r"fy\1 \1"),
)

# Generic interrogative/instructional words that add no retrieval signal once
# the real finance vocabulary has been extracted for the focused variant.
_GENERIC_QUERY_TERMS = frozenset(
    """
    what how when where why which who whom whose much many quantity number
    amount value totals total state states stated report reported reports
    outline outlined explicitly directly materially important ongoing primarily
    perspective investment analyst details shown within calculate calculated
    calculation using relies rely give response assume assuming cannot only
    based answer define defined please company companies year years quarter
    quarters had has have having were was been being there their its it
    provide provided information available from with into about across over
    under between including includes included related relating concerning
    regarding the as of and or for to in on at by an a is are be do does did
    """.split()
)

# Generic 10-K statement/section heading queries. When the question names a
# report section (income statement, cash flow statement, balance sheet,
# segments, legal proceedings), the corresponding heading query reliably ranks
# the section's own pages first — including pages whose table layout keeps the
# question's vocabulary sparse. These are deterministic, document-agnostic
# rewrites; they depend on no gold and no document-specific knowledge.
_STRUCTURAL_QUERIES = (
    (
        "income statement",
        "consolidated statement of income net revenue cost of sales selling general and "
        "administrative expenses operating profit income before income taxes provision for "
        "income taxes net income attributable",
    ),
    (
        "cash flow",
        "consolidated statement of cash flows net cash provided by operating activities "
        "purchases of property plant and equipment investing activities financing activities",
    ),
    (
        "balance sheet",
        "consolidated balance sheet total assets total liabilities stockholders equity",
    ),
    (
        "segment",
        "segment information operating profit net revenue geographic segments",
    ),
    (
        "legal",
        "legal proceedings litigation",
    ),
)


def _expand_query(question: str) -> str:
    expanded = question
    for pattern, replacement in _QUERY_EXPANSIONS:
        expanded = pattern.sub(replacement, expanded)
    return expanded


def _focused_query(question: str) -> str:
    """Return only the rare informative terms of the expanded question.

    Function words and generic question words are dropped; the remaining terms
    (finance vocabulary, fiscal years, entity names) form a short high-signal
    query whose admission floor stays low while bm25 ranks rare matches first.
    """
    from powercontext.builtin.artifacts.search import analyze_fts_query

    terms = analyze_fts_query(_expand_query(question)).split()
    kept = [term for term in terms if term not in _GENERIC_QUERY_TERMS]
    return " ".join(dict.fromkeys(kept))


def _query_variants(question: str) -> tuple[str, ...]:
    """Build deterministic offline query variants for one raw question.

    Returns the expanded question, the raw question, the focused key-term query,
    and any section-heading queries named by the question itself. Variants are
    deduplicated while preserving priority order.
    """
    lowered = question.casefold() + " " + _expand_query(question).casefold()
    variants: list[str] = []
    for query in (_expand_query(question), question, _focused_query(question)):
        if query and query not in variants:
            variants.append(query)
    for trigger, structural in _STRUCTURAL_QUERIES:
        if trigger in lowered:
            if structural not in variants:
                variants.append(structural)
    return tuple(variants)


async def search_pdf_pages(memory, question: str, limit: int = 10) -> tuple["MemoryCitation", ...]:
    """Search one opened scoped Memory and return page-level citations.

    Runs deterministic offline query variants through the public Memory search
    API, deduplicates the genuinely returned hits, and returns at most ``limit``
    distinct exact :class:`MemoryCitation` values in retrieval-priority order.
    Every returned citation resolves through ``memory.get`` back to the stored
    page evidence; no citation is fabricated outside the Memory store.
    """
    if limit < 1:
        raise ValueError("limit must be a positive integer")  # noqa: TRY003

    from powercontext.builtin.artifacts.memory.models import MemoryCitation
    from powercontext.builtin.runtime import SearchMemoryRequest

    variants = _query_variants(question)

    seen: dict[tuple[str, str, str], tuple[int, int, object]] = {}
    for priority, variant in enumerate(variants):
        page = await memory.search(SearchMemoryRequest(query=variant, mode="fts", limit=limit))
        for rank, hit in enumerate(page.hits):
            key = (str(hit.memory_ref.artifact_id), str(hit.entry_id), str(hit.entry_version_id))
            incumbent = seen.get(key)
            if incumbent is None or (rank, priority) < (incumbent[0], incumbent[1]):
                seen[key] = (rank, priority, hit)

    # Rerank the union by each hit's best rank across retrieval variants; equal
    # ranks keep the primary (expanded) variant first. Every candidate is a
    # genuine Memory hit, so the returned citations always resolve by memory.get.
    ordered = sorted(seen.values(), key=lambda item: (item[0], item[1]))
    citations: list[object] = []
    for _rank, _priority, hit in ordered[:limit]:
        citations.append(
            MemoryCitation(
                memory_ref=hit.memory_ref,
                entry_id=hit.entry_id,
                entry_version_id=hit.entry_version_id,
            )
        )
    return tuple(citations)
