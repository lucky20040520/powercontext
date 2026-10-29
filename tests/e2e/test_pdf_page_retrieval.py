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
import io
import subprocess
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    RememberMemoryRequest,
    SubmitSourceObservation,
    open_builtin_contexts,
    open_builtin_runtime,
)
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import (
    SourceDefinitionRegistry,
    SourceObservation,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.pdf_pages import (
    PDF_PAGE_SOURCE_DEFINITION,
    PDFDocumentInput,
    PDFPageInput,
    parse_pdf_document,
    search_pdf_pages,
)
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY

_CAPTURE = """
import asyncio
import sys
from pathlib import Path
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, SubmitSourceObservation, open_builtin_runtime
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceDefinitionRegistry, manifest_for_definition, project_source_for_transport
from powercontext.sources.pdf_pages import PDF_PAGE_SOURCE_DEFINITION, PDFDocumentInput, parse_pdf_document

async def capture():
    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{sys.argv[1]}"))
    async with open_builtin_runtime(config) as runtime:
        scope = await runtime.scopes.create(ScopeDraft(title="Reports", summary="PDFs", idempotency_key="pdfs"))
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        for name, file in zip(("ACME_2025_10K", "ACME_2025_10K", "OTHER_2025_10K"), sys.argv[2:], strict=True):
            for page in parse_pdf_document(PDFDocumentInput(document_id=name, content=Path(file).read_bytes())):
                observation = project_source_for_transport(registry, await registry.resolve(page))
                request = SubmitSourceObservation(scope_id=scope.scope_id, observation=observation)
                await runtime.ingestion.submit(request)
                await runtime.ingestion.submit(request)
        print(scope.scope_id)

asyncio.run(capture())
"""


def _pdf(pages: list[str], revision: str) -> bytes:
    writer = PdfWriter()
    writer.add_metadata({"/Title": revision})
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        if text:
            font = DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
            })
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = stream
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class _PagePipeline:
    async def extract(self, request, /) -> tuple[MemoryEntryInput, ...]:
        return tuple(
            MemoryEntryInput(
                kind=kind, text=source.projection(TEXT_EVIDENCE_PROJECTION_KEY)["content"], sources=(source,)
            )
            for source in request.sources
            for kind in ("pdf-evidence", "duplicate-page")
        )


