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
import unicodedata
import zlib
from collections import Counter
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from powercontext.sources.definitions import AdapterSourceDefinition, SourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

if TYPE_CHECKING:
    from pypdf import PageObject
    from pypdf.generic import StreamObject

    from powercontext.artifacts import MemoryCitation
    from powercontext.builtin.runtime import MemoryEntryRecord, ScopedMemoryApplication


_LATIN_LIGATURES = str.maketrans({
    chr(code): unicodedata.normalize("NFKC", chr(code)) for code in range(0xFB00, 0xFB07)
})


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
    if contents is not None:
        contents = contents.get_object()
        if not isinstance(contents, NullObject):
            streams = contents if isinstance(contents, ArrayObject) else (contents,)
            for stream in streams:
                resolved = stream.get_object()
                if not isinstance(resolved, StreamObject):
                    raise TypeError("PDF page contents must be streams")  # noqa: TRY003
                _validate_compression(resolved)
    _validate_form_streams(page, set())
    canvas = _text_bearing_page(page)
    text = _extract_complete_text(canvas, prefer_layout=canvas is not page)
    return unicodedata.normalize("NFC", text.translate(_LATIN_LIGATURES))


def _text_bearing_page(page: PageObject) -> PageObject:
    """Unwrap a text-only Form canvas without losing its own font resources.

    Layout extraction otherwise misses fonts on pages that only invoke a Form.
    Only a single painted Form with no other content is eligible; images, extra
    invocations and page text retain their original extraction path.
    """
    from pypdf import PageObject
    from pypdf.generic import DictionaryObject, NameObject, StreamObject

    seen: set[int] = set()
    while True:
        contents = page.get_contents()
        if contents is None or any(op not in (b"q", b"Q", b"cm", b"Do", b"gs") for _, op in contents.operations):
            return page
        calls = [args for args, op in contents.operations if op == b"Do"]
        if len(calls) != 1 or len(calls[0]) != 1:
            return page
        resources = page.get("/Resources")
        if resources is None:
            return page
        resources = resources.get_object()
        objects = resources.get("/XObject")
        if objects is None:
            return page
        form = objects.get_object()[calls[0][0]].get_object()
        if not isinstance(form, StreamObject) or form.get("/Subtype") != "/Form" or id(form) in seen:
            return page
        seen.add(id(form))
        fonts = form.get("/Resources", resources).get_object()
        if not isinstance(fonts, DictionaryObject):
            return page
        canvas = PageObject(pdf=page.pdf)
        canvas.update(page)
        canvas.pop("/Parent", None)
        canvas[NameObject("/Contents")] = form
        canvas[NameObject("/Resources")] = fonts
        page = canvas


def _coalesce_kerning(items: list[Any]) -> list[Any]:
    output: list[Any] = []
    index = 0
    while index < len(items):
        current = items[index]
        if isinstance(current, (str, bytes)):
            # TJ advances use thousandths of a text-space unit. Keep word-sized
            # advances and every original string byte; join only micro-kerning.
            while (
                index + 2 < len(items)
                and isinstance(items[index + 1], (int, float))
                and abs(items[index + 1]) <= 40
                and type(items[index + 2]) is type(current)
            ):
                current = type(current)(current + items[index + 2])
                index += 2
        output.append(current)
        index += 1
    return output


def _font_aliases(page: PageObject) -> dict[str, str]:
    """Recognize exact duplicate font dictionaries without guessing encodings."""

    from pypdf.generic import DictionaryObject

    resources = page.get("/Resources")
    if resources is None:
        return {}
    resources = resources.get_object()
    if not isinstance(resources, DictionaryObject):
        return {}
    fonts = resources.get("/Font")
    if fonts is None:
        return {}
    fonts = fonts.get_object()
    if not isinstance(fonts, DictionaryObject):
        return {}
    aliases: dict[str, str] = {}
    unique: list[tuple[str, object]] = []
    for name, reference in fonts.items():
        value = reference.get_object()
        for canonical, known in unique:
            if value == known:
                aliases[name] = canonical
                break
        else:
            aliases[name] = name
            unique.append((name, value))
    return aliases


