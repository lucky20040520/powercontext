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

"""Complete physical PDF pages and offline retrieval of persisted evidence."""

from __future__ import annotations

import hashlib
import io
import json
import math
import re
import zlib
from collections import Counter
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

if TYPE_CHECKING:
    from pypdf import PageObject
    from pypdf.generic import StreamObject

    from powercontext.artifacts import MemoryCitation
    from powercontext.builtin.runtime import MemoryEntryRecord, ScopedMemoryApplication


class PDFDocumentInput(BaseModel):
    """Original PDF bytes; page numbers always refer to this exact revision."""

    document_id: str
    content: bytes

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        return _require_document_id(value)


class PDFPageInput(BaseModel):
    """Complete extracted text of one 1-based physical page, including blanks."""

    document_id: str
    document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_number: int = Field(ge=1, strict=True)
    text: str

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        return _require_document_id(value)


def _require_document_id(value: str) -> str:
    if not value.strip():
        raise ValueError("PDF document identity must contain non-whitespace text")  # noqa: TRY003
    return value


def _page_identity(value: PDFPageInput) -> str:
    identity = json.dumps(
        [value.document_id, value.document_sha256, value.page_number], ensure_ascii=False, separators=(",", ":")
    )
    return f"pdf:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"


class PDFPageSource(Source, PDFPageInput):
    """Captured page with a bounded revision-specific identity."""

    definition_version: Literal["1"] = "1"
    materialization: Literal[SourceMaterialization.CAPTURED] = SourceMaterialization.CAPTURED

    @model_validator(mode="after")
    def validate_identity(self) -> PDFPageSource:
        if self.name != _page_identity(self):
            raise ValueError("PDF Source name must match its document, digest and physical page")  # noqa: TRY003
        return self


def parse_pdf_document(value: PDFDocumentInput) -> tuple[PDFPageInput, ...]:
    """Extract every page atomically, without repairing incomplete PDFs or doing OCR.

    Install ``powercontext[pdf]`` to use this parser. Imports stay local so other
    Source definitions remain usable without the optional PDF dependency.
    """

    from pypdf import PdfReader
    from pypdf.generic import DictionaryObject

    digest = hashlib.sha256(value.content).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(value.content), strict=True)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("PDF requires a non-empty password")  # noqa: TRY003, TRY301
        # Materialize before returning: an error on a later page cannot expose
        # an apparently successful partial document to ingestion.
        pages = tuple(
            PDFPageInput(
                document_id=value.document_id,
                document_sha256=digest,
                page_number=index,
                text=_extract_page_text(page),
            )
            for index, page in enumerate(reader.pages, 1)
        )
        root = reader.root_object["/Pages"].get_object()
        if not isinstance(root, DictionaryObject) or len(pages) != root.get("/Count"):
            raise ValueError("PDF page tree does not contain its declared pages")  # noqa: TRY003, TRY301
    except Exception as error:
        # pypdf also surfaces malformed objects as built-in exceptions. At this
        # input boundary all failures mean that the complete document is invalid.
        raise ValueError("Unable to completely parse PDF document") from error  # noqa: TRY003
    return pages


def _extract_page_text(page: PageObject) -> str:
    from pypdf.generic import ArrayObject, NullObject, StreamObject

    # pypdf's extractor silently treats some invalid /Contents values as blank.
    # An absent/null stream is blank; a present stream must actually be readable.
    contents = page.get("/Contents")
    if contents is None:
        return ""
    contents = contents.get_object()
    if isinstance(contents, NullObject):
        return ""
    streams = contents if isinstance(contents, ArrayObject) else (contents,)
    for stream in streams:
        resolved = stream.get_object()
        if not isinstance(resolved, StreamObject):
            raise TypeError("PDF page contents must be streams")  # noqa: TRY003
        _validate_compression(resolved)
    from powercontext.sources._pdf_text import select_page_text

    return select_page_text(page)