def test_pdf_evidence_survives_capture_process_and_runtime_restart(tmp_path: Path) -> None:
    texts = [
        "Consolidated statement index",
        "CONSOLIDATED STATEMENTS OF CASH FLOWS\n2025 Depreciation and amortization 42 Capital expenditure 91",
        "CONSOLIDATED STATEMENTS OF INCOME\n2025 Net revenue 810 Operating income 120",
        "Contingencies: the company is defending litigation over a patent",
        "",
        "Discussion of EBITDA, operating income, depreciation, amortization, cash flows and income statement. " * 20,
    ]
    files = [tmp_path / name for name in ("original.pdf", "revised.pdf", "other.pdf")]
    files[0].write_bytes(_pdf(texts, "original"))
    files[1].write_bytes(_pdf(texts, "revision"))
    files[2].write_bytes(_pdf([texts[1] + " EBITDA capex income margin " * 3], "competitor"))
    database = tmp_path / "reports.db"
    captured = subprocess.run(
        [sys.executable, "-c", _CAPTURE, str(database), *(str(file) for file in files)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    scope_id = captured.stdout.strip()
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{database}"))

    async def retrieve() -> None:
        async with open_builtin_contexts(config) as contexts:
            journal = await (await contexts.get(scope_id)).sources.journal.entries()
            assert len(journal) == 13
            observations: dict[str, SourceObservation] = {}
            for item in journal:
                assert isinstance(item.source, SourceObservation)
                observations[item.source_ref.source_id] = item.source

        async with open_builtin_runtime(config, candidate_pipeline=_PagePipeline()) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            for _ in range(14):
                if not (await memory.flush()).processed:
                    break
            else:
                raise AssertionError("PDF ingestion did not drain")  # noqa: TRY003
            await memory.remember(
                RememberMemoryRequest(
                    entries=(
                        MemoryEntryInput(
                            kind="unrelated", text="ACME 2025 EBITDA income depreciation cash flows " * 20
                        ),
                    )
                )
            )

        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            citations = await search_pdf_pages(
                memory, "What is ACME's FY2025 EBITDA using operating income and D&A from cash flows?", limit=4
            )
            assert len(citations) == 4
            locations = []
            for citation in citations:
                entry = (await memory.get(GetMemoryEntryRequest(citation=citation))).entry
                (reference,) = entry.sources
                observation = observations[reference.source_id]
                assert isinstance(observation, SourceObservation)
                page = PDFPageInput.model_validate(observation.payload)
                assert entry.text == f"{page.document_id}\n{page.text}".strip()
                locations.append((page.document_id, page.document_sha256, page.page_number))
            assert len(set(locations)) == 4
            assert {page_number for doc, _, page_number in locations if doc == "ACME_2025_10K"} == {2, 3}
            legal = await search_pdf_pages(memory, "Does ACME have ongoing legal battles?", limit=1)
            assert len(legal) == 1
            entry = (await memory.get(GetMemoryEntryRequest(citation=legal[0]))).entry
            assert "patent" in entry.text
            all_citations = await search_pdf_pages(memory, "cash flow income litigation", limit=100)
            references = [
                (await memory.get(GetMemoryEntryRequest(citation=citation))).entry.sources[0]
                for citation in all_citations
            ]
            assert len({reference.source_id for reference in references}) == len(references)
            assert await search_pdf_pages(memory, "cash", limit=0) == ()
            assert await search_pdf_pages(memory, "cash", limit=-1) == ()
            assert await search_pdf_pages(memory, " \t") == ()
            assert runtime.scopes is not None
            other_scope = await runtime.scopes.create(
                ScopeDraft(title="Empty", summary="Isolated", idempotency_key="empty")
            )
            assert await search_pdf_pages(runtime.memory.for_scope(other_scope.scope_id), "ACME cash") == ()

        async with open_builtin_runtime(config) as runtime:
            restored = await runtime.memory.for_scope(scope_id).get(GetMemoryEntryRequest(citation=citations[0]))
            assert restored.citation == citations[0]

    asyncio.run(retrieve())


async def _capture_pages(config: BuiltinConfig, pages: list[tuple[str, str]]) -> str:
    from powercontext.builtin.runtime import SubmitSourceObservation

    registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
    async with open_builtin_runtime(config, candidate_pipeline=_PagePipeline()) as runtime:
        assert runtime.scopes is not None
        scope = await runtime.scopes.create(ScopeDraft(title="Mixed reports", summary="PDFs", idempotency_key="mixed"))
        await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
        for index, (document, text) in enumerate(pages, 1):
            page = PDFPageInput(document_id=document, document_sha256="a" * 64, page_number=index, text=text)
            observation = project_source_for_transport(registry, await registry.resolve(page))
            await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope.scope_id, observation=observation))
        memory = runtime.memory.for_scope(scope.scope_id)
        for _ in range(len(pages) + 1):
            if not (await memory.flush()).processed:
                break
        else:
            raise AssertionError("PDF ingestion did not drain")  # noqa: TRY003
        return scope.scope_id


def test_complete_long_page_remains_retrievable_after_restart(tmp_path: Path) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'long-page.db'}"))
    body = "Revenue 2025 was 120 million. 财报完整正文。\n" * 240 + "Final debt maturity evidence 987654321."
    expected = "ACME_2025_10K\n" + body
    assert 8192 < len(expected.encode("utf-8")) < 32768

    async def run() -> None:
        scope_id = await _capture_pages(config, [("ACME_2025_10K", body)])
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            citations = await search_pdf_pages(memory, "Acme final debt maturity evidence 987654321", limit=1)
            assert len(citations) == 1
            record = await memory.get(GetMemoryEntryRequest(citation=citations[0]))
            assert record.entry.text == expected
        async with open_builtin_runtime(config) as runtime:
            record = await runtime.memory.for_scope(scope_id).get(GetMemoryEntryRequest(citation=citations[0]))
            assert record.entry.text == expected

    asyncio.run(run())