class _TextRunNormalizer:
    """Normalize horizontal runs and exact, explicitly positioned overprinting."""

    def __init__(self, page: PageObject) -> None:
        self.aliases = _font_aliases(page)
        self.rewritten = False
        self.cross_run_kerning = False
        self.joined_glyphs = 0
        self.text_characters = 0
        self.positioned = True
        self.font: tuple[Any, ...] = ()
        self.fonts: list[tuple[Any, ...]] = []
        self.form_depth = 0
        self.painted: set[tuple[Any, ...]] = set()

    def before(self, operator: bytes, operands: list[Any], cm: list[float], tm: list[float]) -> None:
        from pypdf.generic import ArrayObject

        if operator == b"Do":
            self.form_depth += 1
        if self.form_depth == 0:
            self._track_position(operator, operands)
            self._remove_overprint(operator, operands, cm, tm)
        if operator == b"Tj" and operands:
            self.text_characters += len(operands[0])
        if operator == b"TJ" and operands:
            original = operands[0]
            self.text_characters += sum(len(item) for item in original if isinstance(item, (str, bytes)))
            if (
                len(original) >= 2
                and isinstance(original[-1], (int, float))
                and original[-1] > 40
                and isinstance(original[-2], (str, bytes))
                and original[-2]
                and not original[-2][-1:].isspace()
            ):
                self.cross_run_kerning = True
            items = _coalesce_kerning(original)
            self.joined_glyphs += (len(original) - len(items)) // 2
            self.rewritten |= len(items) != len(operands[0])
            operands[0] = ArrayObject(items)

    def after(self, operator: bytes, _operands: list[Any], *_matrices: object) -> None:
        if operator == b"Do":
            self.form_depth -= 1

    def _track_position(self, operator: bytes, operands: list[Any]) -> None:
        if operator == b"q":
            self.fonts.append(self.font)
        elif operator == b"Q" and self.fonts:
            self.font = self.fonts.pop()
        elif operator == b"Tf":
            name = str(operands[0])
            self.font = (self.aliases.get(name, name), *operands[1:])
        elif operator in (b"BT", b"Tm", b"Td", b"TD", b"T*"):
            self.positioned = True

    def _remove_overprint(self, operator: bytes, operands: list[Any], cm: list[float], tm: list[float]) -> None:
        from pypdf.generic import ArrayObject

        if operator not in (b"Tj", b"TJ") or not operands:
            return
        glyphs = operands[0] if operator == b"Tj" else (operands[0][0] if len(operands[0]) == 1 else None)
        # Repeated implicit text advances are real repetitions. Require an
        # explicit placement and an exact single-glyph match at that location.
        if self.positioned and isinstance(glyphs, (str, bytes)) and len(glyphs) == 1:
            key = (glyphs, self.font, tuple(cm), tuple(tm))
            if key in self.painted:
                operands[0] = type(glyphs)() if operator == b"Tj" else ArrayObject()
                self.rewritten = True
            else:
                self.painted.add(key)
        self.positioned = False


def _extract_complete_text(page: PageObject, *, prefer_layout: bool = False) -> str:
    """Detect TJ word-boundary failures without a vocabulary or document table.

    Use layout only for affected pages, and only when it preserves every
    character after exact overprinting is removed. Ordinary pages retain the
    original extraction and table tokens. No content crosses a page boundary.
    """

    normalizer = _TextRunNormalizer(page)
    coalesced = page.extract_text(visitor_operand_before=normalizer.before, visitor_operand_after=normalizer.after)
    # Glyph-wise TJ encoding can fragment words across independently placed
    # runs even when coalescing leaves plain extraction unchanged. Its density
    # distinguishes that producer pattern from ordinary word-level kerning.
    prefer_layout |= normalizer.joined_glyphs * 2 >= max(1, normalizer.text_characters)
    if not normalizer.rewritten and not normalizer.cross_run_kerning and not prefer_layout:
        return coalesced
    if not prefer_layout and not normalizer.cross_run_kerning:
        plain = page.extract_text()
        if Counter(_WORDS.findall(plain.lower())) == Counter(_WORDS.findall(coalesced.lower())):
            return plain
    layout = page.extract_text(
        extraction_mode="layout", layout_mode_space_vertically=False, layout_mode_strip_rotated=False
    )
    if Counter(character for character in layout if not character.isspace()) != Counter(
        character for character in coalesced if not character.isspace()
    ):
        return _repair_mixed_form_text(page, coalesced)
    # Wide tables and small fonts must not inflate Memory with layout padding.
    return re.sub(r"[ \t]+", " ", layout)


def _painted_forms(page: PageObject) -> tuple[StreamObject, ...]:
    """Return only actual direct Form invocations, retaining their multiplicity."""
    from pypdf.generic import StreamObject

    contents = page.get_contents()
    resources = page.get("/Resources")
    if contents is None or resources is None:
        return ()
    objects = resources.get_object().get("/XObject")
    if objects is None:
        return ()
    forms: list[StreamObject] = []
    for args, operator in contents.operations:
        if operator == b"Do" and len(args) == 1:
            form = objects.get_object()[args[0]].get_object()
            if isinstance(form, StreamObject) and form.get("/Subtype") == "/Form":
                forms.append(form)
    return tuple(forms)