def _validate_compression(stream: StreamObject) -> None:
    """Reject incomplete Flate data before pypdf's best-effort decoder repairs it."""

    from pypdf.filters import decode_stream_data
    from pypdf.generic import ArrayObject, DecodedStreamObject, NameObject

    filters = stream.get("/Filter", ())
    if isinstance(filters, NameObject):
        filters = (filters,)
    if not any(name in ("/FlateDecode", "/Fl") for name in filters):
        return
    # Use the public serialization API to access the encoded payload. Reading
    # get_data() here would already discard checksum/EOF failures in pypdf.
    buffer = io.BytesIO()
    stream.write_to_stream(buffer)
    encoded = buffer.getvalue().split(b"\nstream\n", 1)[1].rsplit(b"\nendstream", 1)[0]
    parameters = stream.get("/DecodeParms")
    for index, name in enumerate(filters):
        if name in ("/FlateDecode", "/Fl"):
            prefix = DecodedStreamObject()
            prefix.set_data(encoded)
            prefix[NameObject("/Filter")] = ArrayObject(list(filters[:index]))
            if parameters is not None:
                prefix[NameObject("/DecodeParms")] = (
                    ArrayObject(parameters[:index]) if isinstance(parameters, ArrayObject) else parameters
                )
            zlib.decompress(decode_stream_data(prefix))


class _PDFPageAdapter:
    input_class = PDFPageInput
    name = "pdf-page"
    source_class = PDFPageSource

    async def resolve(self, value: PDFPageInput, /) -> PDFPageSource:
        return PDFPageSource(name=_page_identity(value), **value.model_dump())

    async def read(self, source: PDFPageSource, /) -> PDFPageInput:
        return PDFPageInput.model_validate(source.model_dump())


class _PDFPageTextEvidence:
    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PDFPageSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PDFPageSource, /) -> TextEvidence:
        return TextEvidence(
            source_type="pdf-page",
            source_id=source.name,
            content=f"{source.document_id}\n{source.text}",
            metadata={
                "document_id": source.document_id,
                "document_sha256": source.document_sha256,
                "page_number": source.page_number,
            },
        )


PDF_PAGE_SOURCE_DEFINITION: SourceDefinition[PDFPageInput, PDFPageSource, PDFPageInput] = AdapterSourceDefinition(
    _PDFPageAdapter(), projections=(_PDFPageTextEvidence(),)
)

_WORDS = re.compile(r"[a-z]+|\d+")
_IDENTITY_WORDS = re.compile(r"[a-z0-9]+")
_REPORT_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
_REPORT_SUFFIXES = frozenset({"10k", "10q", "8k", "annual", "report", "form", "dated", "inc", "corp", "company", "plc"})


def _tokens(text: str) -> list[str]:
    words = _WORDS.findall(text.lower())
    # Light inflection normalization keeps numbers and accounting abbreviations.
    return [
        word[:-3] + "y" if word.endswith("ies") else word[:-1] if len(word) > 3 and word.endswith("s") else word
        for word in words
    ]