def test_layout_padding_and_form_fallback_survive_persistence_and_restart(tmp_path: Path) -> None:
    writer = PdfWriter()
    fonts = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
        })
    })
    wide_contents = (
        b"BT /F1 12 Tf "
        + b" ".join(
            f"1 0 0 1 50 {700 - row * 20} Tm (Revenue 2025 1234.56) Tj "
            f"1 0 0 1 250050 {700 - row * 20} Tm (Net income 789) Tj".encode("ascii")
            for row in range(5)
        )
        + b" ET"
    )
    for is_form, contents in (
        (False, wide_contents),
        (True, b"BT /F1 12 Tf 50 700 Td (Final debt maturity evidence 987654321) Tj ET"),
    ):
        page = writer.add_blank_page(width=400_000, height=792)
        stream = DecodedStreamObject()
        stream.set_data(contents)
        if is_form:
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
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    raw = buffer.getvalue()
    reader = PdfReader(io.BytesIO(raw), strict=True)
    assert len(reader.pages[0].extract_text(extraction_mode="layout").encode("utf-8")) > 32768
    assert not reader.pages[1].extract_text(extraction_mode="layout").strip()
    pages = parse_pdf_document(PDFDocumentInput(document_id="ACME_2025_10K", content=raw))
    assert len(pages) == 3 and pages[2].text == ""
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'layout.db'}"))

    async def run() -> None:
        registry = SourceDefinitionRegistry((PDF_PAGE_SOURCE_DEFINITION,))
        observations = [project_source_for_transport(registry, await registry.resolve(page)) for page in pages]
        expected = {
            source.name: f"{page.document_id}\n{page.text}".strip()
            for source, page in zip(observations, pages, strict=True)
        }
        async with open_builtin_runtime(config, candidate_pipeline=_PagePipeline()) as runtime:
            assert runtime.scopes is not None
            scope = await runtime.scopes.create(ScopeDraft(title="Layout", summary="PDFs", idempotency_key="layout"))
            await runtime.ingestion.register(manifest_for_definition(PDF_PAGE_SOURCE_DEFINITION))
            for source in observations:
                request = SubmitSourceObservation(scope_id=scope.scope_id, observation=source)
                await runtime.ingestion.submit(request)
                await runtime.ingestion.submit(request)
            memory = runtime.memory.for_scope(scope.scope_id)
            for _ in range(len(pages) + 1):
                if not (await memory.flush()).processed:
                    break
            else:
                raise AssertionError("PDF ingestion did not drain")  # noqa: TRY003

        async with open_builtin_contexts(config) as contexts:
            journal = await (await contexts.get(scope.scope_id)).sources.journal.entries()
            assert len(journal) == len(pages)
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope.scope_id)
            snapshot = await memory.list()
            assert {row.entry.sources[0].source_id: row.entry.text for row in snapshot.entries} == expected
            citations = await search_pdf_pages(memory, "Revenue net income debt maturity 987654321", limit=20)
            assert len(citations) == 2
            for citation in citations:
                record = await memory.get(GetMemoryEntryRequest(citation=citation))
                assert record.entry.text == expected[record.entry.sources[0].source_id]
        async with open_builtin_runtime(config) as runtime:
            for citation in citations:
                record = await runtime.memory.for_scope(scope.scope_id).get(GetMemoryEntryRequest(citation=citation))
                assert record.citation == citation
                assert record.entry.text == expected[record.entry.sources[0].source_id]

    asyncio.run(run())


