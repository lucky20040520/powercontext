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

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import re
import zlib
from collections import Counter

import pytest
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NullObject, NumberObject

from powercontext.sources import SourceDefinitionRegistry, SourceMaterialization, TextEvidence
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    PDFPageInput,
    PDFPageSource,
    parse_pdf_document,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY

_OWNER_PASSWORD = "test-owner"  # noqa: S105 - deterministic encryption fixture
_USER_PASSWORD = "test-user"  # noqa: S105 - deterministic encryption fixture


def _document(
    *, password: str | None = None, broken_tail: bool = False, algorithm: str = "RC4-128", indirect_filter: bool = False
) -> bytes:
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
    })
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 50 700 Td (Revenue 2025 1,234.56) Tj 0 -20 Td (Net income 789) Tj ET")
    if indirect_filter:
        stream = stream.flate_encode()
        stream[NameObject("/Filter")] = writer._add_object(NameObject("/FlateDecode"))
    page[NameObject("/Contents")] = stream
    tail = writer.add_blank_page(width=612, height=792)
    if broken_tail:
        tail[NameObject("/Contents")] = NumberObject(7)
    if password is not None:
        writer.encrypt(user_password=password, owner_password=_OWNER_PASSWORD, algorithm=algorithm)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_full_text_numbers_blanks_and_source_roundtrip() -> None:
    raw = _document()
    pages = parse_pdf_document(PDFDocumentInput(document_id="财报 / 2025", content=raw))
    assert len(pages) == 2
    first, blank = pages
    assert first.page_number == 1 and blank.page_number == 2 and blank.text == ""
    assert "Revenue 2025 1,234.56" in first.text and "Net income 789" in first.text
    assert all(page.document_sha256 == hashlib.sha256(raw).hexdigest() for page in pages)
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    source = asyncio.run(registry.resolve(first))
    assert isinstance(source, PDFPageSource)
    assert source.materialization is SourceMaterialization.CAPTURED
    assert PDF_PAGE_SOURCE_DEFINITION.name == "pdf-page" and PDF_PAGE_SOURCE_DEFINITION.version == "1"
    source = PDFPageSource.model_validate_json(source.model_dump_json())
    assert asyncio.run(registry.read(source)) == first
    evidence = TextEvidence.model_validate(registry.project(source, TEXT_EVIDENCE_PROJECTION_KEY))
    assert evidence.source_type == "pdf-page" and evidence.source_id == source.name
    assert evidence.content == f"{first.document_id}\n{first.text}"
    assert evidence.metadata == {
        "document_id": first.document_id,
        "document_sha256": first.document_sha256,
        "page_number": 1,
    }


@pytest.mark.parametrize("algorithm", ["RC4-128", "AES-128", "AES-256"])
def test_empty_password_permission_pdf_preserves_text(algorithm: str) -> None:
    raw = _document(password="", algorithm=algorithm)
    pages = parse_pdf_document(PDFDocumentInput(document_id="permissions", content=raw))
    assert len(pages) == 2 and "1,234.56" in pages[0].text


@pytest.mark.parametrize(
    "raw",
    [b"", b"not pdf", b"%PDF-1.7\ntruncated", _document(password=_USER_PASSWORD), _document(broken_tail=True)],
    ids=["empty", "not-pdf", "truncated", "password-required", "broken-last-page"],
)
def test_invalid_or_partially_readable_documents_fail_atomically(raw: bytes) -> None:
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="invalid", content=raw))


@pytest.mark.parametrize("identity", ["", " \t\n"])
def test_blank_document_identity_is_rejected(identity: str) -> None:
    with pytest.raises(ValueError):
        PDFDocumentInput(document_id=identity, content=_document())