def _repair_mixed_form_text(page: PageObject, text: str) -> str:
    """Repair Form-local word spacing when whole-page layout lacks its fonts.

    Preserve all surrounding page text and every painted occurrence. A repair is
    applied only to an exact extracted Form span and only if its non-whitespace
    characters are unchanged; unrelated text and page boundaries cannot move.
    """
    from pypdf import PageObject
    from pypdf.generic import ArrayObject, DictionaryObject, NameObject

    forms = _painted_forms(page)
    if not forms:
        return text
    resources = page["/Resources"]
    occurrences = Counter(map(id, forms))
    seen: set[int] = set()

    def coalesce(operator: bytes, operands: list[Any], *_matrices: object) -> None:
        if operator == b"TJ" and operands:
            operands[0] = ArrayObject(_coalesce_kerning(operands[0]))

    for form in forms:
        if id(form) in seen:
            continue
        seen.add(id(form))
        local_resources = form.get("/Resources", resources).get_object()
        if not isinstance(local_resources, DictionaryObject):
            continue
        canvas = PageObject(pdf=page.pdf)
        canvas.update(page)
        canvas.pop("/Parent", None)
        canvas[NameObject("/Contents")] = form
        canvas[NameObject("/Resources")] = local_resources
        original = canvas.extract_text(visitor_operand_before=coalesce)
        # An identical span elsewhere may use different fonts or spacing.
        # Leave ambiguous matches alone rather than modifying unrelated text.
        if not original or text.count(original) != occurrences[id(form)]:
            continue
        repaired = _extract_complete_text(_text_bearing_page(canvas), prefer_layout=True)
        if Counter(char for char in original if not char.isspace()) == Counter(
            char for char in repaired if not char.isspace()
        ):
            text = text.replace(original, repaired)
    return text


def _validate_form_streams(container: object, seen: set[int]) -> None:
    """Validate nested text-bearing forms that the extractor may silently skip."""

    from pypdf.generic import DictionaryObject, StreamObject

    if not isinstance(container, DictionaryObject) or id(container) in seen:
        return
    seen.add(id(container))
    resources = container.get("/Resources")
    if resources is None:
        return
    resources = resources.get_object()
    if not isinstance(resources, DictionaryObject):
        raise TypeError("PDF resources must be a dictionary")  # noqa: TRY003
    objects = resources.get("/XObject")
    if objects is None:
        return
    objects = objects.get_object()
    if not isinstance(objects, DictionaryObject):
        raise TypeError("PDF XObjects must be a dictionary")  # noqa: TRY003
    for reference in objects.values():
        form = reference.get_object()
        # Image payloads do not contribute extractable text and are outside OCR.
        if isinstance(form, StreamObject) and form.get("/Subtype") == "/Form":
            _validate_compression(form)
            _validate_form_streams(form, seen)


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
_EXPLICIT_REPORT_YEAR = re.compile(
    r"(?<!\d)((?:19|20)\d{2})[\s_-]*(?:annual[\s_-]+report|(?:form[\s_-]+)?10[\s_-]*[kq])\b"
    r"|\b(?:annual[\s_-]+report|(?:form[\s_-]+)?10[\s_-]*[kq])[\s_-]+"
    r"(?:for[\s_-]+)?(?:fy[\s_-]*)?((?:19|20)\d{2})(?!\d)",
    re.IGNORECASE,
)
_REPORT_SUFFIXES = frozenset({
    "10k",
    "10q",
    "8k",
    "annual",
    "report",
    "form",
    "dated",
    "inc",
    "corp",
    "company",
    "plc",
    "corporation",
    "incorporated",
    "holding",
    "holdings",
    "limited",
    "ltd",
    "llc",
    "co",
})
_INFLECTIONS = {
    "taxes": "tax",
    "losses": "loss",
    "businesses": "business",
    "analyses": "analysis",
    "amortisation": "amortization",
    "capitalisation": "capitalization",
    "taxation": "tax",
}
_LINE_WRAP = re.compile(r"([a-z]+)[-\u00ad][ \t]*\r?\n[ \t]*([a-z]+)")


def _word_form(word: str) -> str:
    if word in _INFLECTIONS:
        return _INFLECTIONS[word]
    if word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _search_text(text: str, joined_words: set[str] | None = None) -> str:
    # Normalize only the derived search view. Captured text and quality tokens
    # retain the PDF extractor's original characters and physical page boundary.
    normalized = unicodedata.normalize("NFKC", text).lower()
    # PDF prose commonly spells initialisms with periods while questions omit
    # them (U.S./US, U.K./UK). Preserve the same search token in both directions.
    normalized = re.sub(r"\b(?:[a-z]\.)+[a-z]\.?(?![a-z])", lambda match: match[0].replace(".", ""), normalized)
    if joined_words:
        normalized = _LINE_WRAP.sub(
            lambda match: match[1] + match[2] if _word_form(match[1] + match[2]) in joined_words else match[0],
            normalized,
        )
    return normalized.replace("\u00ad", "")


def _tokens(text: str, joined_words: set[str] | None = None) -> list[str]:
    return [_word_form(word) for word in _WORDS.findall(_search_text(text, joined_words))]


