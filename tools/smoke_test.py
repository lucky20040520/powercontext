"""Smoke test for pdf_pages: parse, registry, projection, revisions, edge inputs."""
import asyncio
import io
from pathlib import Path

from pypdf import PdfWriter

from powercontext.sources import SourceDefinitionRegistry, project_source_for_transport
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    parse_pdf_document,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY

PDF = Path(
    r"C:\Users\wh-yin\Doubao\chats\2026-10-28\new-chat-1\powercontext-eval\competition\challenges\source-03-pdf-retrieval\workload\public\pdfs\PEPSICO_2022_10K.pdf"
)

async def main() -> None:
    raw = PDF.read_bytes()
    pages = parse_pdf_document(PDFDocumentInput(document_id="PEPSICO_2022_10K", content=raw))
    print("pages:", len(pages), "first:", pages[0].page_number, "last:", pages[-1].page_number)
    print("sha256 ok:", pages[0].document_sha256 == "7d8a9f3374e429c58f101319e2da8a0e601a89859e1e4f6854163dd5f8ce6b47")
    print("text non-empty count:", sum(1 for p in pages if p.text.strip()))
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    source = await registry.resolve(pages[0])
    print("source name:", source.name, "len:", len(source.name))
    print("read roundtrip:", await registry.read(source) == pages[0])
    observation = project_source_for_transport(registry, source)
    proj = observation.projection(TEXT_EVIDENCE_PROJECTION_KEY)
    print("projection keys:", sorted(proj.keys()))
    print("projection meta:", proj["metadata"])
    print("projection content head:", proj["content"][:80].replace("\n", "\\n"))

    # blank pages + revision identity
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=200)
    writer.add_blank_page(width=100, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    original = parse_pdf_document(PDFDocumentInput(document_id="control", content=buf.getvalue()))
    print("blank pages:", [(p.page_number, p.text) for p in original])
    writer.add_metadata({"/Title": "New revision"})
    buf = io.BytesIO()
    writer.write(buf)
    updated = parse_pdf_document(PDFDocumentInput(document_id="control", content=buf.getvalue()))
    print("revised sha differs:", updated[0].document_sha256 != original[0].document_sha256)
    print("revised name differs:", (await registry.resolve(original[0])).name != (await registry.resolve(updated[0])).name)

    # empty password marker
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=200)
    writer.encrypt(user_password="", owner_password="owner")
    buf = io.BytesIO()
    writer.write(buf)
    pages_enc = parse_pdf_document(PDFDocumentInput(document_id="permissions", content=buf.getvalue()))
    print("encrypted readable:", len(pages_enc) == 1 and pages_enc[0].page_number == 1)

    # corrupt inputs
    for label, raw_bytes in [("empty", b""), ("notpdf", b"not a PDF"), ("trunc", b"%PDF-1.7\ntruncated")]:
        try:
            parse_pdf_document(PDFDocumentInput(document_id="invalid", content=raw_bytes))
            print(label, ": NO ERROR (bad)")
        except ValueError as error:
            print(label, ": ValueError ok")

asyncio.run(main())