def test_source_identity_is_bounded_stable_and_revision_specific() -> None:
    base = PDFPageInput(document_id="文档:/" * 1000, document_sha256="a" * 64, page_number=1, text="first")
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))

    def identity(page: PDFPageInput) -> str:
        return asyncio.run(registry.resolve(page)).name

    assert len(identity(base)) <= 256
    assert identity(base) == identity(base.model_copy(update={"text": "changed"}))
    variants = [
        base.model_copy(update=change)
        for change in ({"document_id": base.document_id + ":"}, {"document_sha256": "b" * 64}, {"page_number": 2})
    ]
    assert len({identity(base), *(identity(page) for page in variants)}) == 4
    source = asyncio.run(registry.resolve(base))
    with pytest.raises(ValueError):
        PDFPageSource.model_validate(source.model_dump() | {"page_number": 2})


@pytest.mark.parametrize("changes", [{"page_number": 0}, {"page_number": True}, {"document_sha256": "A" * 64}])
def test_manually_supplied_pages_validate_location(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        PDFPageInput.model_validate(
            {"document_id": "report", "document_sha256": "a" * 64, "page_number": 1, "text": ""} | changes
        )


def test_corrupt_compressed_page_is_not_silently_returned_as_blank() -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=200)
    stream = DecodedStreamObject()
    contents = b"BT (must not silently disappear) Tj ET"
    stream.set_data(contents)
    page[NameObject("/Contents")] = stream.flate_encode()
    output = io.BytesIO()
    writer.write(output)
    encoded = zlib.compress(contents)
    raw = output.getvalue()
    assert encoded in raw
    # Keep byte offsets and Length valid, but corrupt the zlib checksum.
    damaged = raw.replace(encoded, encoded[:-4] + b"\x00\x00\x00\x00", 1)
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="corrupt-stream", content=damaged))


def test_chained_filters_preserve_complete_text_and_reject_corruption() -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=100, height=200)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
        })
    })
    stream = DecodedStreamObject()
    original = b"BT /F1 12 Tf (Revenue 12345 and operating income 6789) Tj ET"
    encoded = base64.a85encode(zlib.compress(original)) + b"~>"
    stream.set_data(encoded)
    stream[NameObject("/Filter")] = ArrayObject([NameObject("/ASCII85Decode"), NameObject("/FlateDecode")])
    page[NameObject("/Contents")] = stream
    output = io.BytesIO()
    writer.write(output)
    pages = parse_pdf_document(PDFDocumentInput(document_id="filter-chain", content=output.getvalue()))
    assert "12345" in pages[0].text and "6789" in pages[0].text
    corrupt = base64.a85encode(zlib.compress(original)[:-4] + b"\x00\x00\x00\x00") + b"~>"
    assert len(corrupt) == len(encoded)
    with pytest.raises(ValueError):
        parse_pdf_document(
            PDFDocumentInput(document_id="filter-chain", content=output.getvalue().replace(encoded, corrupt, 1))
        )


def test_indirect_compression_filter_is_a_readable_pdf() -> None:
    pages = parse_pdf_document(PDFDocumentInput(document_id="indirect-filter", content=_document(indirect_filter=True)))
    assert len(pages) == 2 and "Revenue 2025 1,234.56" in pages[0].text


def _text_document(contents: bytes, *, form: bool = False) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=400_000, height=792)
    fonts = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
        })
    })
    stream = DecodedStreamObject()
    stream.set_data(contents)
    if form:
        stream.update({
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): ArrayObject([NumberObject(n) for n in (0, 0, 400_000, 792)]),
            NameObject("/Resources"): fonts,
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/XObject"): DictionaryObject({NameObject("/Report"): writer._add_object(stream)})
        })
        stream = DecodedStreamObject()
        stream.set_data(b"q /Report Do Q")
    else:
        page[NameObject("/Resources")] = fonts
    page[NameObject("/Contents")] = stream
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_form_page_keeps_complete_text_when_layout_is_empty() -> None:
    raw = _text_document(
        b"BT /F1 12 Tf 50 700 Td (Revenue    2025    1234.56) Tj 0 -20 Td (Net income    789) Tj ET",
        form=True,
    )
    (page,) = parse_pdf_document(PDFDocumentInput(document_id="form-report", content=raw))
    assert page.text.splitlines() == ["Revenue 2025 1234.56", "Net income 789"]
    assert page.document_sha256 == hashlib.sha256(raw).hexdigest()


