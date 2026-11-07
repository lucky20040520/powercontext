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

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject

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


def test_nested_form_text_is_complete_and_corruption_fails_atomically() -> None:
    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(io.BytesIO(_document())))
    page = writer.pages[0]
    page_contents = page.get_contents()
    assert page_contents is not None
    original = page_contents.get_data()
    form = DecodedStreamObject()
    form.set_data(original)
    form = form.flate_encode()
    form[NameObject("/Subtype")] = NameObject("/Form")
    form[NameObject("/Resources")] = page["/Resources"]
    form[NameObject("/BBox")] = ArrayObject([NumberObject(n) for n in (0, 0, 612, 792)])
    nested = DecodedStreamObject()
    nested.set_data(b"/TextForm Do")
    nested[NameObject("/Subtype")] = NameObject("/Form")
    nested[NameObject("/BBox")] = form["/BBox"]
    nested[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/TextForm"): writer._add_object(form)})
    })
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/XObject"): DictionaryObject({NameObject("/Nested"): writer._add_object(nested)})
    })
    contents = DecodedStreamObject()
    contents.set_data(b"/Nested Do")
    page[NameObject("/Contents")] = contents
    output = io.BytesIO()
    writer.write(output)
    raw = output.getvalue()
    pages = parse_pdf_document(PDFDocumentInput(document_id="nested-form", content=raw))
    assert len(pages) == 2 and "Revenue 2025 1,234.56" in pages[0].text
    encoded = zlib.compress(original)
    assert encoded in raw
    damaged = raw.replace(encoded, encoded[:-4] + b"\x00\x00\x00\x00", 1)
    with pytest.raises(ValueError):
        parse_pdf_document(PDFDocumentInput(document_id="nested-form", content=damaged))


def test_small_horizontal_kerning_preserves_complete_words_and_table_numbers() -> None:
    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(io.BytesIO(_document())))
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 50 700 Td [(regula) -13 (tory) -300 (assets)] TJ 0 -20 Td (2025 100 2024 90) Tj ET")
    writer.pages[0][NameObject("/Contents")] = stream
    output = io.BytesIO()
    writer.write(output)
    raw = output.getvalue()
    pages = parse_pdf_document(PDFDocumentInput(document_id="kerning", content=raw))
    assert re.findall(r"[a-z]+|\d+", pages[0].text.lower()) == ["regulatory", "assets", "2025", "100", "2024", "90"]
    assert len(pages) == 2 and pages[1].text == ""
    assert pages[0].document_sha256 == hashlib.sha256(raw).hexdigest()


def test_exact_glyph_overprinting_does_not_duplicate_words_or_remove_real_repetitions() -> None:
    writer = PdfWriter()
    writer.clone_document_from_reader(PdfReader(io.BytesIO(_document())))
    operations = [b"BT /F1 12 Tf"]
    widths = {"R": 722, "e": 556, "v": 500, "n": 556, "u": 556}
    for _ in range(2):
        position = 50.0
        for character in "Revenue":
            operations.append(f"1 0 0 1 {position:.3f} 700 Tm ({character}) Tj".encode())
            position += widths[character] * 12 / 1000
    operations.append(b"1 0 0 1 50 680 Tm (1) Tj (1) Tj ET")
    stream = DecodedStreamObject()
    stream.set_data(b" ".join(operations))
    writer.pages[0][NameObject("/Contents")] = stream
    output = io.BytesIO()
    writer.write(output)
    pages = parse_pdf_document(PDFDocumentInput(document_id="overprint", content=output.getvalue()))
    assert re.findall(r"[a-z]+|\d+", pages[0].text.lower()) == ["revenue", "11"]