_STOPWORDS = frozenset(
    _tokens(
        "a an the and or of to in on at for from by with as is are was were be been being "
        "it its s do does did has have had that this these those which what how why when where "
        "who whom whose any all can could would should will may must not no only also than then "
        "if so but into through between during per using use used based about out over under "
        "give answer respond response question calculate define assuming perspective investment "
        "analyst details shown relying directly explicitly outlined primarily reported important "
        "state usd million millions billion billions fy fiscal year years period periods "
        "increase increased decrease decreased change changed compare comparison much many amount quantity "
        "according respective respectively following financial statement statements unadjusted adjusted"
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
    ("buyback", "share repurchase", "stock repurchase", "treasury stock", "shares purchased"),
    ("supplier", "accounts payable", "trade payable"),
    ("customer credit", "accounts receivable", "trade receivable"),
    ("research and development", "research development", "r d", "product development", "product engineering"),
    ("lease", "rental", "rent", "lease commitment"),
    ("acquisition", "business combination", "purchase consideration"),
    ("effective tax rate", "income tax provision", "income tax expense", "income before tax", "pretax income"),
    ("maturity", "maturities", "current portion", "current installment", "current maturities"),
    ("shareholder", "stockholder"),
    ("customer", "buyer", "client"),
    ("online", "ecommerce", "e commerce", "digital commerce"),
    ("geographic", "foreign revenue", "foreign customer", "overseas", "outside the united states", "non us"),
    ("maturity", "maturities", "fall due", "scheduled payment", "future minimum payment", "payment schedule"),
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
    "net profit margin": ("net income", "net earning", "net sale", "revenue"),
    "net income margin": ("net income", "net sale", "revenue"),
    "return on invested capital": ("operating profit", "income tax", "invested capital", "equity", "debt"),
    "return on capital employed": ("operating income", "total asset", "current liability"),
    "fixed asset turnover": ("net sale", "revenue", "property plant equipment"),
    "receivable turnover": ("net sale", "revenue", "accounts receivable"),
    "inventory turnover": ("cost of sale", "cost of revenue", "inventory"),
    "days sales outstanding": ("accounts receivable", "net sale", "revenue"),
    "days inventory outstanding": ("inventory", "cost of sale"),
    "days payable outstanding": ("accounts payable", "cost of sale"),
    "cash conversion cycle": ("accounts receivable", "inventory", "accounts payable", "cost of sale", "net sale"),
    "debt to equity": ("total debt", "borrowing", "shareholder equity", "stockholder equity"),
    "debt to asset": ("total debt", "total asset"),
    "interest coverage": ("operating income", "interest expense"),
    "dividend payout": ("dividend", "net income"),
    "earnings per share": ("basic", "diluted", "net income", "weighted average share"),
    "cash ratio": ("cash equivalent", "current liability"),
    "net debt": ("total debt", "cash equivalent"),
    "debt ratio": ("total liability", "total asset"),
    "debt to capital": ("total debt", "shareholder equity", "stockholder equity"),
    "equity multiplier": ("total asset", "shareholder equity", "stockholder equity"),
    "ebit": ("operating income", "operating profit"),
    "ebitda margin": ("operating income", "depreciation amortization", "revenue", "net sale"),
    "net debt to ebitda": ("total debt", "cash equivalent", "operating income", "depreciation amortization"),
    "free cash flow margin": ("operating cash flow", "capital expenditure", "revenue"),
    "operating cash flow ratio": ("operating cash flow", "current liability"),
    "cash flow margin": ("operating cash flow", "revenue"),
    "debt service coverage": ("operating income", "interest expense", "principal payment", "current maturity"),
}
_METRIC_ALIASES = {
    "gross profit margin": "gross margin",
    "roa": "return on asset",
    "roe": "return on equity",
    "roic": "return on invested capital",
    "roce": "return on capital employed",
    "eps": "earnings per share",
    "fcf": "free cash flow",
    "fcf margin": "free cash flow margin",
    "dso": "days sales outstanding",
    "dio": "days inventory outstanding",
    "dpo": "days payable outstanding",
    "ccc": "cash conversion cycle",
    "net leverage ratio": "net debt to ebitda",
}
_STATEMENT_PREFIX = r"^\s*(?:(?:consolidated|combined|condensed|unaudited)\s+)*"
_STATEMENT_SUFFIX = r"(?:\s*\([^\n)]*\))*\s*$"
_STATEMENT_HEADINGS = (
    (
        frozenset({"income", "profit", "revenue", "sale", "earning", "ebitda", "margin"}),
        re.compile(
            _STATEMENT_PREFIX + r"(?:statements? of (?:(?:consolidated|combined|condensed)\s+)*"
            r"(?:income|operations?|earnings?|profit(?:\s+or\s+loss)?)|income statements?)"
            r"(?:\s+and\s+(?:other\s+)?comprehensive\s+(?:income|loss))?" + _STATEMENT_SUFFIX,
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        frozenset({"cash", "flow", "capex", "depreciation", "amortization", "ebitda"}),
        re.compile(
            _STATEMENT_PREFIX
            + r"statements? of (?:(?:consolidated|combined|condensed)\s+)*cash flows?"
            + _STATEMENT_SUFFIX,
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        frozenset({"asset", "liability", "equity", "inventory", "receivable", "debt", "capital", "cash", "equivalent"}),
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
})
_LEGAL_TERMS = frozenset({"legal", "lawsuit", "litigation", "proceeding", "contingency"})
_LEGAL_HEADING = re.compile(
    r"^\s*(?:(?:item|note)\s+\d+[a-z]?\s*[.\u2014:\-]?\s*)?"
    r"(?:legal\s+(?:proceedings?|matters)|litigation|(?:commitments?\s+and\s+)?contingencies)" + _STATEMENT_SUFFIX,
    re.IGNORECASE | re.MULTILINE,
)


_GEOGRAPHIC_HEADING = re.compile(
    r"^\s*(?:(?:note\s+)?\d+[a-z]?\s*[.\u2014:\-]?\s*)?"
    r"(?:(?:business\s+)?segments?\s+(?:information\s+)?and\s+)?"
    r"geographic(?:al)?\s+(?:information|data|areas?)\s*[:.]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


_CUSTOMER_FOCUS = frozenset({
    "single",
    "individual",
    "major",
    "significant",
    "largest",
    "concentration",
    "concentrated",
    "depend",
})
_CUSTOMER_PERCENT = re.compile(r"\bcustomers?\b[\s\S]{0,200}?\b\d+(?:\.\d+)?\s*%", re.IGNORECASE)


def _matched_metrics(tokens: list[str]) -> tuple[tuple[str, ...], ...]:
    normalized = " " + " ".join(tokens) + " "
    names = {metric for metric in _METRICS if " " + " ".join(_tokens(metric)) + " " in normalized}
    names.update(
        metric for alias, metric in _METRIC_ALIASES.items() if " " + " ".join(_tokens(alias)) + " " in normalized
    )
    return tuple(dict.fromkeys(_METRICS[name] for name in sorted(names)))


def _supporting_components(question: str) -> tuple[str, ...]:
    """Recall separate statement components and narrowly requested disclosures."""

    tokens = set(_tokens(question))
    components = [phrase for metric in _matched_metrics(_tokens(question)) for phrase in metric]
    geographic = tokens & {
        "geography",
        "geographic",
        "geographical",
        "region",
        "country",
        "foreign",
        "oversea",
        "outside",
    }
    if geographic and tokens & {"revenue", "sale", "asset", "operation", "operate", "geography", "country"}:
        components.extend(("geographic revenue", "geographic asset" if "asset" in tokens else "geographic segment"))
    if tokens & {"lease", "rental", "rent"} and (
        tokens & {"maturity", "due", "scheduled", "future"} or "fall due" in question.lower()
    ):
        components.extend(("lease liability maturity", "future minimum lease payment"))
    if tokens & {"customer", "buyer", "client"} and tokens & _CUSTOMER_FOCUS:
        components.append("customer concentration")
    if "pension" in tokens and tokens & {"invested", "investment", "allocation", "bond", "security"}:
        components.append("pension asset allocation")
    # Components describe evidence, never report identities or fiscal headers.
    return tuple(dict.fromkeys(components))


def _query_terms(question: str) -> tuple[dict[str, float], tuple[tuple[str, ...], ...]]:
    raw = _tokens(question)
    terms = dict.fromkeys((word for word in raw if word not in _STOPWORDS), 1.0)
    normalized = " " + " ".join(raw) + " "
    expansions: list[tuple[str, ...]] = [
        concept
        for concept in _CONCEPTS
        if any(" " + " ".join(_tokens(phrase)) + " " in normalized for phrase in concept)
    ]
    expansions.extend(_matched_metrics(raw))
    # Literal accounting phrases remain a separate signal from broad synonyms.
    phrases = [
        tuple(raw[start : start + size])
        for size in (2, 3)
        for start in range(len(raw) - size + 1)
        if all(word not in _STOPWORDS for word in raw[start : start + size])
    ]
    for concept in expansions:
        for phrase in concept:
            alternative = tuple(_tokens(phrase))
            if len(alternative) > 1:
                phrases.append(alternative)
            for token in alternative:
                if token not in _STOPWORDS:
                    terms.setdefault(token, 0.5)
    return terms, tuple(dict.fromkeys(phrases))


async def search_pdf_pages(
    memory: ScopedMemoryApplication, question: str, limit: int = 10
) -> tuple[MemoryCitation, ...]:
    """Rank active captured pages from one scoped Memory snapshot, entirely offline.

    Public ``search`` supplies native FTS candidates; ``list`` supplies the
    active page snapshot and its exact citations. Offline BM25 also uses that corpus
    rather than relying solely on a natural-language FTS admission cutoff,
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
    from powercontext.builtin.runtime import SearchMemoryRequest

    records = _select_reports(records, question)
    terms, phrases = _page_query(records, question, terms, phrases)
    components = _supporting_components(question)
    # Ask the public search API for native lexical candidates as well. The
    # snapshot remains authoritative: concurrent writes cannot invent a citation
    # or move this query to another Memory revision. Explicit FTS avoids vectors.
    native = await memory.search(
        SearchMemoryRequest(query=" ".join(terms), mode="fts", limit=min(200, max(40, limit * 5)))
    )
    versions = {
        record.entry.entry_version_id: record.entry.sources[0].source_id
        for record in snapshot.entries
        if len(record.entry.sources) == 1 and record.entry.sources[0].source_type == "pdf-page"
    }
    native_sources = tuple(
        dict.fromkeys(
            versions[hit.entry_version_id]
            for hit in native.hits
            if hit.memory_ref == snapshot.memory_ref and hit.entry_version_id in versions
        )
    )
    return _rank_pages(records, terms, phrases, limit, components=components, native_sources=native_sources)


def _page_query(
    records: list[MemoryEntryRecord],
    question: str,
    terms: dict[str, float],
    phrases: tuple[tuple[str, ...], ...],
) -> tuple[dict[str, float], tuple[tuple[str, ...], ...]]:
    """Separate a report selector from the subject of its evidence pages.

    Company names and fiscal years select reports, but their repetition in
    running headers and narrative is not evidence about the requested metric.
    Only remove company words when the question actually names that identity;
    arbitrary document IDs must not suppress otherwise useful subject words.
    """

    question_words = set(_tokens(question))
    selectors = set(_REPORT_YEAR.findall(question))
    for document in {record.entry.text.partition("\n")[0] for record in records}:
        company_part = _REPORT_YEAR.split(document, maxsplit=1)[0]
        company_words = {
            word
            for word in _IDENTITY_WORDS.findall(company_part.lower())
            if word not in _REPORT_SUFFIXES and word not in {"and", "the"} and not word.isdigit()
        }
        normalized_company = set(_tokens(" ".join(company_words)))
        if normalized_company and normalized_company <= question_words:
            selectors.update(normalized_company)
    focused = {term: weight for term, weight in terms.items() if term not in selectors}
    # Identity-only searches retain their original behavior.
    if not focused:
        return terms, phrases
    return focused, tuple(phrase for phrase in phrases if not selectors.intersection(phrase))


def _select_reports(records: list[MemoryEntryRecord], question: str) -> list[MemoryEntryRecord]:
    """Honor explicit report identities before ranking page content across companies."""

    question_words = _IDENTITY_WORDS.findall(question.lower())
    # Joining neighboring words accommodates report IDs such as COCA_COLA and
    # questions spelling the same name as CocaCola, without matching 3M to X3M.
    mentioned_names = {
        "".join(words[start:end])
        for words in (question_words, [word for word in question_words if word not in {"and", "the"}])
        for start in range(len(words))
        for end in range(start + 1, min(start + 6, len(words)) + 1)
    }
    documents = {record.entry.text.partition("\n")[0] for record in records}
    selected: dict[str, set[str]] = {}
    for document in documents:
        # Reporting periods and suffixes are not part of the company name.
        # Keep alphanumeric company tokens such as 3M intact.
        company_part = _REPORT_YEAR.split(document, maxsplit=1)[0]
        company_words = [
            word
            for word in _IDENTITY_WORDS.findall(company_part.lower())
            if word not in _REPORT_SUFFIXES and word not in {"and", "the"} and not word.isdigit()
        ]
        company = "".join(company_words)
        aliases = {company} if len(company) > 1 and company not in _STOPWORDS else set()
        # Derive initialisms from the caller's identity, without company tables.
        if len(company_words) >= 3:
            aliases.add("".join(word[0] for word in company_words))
        if aliases & mentioned_names:
            selected.setdefault(company, set()).add(document)
    if not selected:
        return records
    report_years = {year for match in _EXPLICIT_REPORT_YEAR.findall(question) for year in match if year}
    years = report_years or set(_REPORT_YEAR.findall(question))
    documents = {
        document
        for company_documents in selected.values()
        for document in _select_report_years(company_documents, years, explicit=bool(report_years))
    }
    return [record for record in records if record.entry.text.partition("\n")[0] in documents]


def _select_report_years(documents: set[str], years: set[str], *, explicit: bool) -> set[str]:
    matching = {document for document in documents if years.intersection(_REPORT_YEAR.findall(document))}
    if not matching:
        return documents
    if explicit:
        return matching
    # A financial year is not a filing identity: newer reports can contain its
    # comparative or restated figures. Apply fallback independently per company.
    return matching | {
        document for document in documents if any(year > min(years) for year in _REPORT_YEAR.findall(document))
    }


def _rank_pages(
    records: list[MemoryEntryRecord],
    terms: dict[str, float],
    phrases: tuple[tuple[str, ...], ...],
    limit: int,
    *,
    components: tuple[str, ...] = (),
    native_sources: tuple[str, ...] = (),
) -> tuple[MemoryCitation, ...]:
    """Fuse page, literal-query and local-passage rankings of the same snapshot."""

    bodies = [record.entry.text.partition("\n")[2] for record in records]
    component_queries = [
        (
            (dict.fromkeys(_tokens(component), 1.0), (tuple(_tokens(component)),))
            if component.startswith("geographic ")
            else _query_terms(component)
        )
        for component in components
    ]
    indexed_terms = set(terms).union(*(query.keys() for query, _ in component_queries))
    token_lists = [_tokens(body, indexed_terms) for body in bodies]
    counts = [Counter(tokens) for tokens in token_lists]
    frequency = Counter(token for count in counts for token in count)
    average_length = max(1.0, sum(map(len, token_lists)) / len(records))
    idf = {term: math.log1p((len(records) - frequency[term] + 0.5) / (frequency[term] + 0.5)) for term in indexed_terms}
    literal_terms = {term: weight for term, weight in terms.items() if weight == 1.0}
    rankings: list[list[tuple[float, int]]] = [[], [], []]
    component_rankings: list[list[tuple[float, int]]] = [[] for _ in component_queries]
    for index, (record, tokens, count) in enumerate(zip(records, token_lists, counts, strict=True)):
        score = _bm25(count, len(tokens), terms, idf, average_length)
        literal_score = _bm25(count, len(tokens), literal_terms, idf, average_length)
        # Phrase matches favor actual statement bodies over incidental mentions.
        normalized = " " + " ".join(tokens) + " "
        score += sum(
            sum(idf.get(term, 0.0) for term in phrase) * 0.6
            for phrase in phrases
            if " " + " ".join(phrase) + " " in normalized
        )
        literal_score += sum(
            sum(idf[term] for term in phrase) * 0.6
            for phrase in phrases
            if all(term in literal_terms for term in phrase) and " " + " ".join(phrase) + " " in normalized
        )
        # Actual statement titles are stronger evidence than a long discussion
        # repeating the same metrics. Restrict to complete heading lines near
        # the page start, so prose and numbered table-of-contents rows do not win.
        body = _search_text(bodies[index], indexed_terms)
        score += _evidence_bonus(body, terms, idf)
        document_tokens = set(_tokens(record.entry.text.partition("\n")[0])) - {"10", "k", "q", "form", "report"}
        company = {term for term in document_tokens if not term.isdigit() and terms.get(term) == 1.0}
        if company:
            score *= 2.0
        if any(term.isdigit() and len(term) == 4 and terms.get(term) == 1.0 for term in document_tokens):
            score *= 1.25
        if score > 0:
            rankings[0].append((score, index))
        if literal_score > 0:
            rankings[1].append((literal_score, index))
        # A table or short note can occupy only a small part of a dense page.
        # Fixed overlapping token windows do not alter the captured page text.
        passage_score = max(
            (
                _bm25(Counter(tokens[start : start + 120]), len(tokens[start : start + 120]), terms, idf, 120.0)
                for start in range(0, len(tokens), 60)
            ),
            default=0.0,
        )
        if passage_score > 0:
            rankings[2].append((passage_score, index))
        for component_ranking, (query, component_phrases) in zip(component_rankings, component_queries, strict=True):
            component_score = _bm25(count, len(tokens), query, idf, average_length)
            if component_score <= 0:
                continue
            component_score += _evidence_bonus(body, query, idf)
            component_score += sum(
                0.6 * sum(idf.get(term, 0.0) for term in phrase)
                for phrase in component_phrases
                if " " + " ".join(phrase) + " " in normalized
            )
            component_ranking.append((component_score, index))
    if native_sources and limit >= 10:
        positions = {record.entry.sources[0].source_id: index for index, record in enumerate(records)}
        rankings.append([
            (1.0 / rank, positions[source]) for rank, source in enumerate(native_sources, 1) if source in positions
        ])
    return _fuse_page_rankings(records, rankings, limit, component_rankings=component_rankings, token_counts=counts)


def _evidence_bonus(body: str, terms: dict[str, float], idf: dict[str, float]) -> float:
    score = sum(
        3.0 * sum(terms[term] * idf[term] for term in vocabulary & terms.keys())
        for vocabulary, heading in _STATEMENT_HEADINGS
        if heading.search(body[:2000])
    )
    if _GEOGRAPHY_TERMS & terms.keys() and (_BUSINESS_HEADING.search(body) or _GEOGRAPHIC_HEADING.search(body)):
        score += 3.0 * sum(terms[term] * idf[term] for term in _GEOGRAPHY_TERMS & terms.keys())
    if _LEGAL_TERMS & terms.keys() and _LEGAL_HEADING.search(body[:2000]):
        score += 3.0 * sum(terms[term] * idf[term] for term in _LEGAL_TERMS & terms.keys())
    # Concentration questions need the disclosure's numeric relationship, not
    # pages merely discussing customer acquisition or distribution channels.
    if "customer" in terms and _CUSTOMER_FOCUS & terms.keys() and _CUSTOMER_PERCENT.search(body):
        score += 6.0 * sum(terms[term] * idf[term] for term in ({"customer"} | _CUSTOMER_FOCUS) & terms.keys())
    return score


def _bm25(
    count: Counter[str], length: int, terms: dict[str, float], idf: dict[str, float], average_length: float
) -> float:
    normalization = 1.2 * (0.55 + 0.45 * length / average_length)
    return sum(
        weight * idf[term] * count[term] * 2.2 / (count[term] + normalization)
        for term, weight in terms.items()
        if count[term]
    )


def _fuse_page_rankings(
    records: list[MemoryEntryRecord],
    rankings: list[list[tuple[float, int]]],
    limit: int,
    *,
    component_rankings: list[list[tuple[float, int]]] | None = None,
    token_counts: list[Counter[str]] | None = None,
) -> tuple[MemoryCitation, ...]:
    fused: dict[int, float] = {}
    # Preserve the statement-aware channel while allowing literal evidence and
    # locally relevant notes to compete without incompatible raw score scales.
    for weight, ranking in zip((1.0, 0.65, 0.8, 0.45)[: len(rankings)], rankings, strict=True):
        ranking.sort(key=lambda item: (-item[0], item[1]))
        for rank, (_, index) in enumerate(ranking, 1):
            fused[index] = fused.get(index, 0.0) + weight / (20 + rank)
    # Rank-only fusion loses how much stronger an actual statement is than a
    # page merely repeating every query term. Retain bounded primary confidence.
    maximum = max((score for score, _ in rankings[0]), default=1.0)
    for score, index in rankings[0]:
        fused[index] += 0.1 * score / maximum
    ordered = sorted(fused, key=lambda index: (-fused[index], index))
    selected = _component_pages(component_rankings, limit)
    # A metric may require several different statements. Reserve a bounded part
    # of the result window for their strongest supporting pages, then retain
    # the fused ranking for the remaining slots. Small limits keep pure ranking.
    if limit >= 4 and token_counts is not None and len(ordered) > limit:
        return tuple(
            records[index].citation for index in _diverse_pages(records, ordered, fused, selected, token_counts, limit)
        )
    for index in ordered:
        if len(selected) >= limit:
            break
        selected.add(index)
    return tuple(
        records[index].citation for index in sorted(selected, key=lambda index: (-fused.get(index, 0.0), index))
    )


def _component_pages(rankings: list[list[tuple[float, int]]] | None, limit: int) -> set[int]:
    selected: set[int] = set()
    if limit < 4 or not rankings:
        return selected
    for ranking in rankings:
        ranking.sort(key=lambda item: (-item[0], item[1]))
    for depth in range(2):
        for ranking in rankings:
            if depth < len(ranking) and len(selected) < limit // 2:
                selected.add(ranking[depth][1])
    return selected


def _diverse_pages(
    records: list[MemoryEntryRecord],
    ordered: list[int],
    scores: dict[int, float],
    reserved: set[int],
    token_counts: list[Counter[str]],
    limit: int,
) -> list[int]:
    """Downweight near-identical pages, without dropping citations or revisions."""

    selected = sorted(reserved, key=lambda index: (-scores.get(index, 0.0), index))
    remaining = set(ordered[: max(100, limit * 5)]) - reserved
    candidates = remaining | reserved
    narratives = {
        index
        for index in candidates
        if sum(token_counts[index].values()) >= 40
        and sum(count for token, count in token_counts[index].items() if token.isdigit())
        <= 0.25 * sum(token_counts[index].values())
        and not any(
            heading.search(_search_text(records[index].entry.text.partition("\n")[2])[:2000])
            for _, heading in _STATEMENT_HEADINGS
        )
    }
    vectors = {
        index: {
            token: count
            for token, count in token_counts[index].items()
            if token not in _STOPWORDS and not token.isdigit()
        }
        for index in candidates
    }
    norms = {index: math.sqrt(sum(count * count for count in vector.values())) for index, vector in vectors.items()}
    documents = {index: records[index].entry.text.partition("\n")[0] for index in vectors}
    redundancy = dict.fromkeys(remaining, 0.0)

    def penalize(previous: int) -> None:
        left = vectors[previous]
        # Page numbers and filing dates do not distinguish repeated narrative
        # exhibits. Protect statements and numeric tables from this treatment.
        if previous not in narratives:
            return
        for index in remaining:
            if (
                index not in narratives
                or documents[index] != documents[previous]
                or not norms[index]
                or not norms[previous]
            ):
                continue
            right = vectors[index]
            smaller, larger = (left, right) if len(left) <= len(right) else (right, left)
            similarity = sum(count * larger.get(token, 0) for token, count in smaller.items()) / (
                norms[index] * norms[previous]
            )
            if similarity >= 0.9:
                redundancy[index] += similarity

    for index in selected:
        penalize(index)
    while remaining and len(selected) < limit:
        best = max(remaining, key=lambda index: (scores[index] / (1.0 + 0.6 * redundancy[index]), -index))
        remaining.remove(best)
        selected.append(best)
        penalize(best)
    return selected


__all__ = [
    "PDF_PAGE_SOURCE_DEFINITION",
    "PDFDocumentInput",
    "PDFPageInput",
    "PDFPageSource",
    "parse_pdf_document",
    "search_pdf_pages",
]