def test_wide_layout_preserves_columns_rows_and_tokens_with_bounded_whitespace() -> None:
    raw = _text_document(
        b"BT /F1 12 Tf 50 700 Td (Revenue 2025 1234.56) Tj "
        b"250000 0 Td (Net income 789) Tj 0 -20 Td (Final debt maturity 987654321) Tj ET"
    )
    (page,) = parse_pdf_document(PDFDocumentInput(document_id="wide-report", content=raw))
    assert Counter(re.findall(r"[a-z]+|\d+", page.text.lower())) == Counter([
        "revenue",
        "2025",
        "1234",
        "56",
        "net",
        "income",
        "789",
        "final",
        "debt",
        "maturity",
        "987654321",
    ])
    assert "Revenue 2025 1234.56 Net income 789" in page.text
    assert "\n" in page.text.partition("Net income 789")[2].partition("Final debt maturity")[0]
    assert len(page.text.encode("utf-8")) < 32768
    assert not re.search(r"[ \t]{2,}", page.text)


def test_whitespace_only_page_is_empty() -> None:
    raw = _text_document(b"BT /F1 12 Tf 50 700 Td (    ) Tj ET", form=True)
    (page,) = parse_pdf_document(PDFDocumentInput(document_id="blank-form", content=raw))
    assert page.text == ""


@pytest.mark.parametrize("contents", [NullObject(), ArrayObject()], ids=["null", "empty-array"])
def test_empty_contents_preserves_blank_page(contents: NullObject | ArrayObject) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Contents")] = contents
    output = io.BytesIO()
    writer.write(output)
    (parsed,) = parse_pdf_document(PDFDocumentInput(document_id="empty-contents", content=output.getvalue()))
    assert parsed.page_number == 1 and parsed.text == ""


def test_plain_table_does_not_merge_years_or_drop_form_labels() -> None:
    raw = _text_document(
        b"BT /F1 12 Tf 50 700 Td (Cash flow 2025) Tj 250 0 Td (2026 1234.56) Tj 0 -20 Td (Q R S T U V) Tj ET",
        form=True,
    )
    (page,) = parse_pdf_document(PDFDocumentInput(document_id="year-table", content=raw))
    assert re.findall(r"\d+", page.text) == ["2025", "2026", "1234", "56"]
    assert "Cash flow" in page.text and "Q R S T U V" in page.text


def test_fragmented_letters_use_complete_improved_layout_candidate() -> None:
    raw = _text_document(
        b"BT /F1 12 Tf 50 700 Td [(R) -135 (e) -135 (v) -135 (e) -135 (n) -135 (u) -135 (e)] TJ "
        b"0 -20 Td (2025 1234.56) Tj ET"
    )
    (page,) = parse_pdf_document(PDFDocumentInput(document_id="fragmented-label", content=raw))
    assert page.text.split() == ["Revenue", "2025", "1234.56"]


def test_repairing_fragments_does_not_treat_existing_repeated_headings_as_new_duplicates() -> None:
    raw = _text_document(
        b"BT /F1 12 Tf 50 700 Td [(R) -135 (e) -135 (v) -135 (e) -135 (n) -135 (u) -135 (e)] TJ "
        b"( operating cash flow) Tj 0 -20 Td (Revenue operating cash flow) Tj ET"
    )
    (page,) = parse_pdf_document(PDFDocumentInput(document_id="repeated-heading", content=raw))
    assert [line.strip() for line in page.text.splitlines() if line.strip()] == [
        "Revenue operating cash flow",
        "Revenue operating cash flow",
    ]


def test_sparse_short_fragments_at_line_breaks_are_not_hidden_by_long_healthy_text() -> None:
    fragmented = b"[(R) -135 (e) -135 (v) -135 (e) -135 (n) -135 (u) -135 (e)] TJ 0 -20 Td "
    healthy = b"Normal healthy business statement with consistent financial reporting. " * 200
    raw = _text_document(b"BT /F1 12 Tf 50 700 Td " + fragmented * 3 + b"(" + healthy + b") Tj ET")
    (page,) = parse_pdf_document(PDFDocumentInput(document_id="sparse-fragments", content=raw))
    assert page.text.count("Revenue") == 3 and "R e v e n u e" not in page.text
    assert page.text.count("Normal healthy business statement with consistent financial reporting.") == 200