def test_report_hints_prioritize_matching_evidence_without_removing_other_reports(tmp_path: Path) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'mixed.db'}"))
    pages = [
        ("NORTH_STAR_2025_10K", "Consolidated Statement of Income\n2025 Revenue 100 Cost of sales 60 Gross profit 40"),
        (
            "NORTH_STAR_2024_10K",
            "Consolidated Statement of Income\n2024 Revenue 900 Cost of sales 300 Gross profit 600",
        ),
        ("RIVAL_2025_10K", "Gross margin North Star gross profit revenue cost of sales 2025 " * 30),
    ]

    async def run() -> None:
        scope_id = await _capture_pages(config, pages)
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            citations = await search_pdf_pages(memory, "What is North Star's FY2025 gross margin?", limit=20)
            assert citations
            texts = [(await memory.get(GetMemoryEntryRequest(citation=citation))).entry.text for citation in citations]
            assert texts[0].startswith("NORTH_STAR_2025_10K\n")
            assert {text.split("\n", 1)[0] for text in texts} == {
                "NORTH_STAR_2025_10K",
                "NORTH_STAR_2024_10K",
                "RIVAL_2025_10K",
            }
            compared = await search_pdf_pages(memory, "Compare North Star's 2025 and 2024 gross margin", limit=20)
            comparison = [
                (await memory.get(GetMemoryEntryRequest(citation=citation))).entry.text for citation in compared
            ]
            assert {text.split("\n", 1)[0] for text in comparison[:2]} == {
                "NORTH_STAR_2025_10K",
                "NORTH_STAR_2024_10K",
            }
            assert any(text.startswith("RIVAL_2025_10K\n") for text in comparison)
            both = await search_pdf_pages(memory, "Compare North Star and Rival gross margin for 2025", limit=20)
            companies = [(await memory.get(GetMemoryEntryRequest(citation=citation))).entry.text for citation in both]
            assert {text.split("\n", 1)[0] for text in companies[:2]} == {"NORTH_STAR_2025_10K", "RIVAL_2025_10K"}

    asyncio.run(run())


@pytest.mark.parametrize(
    "preamble",
    ["", "Forward-looking statements about future performance.\n" * 40],
    ids=["early-heading", "late-heading"],
)
def test_business_overview_with_region_names_can_answer_geography_question(tmp_path: Path, preamble: str) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'regions.db'}"))
    pages = [
        ("NORTH_STAR_2025_10K", preamble + "Our Business\nWe distribute instruments throughout EMEA and APAC."),
        ("NORTH_STAR_2025_10K", "Market risk: currency fluctuations affect international operations."),
        ("RIVAL_2025_10K", "Geographies: North America, Europe, Australia."),
    ]

    async def run() -> None:
        scope_id = await _capture_pages(config, pages)
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            citations = await search_pdf_pages(memory, "What geographies does North Star operate in?", limit=1)
            assert citations
            text = (await memory.get(GetMemoryEntryRequest(citation=citations[0]))).entry.text
            assert "EMEA and APAC" in text

    asyncio.run(run())


@pytest.mark.parametrize(
    ("document", "company"),
    [("3M_2025_10K", "3M"), ("COCA_COLA_2025_10K", "CocaCola"), ("ACME_INC_2025_10K", "Acme")],
)
def test_report_identity_matching_and_fallback_keep_relevant_pages(tmp_path: Path, document: str, company: str) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'identities.db'}"))
    statement = "Consolidated Statement of Income\n2025 Revenue 100 Net income 20"
    pages = [(document, statement), ("X3M_2025_10K", statement)]

    async def run() -> None:
        scope_id = await _capture_pages(config, pages)
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            # No matching 2024 report exists; the company must still be searchable.
            citations = await search_pdf_pages(memory, f"What was {company}'s revenue in 2024?", limit=20)
            assert citations
            texts = [(await memory.get(GetMemoryEntryRequest(citation=citation))).entry.text for citation in citations]
            assert texts[0].startswith(document + "\n")
            assert {text.split("\n", 1)[0] for text in texts} == {document, "X3M_2025_10K"}
            # With no document identity in the question, search the entire scope.
            general = await search_pdf_pages(memory, "What is the reported revenue?", limit=20)
            identities = {
                (await memory.get(GetMemoryEntryRequest(citation=citation))).entry.text.split("\n", 1)[0]
                for citation in general
            }
            assert identities == {document, "X3M_2025_10K"}

    asyncio.run(run())