_STOPWORDS = frozenset(
    _tokens(
        "a an the and or of to in on at for from by with as is are was were be been being "
        "it its s do does did has have had that this these those which what how why when where "
        "who whom whose any all can could would should will may must not no only also than then "
        "if so but into through between during per using use used based about out over under "
        "give answer respond response question calculate define assuming perspective investment "
        "analyst details shown relying directly explicitly outlined primarily reported important "
        "state usd million millions billion billions fy fiscal year years period periods "
        "increase increased decrease decreased change changed compare comparison"
    )
)
# General accounting vocabulary, independent of companies, reports and questions.
_CONCEPTS = (
    (
        "geography",
        "geographic",
        "geographical",
        "region",
        "market",
        "country",
        "segment",
        "international",
        "business",
        "division",
    ),
    ("legal", "lawsuit", "litigation", "proceeding", "contingency", "battle"),
    ("restructuring", "reorganization", "realignment", "severance"),
    ("revenue", "sale", "turnover"),
    ("income", "earning", "profit"),
    ("capex", "capital spending", "capital expenditure", "property plant equipment"),
    ("cash flow", "cash flows", "cash provided", "cash used"),
    ("income statement", "p l statement", "statement of income", "statement of operation", "statement of earning"),
    ("balance sheet", "financial position"),
    ("d a", "depreciation amortization"),
    ("inventory", "stock", "inventories"),
    ("debt", "borrowing", "indebtedness"),
)
# Metric names expand toward their supporting statement lines. The reverse
# direction would turn an ordinary revenue question into many unrelated ratios.
_METRICS = {
    "ebitda": ("operating income", "depreciation amortization"),
    "working capital": ("current asset", "current liability"),
    "quick ratio": ("cash equivalent", "receivable", "current liability"),
    "current ratio": ("current asset", "current liability"),
    "return on equity": ("net income", "shareholder equity", "stockholder equity"),
    "return on asset": ("net income", "total asset"),
    "asset turnover": ("revenue", "total asset"),
    "gross margin": ("gross profit", "revenue", "cost of sale"),
    "operating margin": ("operating income", "revenue"),
    "free cash flow": ("operating cash flow", "capital expenditure"),
}
_STATEMENT_PREFIX = r"^\s*(?:(?:consolidated|combined|condensed|unaudited)\s+)*"
_STATEMENT_SUFFIX = r"(?:\s*\([^\n)]*\))*\s*$"
_STATEMENT_HEADINGS = (
    (
        frozenset({"income", "profit", "revenue", "sale", "earning", "ebitda", "margin"}),
        re.compile(
            _STATEMENT_PREFIX
            + r"(?:statements? of (?:income|operations?|earnings?)|income statements?)"
            + _STATEMENT_SUFFIX,
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        frozenset({"cash", "flow", "capex", "depreciation", "amortization", "ebitda"}),
        re.compile(
            _STATEMENT_PREFIX + r"statements? of cash flows?" + _STATEMENT_SUFFIX,
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        frozenset({"asset", "liability", "equity", "inventory", "receivable", "debt", "capital"}),
        re.compile(
            _STATEMENT_PREFIX + r"(?:balance sheets?|statements? of financial position)" + _STATEMENT_SUFFIX,
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
)
_BUSINESS_HEADING = re.compile(
    r"^\s*(?:item\s+\d+[a-z]?\.?\s*)?(?:our\s+(?:company|business|divisions?)|business|"
    r"(?:geographic|reportable|operating)\s+segments?)\s*[.:]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_GEOGRAPHY_TERMS = frozenset({
    "geography",
    "geographic",
    "geographical",
    "region",
    "country",
    "international",
    "market",
    "division",
    "segment",
})
_GEOGRAPHIC_CONTEXT = (
    "north america",
    "latin america",
    "south america",
    "europe",
    "asia",
    "africa",
    "middle east",
    "pacific",
    "emea",
    "apac",
)


def _query_terms(question: str) -> tuple[dict[str, float], tuple[tuple[str, ...], ...]]:
    raw = _tokens(question)
    terms = dict.fromkeys((word for word in raw if word not in _STOPWORDS), 1.0)
    normalized = " " + " ".join(raw) + " "
    expansions: list[tuple[str, ...]] = [
        concept
        for concept in _CONCEPTS
        if any(" " + " ".join(_tokens(phrase)) + " " in normalized for phrase in concept)
    ]
    expansions.extend(
        alternatives for metric, alternatives in _METRICS.items() if " " + " ".join(_tokens(metric)) + " " in normalized
    )
    if _GEOGRAPHY_TERMS & terms.keys():
        expansions.append(_GEOGRAPHIC_CONTEXT)
    phrases: list[tuple[str, ...]] = []
    for concept in expansions:
        for phrase in concept:
            alternative = tuple(_tokens(phrase))
            if len(alternative) > 1:
                phrases.append(alternative)
            for token in alternative:
                if token not in _STOPWORDS:
                    terms.setdefault(token, 0.35)
    return terms, tuple(phrases)


async def search_pdf_pages(
    memory: ScopedMemoryApplication, question: str, limit: int = 10
) -> tuple[MemoryCitation, ...]:
    """Rank active captured pages from one scoped Memory snapshot, entirely offline.

    The public ``list`` API supplies both full page bodies and exact citations.
    BM25 uses that corpus rather than a natural-language FTS admission cutoff,
    so synonyms and questions spanning several financial statements remain
    eligible. No source files, external indexes or process-local caches are used.
    Work is linear in the scoped corpus text; intended for report collections
    such as the challenge's 1,151 pages, not unbounded knowledge bases.
    """

    if limit <= 0 or not question.strip():
        return ()
    terms, phrases = _query_terms(question)
    if not terms:
        return ()
    snapshot = await memory.list()
    records: list[MemoryEntryRecord] = []
    seen: set[str] = set()
    for record in snapshot.entries:
        references = record.entry.sources
        # A citation must identify exactly one page; ignore unrelated memories
        # and summaries combining multiple sources.
        if len(references) == 1 and references[0].source_type == "pdf-page":
            identity = references[0].source_id
            if identity not in seen:
                records.append(record)
                seen.add(identity)
    if not records:
        return ()
    return _rank_pages(records, terms, phrases, limit, _report_weights(records, question))


def _report_weights(records: list[MemoryEntryRecord], question: str) -> dict[str, float]:
    """Treat company and year matches as hints without excluding other reports."""

    question_words = _IDENTITY_WORDS.findall(question.lower())
    # Joining neighboring words accommodates report IDs such as COCA_COLA and
    # questions spelling the same name as CocaCola, without matching 3M to X3M.
    mentioned_names = {
        "".join(question_words[start:end])
        for start in range(len(question_words))
        for end in range(start + 1, min(start + 6, len(question_words)) + 1)
    }
    documents = {record.entry.text.partition("\n")[0] for record in records}
    selected = set()
    for document in documents:
        # Reporting periods and suffixes are not part of the company name.
        # Keep alphanumeric company tokens such as 3M intact.
        company_part = _REPORT_YEAR.split(document, maxsplit=1)[0]
        company_words = tuple(
            word
            for word in _IDENTITY_WORDS.findall(company_part.lower())
            if word not in _REPORT_SUFFIXES and not word.isdigit()
        )
        company = "".join(company_words)
        if len(company) > 1 and company not in _STOPWORDS and company in mentioned_names:
            selected.add(document)
    years = set(_REPORT_YEAR.findall(question))
    weights = {
        document: (3.0 if document in selected else 1.0)
        * (1.25 if years.intersection(_REPORT_YEAR.findall(document)) else 1.0)
        for document in documents
    }
    return weights


def _rank_pages(
    records: list[MemoryEntryRecord],
    terms: dict[str, float],
    phrases: tuple[tuple[str, ...], ...],
    limit: int,
    report_weights: dict[str, float],
) -> tuple[MemoryCitation, ...]:
    """Score one exact corpus snapshot with length-normalized lexical evidence."""

    bodies = [record.entry.text.partition("\n")[2] for record in records]
    token_lists = [_tokens(body) for body in bodies]
    counts = [Counter(tokens) for tokens in token_lists]
    frequency = Counter(token for count in counts for token in count)
    average_length = max(1.0, sum(map(len, token_lists)) / len(records))
    idf = {term: math.log1p((len(records) - frequency[term] + 0.5) / (frequency[term] + 0.5)) for term in terms}
    ranked: list[tuple[float, int]] = []
    for index, (record, tokens, count) in enumerate(zip(records, token_lists, counts, strict=True)):
        normalized = " " + " ".join(tokens) + " "
        normalization = 1.2 * (0.55 + 0.45 * len(tokens) / average_length)
        score = sum(
            weight * idf[term] * count[term] * 2.2 / (count[term] + normalization)
            for term, weight in terms.items()
            if count[term]
        )
        # Phrase matches favor actual statement bodies over incidental mentions.
        score += sum(
            sum(idf.get(term, 0.0) for term in phrase) * 0.6
            for phrase in phrases
            if " " + " ".join(phrase) + " " in normalized
        )
        # A heading is supporting context, not evidence on its own. Check the
        # remaining body and bound the combined bonus by twice the lexical score.
        body = bodies[index]
        content = body[:1000]
        for _, heading in _STATEMENT_HEADINGS:
            content = heading.sub(" ", content)
        content = _BUSINESS_HEADING.sub(" ", content + body[1000:])
        content_tokens = _tokens(content)
        content_terms = set(content_tokens)
        has_amount = any(token.isdigit() and not _REPORT_YEAR.fullmatch(token) for token in content_terms)
        financial_evidence = any(vocabulary & terms.keys() & content_terms for vocabulary, _ in _STATEMENT_HEADINGS)
        if has_amount and financial_evidence:
            score *= 1.25
        structural_bonus = sum(
            3.0 * sum(terms[term] * idf[term] for term in vocabulary & terms.keys())
            for vocabulary, heading in _STATEMENT_HEADINGS
            if heading.search(body[:1000]) and vocabulary & terms.keys() & content_terms and has_amount
        )
        geography = {term for term in _GEOGRAPHY_TERMS if terms.get(term) == 1.0}
        geographic_content = " " + " ".join(content_tokens) + " "
        has_region = any(" " + " ".join(_tokens(region)) + " " in geographic_content for region in _GEOGRAPHIC_CONTEXT)
        if geography and _BUSINESS_HEADING.search(body) and has_region:
            structural_bonus += 3.0 * sum(idf[term] for term in geography)
        score += min(2.0 * score, structural_bonus)
        score *= report_weights[record.entry.text.partition("\n")[0]]
        if score > 0:
            ranked.append((score, index))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return tuple(records[index].citation for _, index in ranked[:limit])


__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "parse_pdf_document",
    "search_pdf_pages",
]