@pytest.mark.parametrize("form_text", [b"Chart legend 987654321", b"$%-"], ids=["chart-legend", "financial-signs"])
def test_nonempty_layout_cannot_discard_form_text_to_improve_fragments(form_text: bytes) -> None:
    from pypdf import PdfReader

    reader = PdfReader(
        io.BytesIO(
            _text_document(b"BT /F1 12 Tf 50 700 Td [(R) -135 (e) -135 (v) -135 (e) -135 (n) -135 (u) -135 (e)] TJ ET")
        )
    )
    writer = PdfWriter()
    page = writer.add_page(reader.pages[0])
    resources = page["/Resources"]
    assert isinstance(resources, DictionaryObject)
    form = DecodedStreamObject()
    form.set_data(b"BT /F1 12 Tf 50 600 Td (" + form_text + b") Tj ET")
    form.update({
        NameObject("/Type"): NameObject("/XObject"),
        NameObject("/Subtype"): NameObject("/Form"),
        NameObject("/BBox"): ArrayObject([NumberObject(n) for n in (0, 0, 612, 792)]),
        NameObject("/Resources"): DictionaryObject(resources),
    })
    resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Chart"): writer._add_object(form)})
    stream = DecodedStreamObject()
    contents = page.get_contents()
    assert contents is not None
    stream.set_data(contents.get_data() + b" q /Chart Do Q")
    page[NameObject("/Contents")] = stream
    output = io.BytesIO()
    writer.write(output)
    (parsed,) = parse_pdf_document(PDFDocumentInput(document_id="mixed-form", content=output.getvalue()))
    assert form_text.decode("ascii") in parsed.text and "R e v e n u e" in parsed.text


def test_exact_overprint_removes_only_same_position_and_preserves_following_text() -> None:
    raw = _text_document(b"BT /F1 12 Tf 1 0 0 1 50 700 Tm (Revenue 2025) Tj 1 0 0 1 50 700 Tm (Revenue 2025) Tj ET")
    (page,) = parse_pdf_document(PDFDocumentInput(document_id="overprint", content=raw))
    assert page.text.strip() == "Revenue 2025"


@pytest.mark.parametrize(
    "second",
    [b"1 0 0 1 50 680 Tm", b"1 0 0 1 51 700 Tm", b"/F1 13 Tf 1 0 0 1 50 700 Tm", b"1 0 0 rg 1 0 0 1 50 700 Tm"],
    ids=["different-row", "different-position", "different-size", "different-color"],
)
def test_legitimate_repeated_text_is_not_deduplicated(second: bytes) -> None:
    raw = _text_document(b"BT /F1 12 Tf 1 0 0 1 50 700 Tm (Revenue 2025) Tj " + second + b" (Revenue 2025) Tj ET")
    (page,) = parse_pdf_document(PDFDocumentInput(document_id="repetition", content=raw))
    assert page.text.count("Revenue") == 2 and page.text.count("2025") == 2