@pytest.mark.parametrize(
    ("pages", "question", "expected_document"),
    [
        (
            [
                ("TARGET_2025_10K", "Target Corporation financial report. This page is intentionally left blank."),
                (
                    "ACME_2025_10K",
                    "The target operating margin was 18 percent after commissioning the zircon plant.",
                ),
            ],
            "What was the target operating margin after commissioning the zircon plant?",
            "ACME_2025_10K",
        ),
        (
            [
                ("ACME_2025_10K", "Archive index for 2025 financial statements."),
                (
                    "ACME_2026_10K",
                    "Comparative disclosure: in 2025, revenue from the zircon plant was 120 million.",
                ),
            ],
            "What was Acme's revenue from the zircon plant in 2025?",
            "ACME_2026_10K",
        ),
        (
            [
                ("ACME_2025_10K", "Archive index for financial statements."),
                ("BETA_2026_10K", "Revenue from the zircon plant was 120 million."),
            ],
            "What was revenue from the zircon plant?",
            "BETA_2026_10K",
        ),
    ],
    ids=["ambiguous-company-word", "comparative-year", "no-identity"],
)
def test_report_hints_cannot_exclude_the_only_substantive_evidence(
    tmp_path: Path, pages: list[tuple[str, str]], question: str, expected_document: str
) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'hints.db'}"))

    async def run() -> None:
        scope_id = await _capture_pages(config, pages)
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            citations = await search_pdf_pages(memory, question, limit=1)
            assert len(citations) == 1
            record = await memory.get(GetMemoryEntryRequest(citation=citations[0]))
            assert record.entry.text.startswith(expected_document + "\n")
            assert "zircon plant" in record.entry.text

    asyncio.run(run())


@pytest.mark.parametrize(
    "cover_text",
    [
        "The figures are not provided on this cover sheet for 2025.",
        "Catalog reference 42 for 2025. The figures are not provided here.",
    ],
)
def test_statement_headings_alone_cannot_outrank_substantive_financial_evidence(
    tmp_path: Path, cover_text: str
) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'titles.db'}"))
    pages = [
        (
            "ACME_2025_10K",
            "Consolidated Statements of Income\nConsolidated Statements of Cash Flows\n" + cover_text,
        ),
        (
            "ACME_2025_10K",
            "Operating income was 120 million. Depreciation amortization was 30 million.",
        ),
    ]

    async def run() -> None:
        scope_id = await _capture_pages(config, pages)
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            citations = await search_pdf_pages(memory, "Calculate EBITDA for Acme in 2025.", limit=1)
            assert len(citations) == 1
            record = await memory.get(GetMemoryEntryRequest(citation=citations[0]))
            assert "Operating income was 120" in record.entry.text

    asyncio.run(run())


def test_geography_body_evidence_can_outrank_an_empty_business_heading(tmp_path: Path) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'geo-cover.db'}"))
    pages = [
        ("ACME_2025_10K", "Our Business\nThe figures are not provided on this cover sheet."),
        ("ACME_2025_10K", "We operate instrument distribution centers throughout EMEA and APAC."),
    ]

    async def run() -> None:
        scope_id = await _capture_pages(config, pages)
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            citations = await search_pdf_pages(memory, "What geographies does Acme operate in?", limit=1)
            assert len(citations) == 1
            record = await memory.get(GetMemoryEntryRequest(citation=citations[0]))
            assert "EMEA and APAC" in record.entry.text

    asyncio.run(run())