def _actual_text_document(spans: bytes) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    cmap = DecodedStreamObject()
    cmap.set_data(
        b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap "
        b"/CMapType 2 def 1 begincodespacerange <0000> <FFFF> endcodespacerange "
        b"1 beginbfrange <0020> <007E> <0020> endbfrange "
        b"1 beginbfchar <0100> <0000> endbfchar endcmap end end"
    )
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type0"),
        NameObject("/BaseFont"): NameObject("/TestCID"),
        NameObject("/Encoding"): NameObject("/Identity-H"),
        NameObject("/ToUnicode"): cmap,
        NameObject("/DescendantFonts"): ArrayObject([
            DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/CIDFontType2"),
                NameObject("/BaseFont"): NameObject("/TestCID"),
                NameObject("/DW"): NumberObject(500),
            })
        ]),
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
    })
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 50 700 Td <006F007000650072> Tj " + spans + b" <0069006E0067> Tj ET")
    page[NameObject("/Contents")] = stream
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize(
    "replacement,expected", [(b"(at)", "operating"), (b"<FEFF00610074>", "operating"), (b"(xy)", "operxying")]
)
def test_pdf_actual_text_recovers_null_ligature_from_document_metadata(replacement: bytes, expected: str) -> None:
    raw = _actual_text_document(b"/Span << /ActualText " + replacement + b" >> BDC <0100> Tj EMC")
    (page,) = parse_pdf_document(PDFDocumentInput(document_id="marked-text", content=raw))
    assert page.text == expected
    assert page.document_sha256 == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize(
    "spans",
    [
        b"/Span << /ActualText (at) >> BDC <0100> Tj EMC <0100> Tj",
        b"/Span << /ActualText (at) >> BDC <0100> Tj EMC /Span << /ActualText (xy) >> BDC <0100> Tj EMC",
        b"/Span << /ActualText (at) >> BDC <01000100> Tj EMC",
        b"/Span << /ActualText (at) >> BDC /Span << /ActualText (xy) >> BDC <0100> Tj EMC EMC",
    ],
    ids=["uncovered-occurrence", "conflicting-replacements", "multiple-glyphs", "nested-replacements"],
)
def test_uncertain_actual_text_does_not_guess_null_characters(spans: bytes) -> None:
    raw = _actual_text_document(spans)
    (page,) = parse_pdf_document(PDFDocumentInput(document_id="uncertain-marked-text", content=raw))
    assert "\0" in page.text and "at" not in page.text and "xy" not in page.text


def test_fragment_repairs_are_not_penalized_by_a_smaller_word_denominator() -> None:
    contents = (
        b"BT /F1 12 Tf 50 700 Td [(R) -135 (e) -135 (v) -135 (e) -135 (n) -135 (u) -135 (e)] TJ "
        b"0 -20 Td " + b"[(Infor) -135 (mation)] TJ ( ) Tj " * 40 + b"0 -20 Td (" + b"L.L.C. " * 20 + b") Tj ET"
    )
    raw = _text_document(contents)
    (page,) = parse_pdf_document(PDFDocumentInput(document_id="legal-initials", content=raw))
    assert "Revenue" in page.text and page.text.count("Information") == 40
    assert page.text.count("L.L.C.") == 20


def _cid_text_document(contents: bytes, *, nonbreaking_space: bool = False) -> bytes:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(_actual_text_document(b"")))
    writer = PdfWriter()
    page = writer.add_page(reader.pages[0])
    resources = page["/Resources"]
    assert isinstance(resources, DictionaryObject)
    fonts = resources["/Font"]
    assert isinstance(fonts, DictionaryObject)
    font = fonts["/F1"]
    assert isinstance(font, DictionaryObject)
    if nonbreaking_space:
        mapping = font["/ToUnicode"]
        assert isinstance(mapping, DecodedStreamObject)
        mapping.set_data(mapping.get_data().replace(b"endcmap", b"1 beginbfchar <0020> <00A0> endbfchar endcmap"))
    descendants = font["/DescendantFonts"]
    assert isinstance(descendants, ArrayObject)
    descendant = descendants[0]
    assert isinstance(descendant, DictionaryObject)
    descendant[NameObject("/W")] = ArrayObject([
        NumberObject(32),
        ArrayObject([NumberObject(250)]),
    ])
    stream = DecodedStreamObject()
    stream.set_data(contents)
    page[NameObject("/Contents")] = stream
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_sparse_word_uses_effective_glyph_baseline_including_text_rise() -> None:
    raw = _cid_text_document(
        b"BT /F1 12 Tf 12 Ts 1 0 0 1 50 700 Tm <0052> Tj 0 Ts 1 0 0 1 56 712 Tm <0045005300450052005600450044> Tj ET"
    )
    (page,) = parse_pdf_document(PDFDocumentInput(document_id="sparse-heading", content=raw))
    assert page.text == "RESERVED"
    assert page.page_number == 1 and page.document_sha256 == hashlib.sha256(raw).hexdigest()


def test_numeric_fragments_follow_cid_positions_and_preserve_separate_table_values() -> None:
    raw = _cid_text_document(
        b"BT /F1 12 Tf 50 700 Td "
        b"[<0052> -125 <0065> -125 <0076> -125 <0065> -125 <006e> -125 <0075> -125 <0065>] TJ "
        b"1 0 0 1 50 680 Tm <00320030> Tj 13.5 0 Td <00320037> Tj "
        b"1 0 0 1 200 680 Tm <0032003000320038> Tj ET "
        b"BT /F1 12 Tf 300 750 Td <0037> Tj ET "
        b"BT /F1 6 Tf 1 1 1 rg 500 730 Td <00310032003300340035002e0036003700380039> Tj ET"
    )
    (page,) = parse_pdf_document(PDFDocumentInput(document_id="numeric-boundaries", content=raw))
    assert "Revenue" in page.text
    assert Counter(re.findall(r"\d+", page.text)) == Counter(["2027", "2028", "7", "12345", "6789"])


def test_nearby_footnote_is_not_inserted_inside_a_contiguous_number() -> None:
    raw = _cid_text_document(
        b"BT /F1 12 Tf 12 Ts 1 0 0 1 50 700 Tm <0052> Tj "
        b"0 Ts 1 0 0 1 56 712 Tm <0045005300450052005600450044> Tj ET "
        b"BT /F1 12 Tf 1 0 0 1 50 680 Tm <003100320033> Tj ET "
        b"BT /F1 12 Tf 1 0 0 1 68 680 Tm <003400350036> Tj ET "
        b"BT /F1 6 Tf 1 0 0 1 65 684 Tm <002800610029> Tj ET"
    )
    (page,) = parse_pdf_document(PDFDocumentInput(document_id="numeric-footnote", content=raw))
    assert page.text.splitlines() == ["RESERVED", "123456", "(a)"]


def test_local_short_fragment_uses_nbsp_geometry_without_removing_word_separators() -> None:
    raw = _cid_text_document(
        b"BT /F1 12 Tf 12 Ts 1 0 0 1 50 700 Tm <00520065> Tj "
        b"0 Ts 1 0 0 1 62 712 Tm <00760065006e00750065> Tj "
        b"1 0 0 1 50 680 Tm <004e0065007400200069006e0063006f006d0065> Tj ET",
        nonbreaking_space=True,
    )
    (page,) = parse_pdf_document(PDFDocumentInput(document_id="local-short-fragment", content=raw))
    assert [line for line in page.text.splitlines() if line.strip()] == ["Revenue", "Net\N{NO-BREAK SPACE}income"]
    assert page.page_number == 1 and page.document_sha256 == hashlib.sha256(raw).hexdigest()


def test_effective_baselines_separate_merged_labels_and_preserve_financial_signs() -> None:
    raw = _cid_text_document(
        b"BT /F1 12 Tf 12 Ts 1 0 0 1 50 700 Tm <00520065> Tj "
        b"0 Ts 1 0 0 1 62 712 Tm <00760065006e00750065> Tj "
        b"1 0 0 1 50 680 Tm <004100730073006500740073> Tj "
        b"-20 Ts 1 0 0 1 86 680 Tm <004c0069006100620069006c00690074006900650073> Tj "
        b"0 Ts 1 0 0 1 50 640 Tm <002d00310032002e0035003000200037002e00350025> Tj ET",
        nonbreaking_space=True,
    )
    (page,) = parse_pdf_document(PDFDocumentInput(document_id="separate-labels", content=raw))
    assert [line.strip() for line in page.text.splitlines() if line.strip()] == [
        "Revenue",
        "Assets",
        "Liabilities",
        "-12.50\N{NO-BREAK SPACE}7.5%",
    ]
