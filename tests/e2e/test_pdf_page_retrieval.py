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
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import (
    BuiltinConfig,
    GetMemoryEntryRequest,
    RememberMemoryRequest,
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
from powercontext.sources.pdf_pages import PDF_PAGE_SOURCE_DEFINITION, PDFPageInput, search_pdf_pages
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


def test_explicit_company_and_report_year_exclude_other_report_distractors(tmp_path: Path) -> None:
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
            assert all(text.startswith("NORTH_STAR_2025_10K\n") for text in texts)
            compared = await search_pdf_pages(memory, "Compare North Star's 2025 and 2024 gross margin", limit=20)
            comparison = [
                (await memory.get(GetMemoryEntryRequest(citation=citation))).entry.text for citation in compared
            ]
            assert {text.split("\n", 1)[0] for text in comparison} == {"NORTH_STAR_2025_10K", "NORTH_STAR_2024_10K"}
            both = await search_pdf_pages(memory, "Compare North Star and Rival gross margin for 2025", limit=20)
            companies = [(await memory.get(GetMemoryEntryRequest(citation=citation))).entry.text for citation in both]
            assert {text.split("\n", 1)[0] for text in companies} == {"NORTH_STAR_2025_10K", "RIVAL_2025_10K"}

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
    [
        ("3M_2025_10K", "3M"),
        ("COCA_COLA_2025_10K", "CocaCola"),
        ("ACME_INC_2025_10K", "Acme"),
        ("NORTH_STAR_HOLDINGS_CORPORATION_2025_10K", "North Star"),
        ("NORTH_AND_SOUTH_2025_10K", "North & South"),
        ("NORTHERN_SCIENTIFIC_INSTRUMENTS_2025_10K", "NSI"),
    ],
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
            assert all(text.startswith(document + "\n") for text in texts)
            # With no document identity in the question, search the entire scope.
            general = await search_pdf_pages(memory, "What is the reported revenue?", limit=20)
            identities = {
                (await memory.get(GetMemoryEntryRequest(citation=citation))).entry.text.split("\n", 1)[0]
                for citation in general
            }
            assert identities == {document, "X3M_2025_10K"}

    asyncio.run(run())


@pytest.mark.parametrize(
    ("question", "evidence"),
    [
        (
            "How much did North Star spend on share buybacks?",
            "Treasury stock\nCommon shares repurchased during the year cost 250.",
        ),
        (
            "How much does North Star owe its suppliers?",
            "Consolidated Balance Sheets\nAccounts payable 123.",
        ),
        (
            "What is North Star effective tax rate?",
            "Income taxes\nProvision for income taxes 100\nIncome before income taxes 400.",
        ),
        (
            "What were North Star operating lease payments?",
            "Lease commitments\nRent expense 90\nFuture minimum rental obligations 100.",
        ),
    ],
    ids=["buybacks", "supplier-liabilities", "tax-rate", "lease-payments"],
)
def test_financial_paraphrases_recall_evidence_amid_literal_mentions(
    tmp_path: Path, question: str, evidence: str
) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'paraphrases.db'}"))
    # Index and agenda mentions repeat the question's vocabulary but provide
    # none of its financial evidence. They must not fill every retrieval slot.
    boilerplate = f"North Star annual report 2025\n{question}\nIndex reference only.\n" * 8
    pages = [("NORTH_STAR_2025_10K", f"Agenda {index}\n{boilerplate}") for index in range(25)]
    pages.append(("NORTH_STAR_2025_10K", evidence))

    async def run() -> None:
        scope_id = await _capture_pages(config, pages)
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            citations = await search_pdf_pages(memory, question, limit=20)
            assert 0 < len(citations) <= 20
            entries = [(await memory.get(GetMemoryEntryRequest(citation=item))).entry for item in citations]
            assert len({entry.sources[0].source_id for entry in entries}) == len(entries)
            assert any(entry.text == f"NORTH_STAR_2025_10K\n{evidence}" for entry in entries)

    asyncio.run(run())


def test_financial_year_does_not_exclude_comparative_evidence_in_newer_report(tmp_path: Path) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'comparatives.db'}"))
    pages = [
        ("ACME_2024_10K", "Revenue 2024. See segment disclosures in subsequent filings."),
        (
            "ACME_2025_10K",
            "Segment revenue\nComparative 2024 segment revenue was restated after the reorganization. "
            "Industrial segment 800; services segment 200.",
        ),
    ]

    async def run() -> None:
        scope_id = await _capture_pages(config, pages)
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            citations = await search_pdf_pages(memory, "What was ACME's segment revenue in FY2024?", limit=20)
            texts = [(await memory.get(GetMemoryEntryRequest(citation=item))).entry.text for item in citations]
            assert any("Industrial segment 800" in text for text in texts)
            # An explicit report identity still restricts the document revision.
            citations = await search_pdf_pages(memory, "What revenue appears in ACME's 2024 annual report?", limit=20)
            texts = [(await memory.get(GetMemoryEntryRequest(citation=item))).entry.text for item in citations]
            assert texts and all(text.startswith("ACME_2024_10K\n") for text in texts)

    asyncio.run(run())


def test_comparison_keeps_each_named_company_when_one_lacks_matching_report_year(tmp_path: Path) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'comparison.db'}"))
    pages = [
        ("ACME_2025_10K", "Revenue 2025 100, with a comparative 2024 revenue of 90."),
        ("RIVAL_2024_10K", "Revenue 2024 200."),
    ]

    async def run() -> None:
        scope_id = await _capture_pages(config, pages)
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            citations = await search_pdf_pages(memory, "Compare ACME and Rival revenue in FY2025", limit=20)
            documents = {
                (await memory.get(GetMemoryEntryRequest(citation=item))).entry.text.split("\n", 1)[0]
                for item in citations
            }
            assert documents == {"ACME_2025_10K", "RIVAL_2024_10K"}

    asyncio.run(run())


@pytest.mark.parametrize(
    ("question", "discussion", "evidence"),
    [
        (
            "What was Orion cash ratio in 2025?",
            "Cash management supports our liquidity ratio objectives. "
            "We discuss cash and liquidity policies, financing and future investment plans.",
            (
                "Consolidated Balance Sheets\n2025 Cash and cash equivalents 500.",
                "Consolidated Balance Sheets\n2025 Total current liabilities 250.",
            ),
        ),
        (
            "What was Orion net debt in 2025?",
            "Debt maturity and net borrowing objectives remain under review. "
            "We discuss debt management and financing policies.",
            (
                "Consolidated Balance Sheets\n2025 Total debt 900.",
                "Consolidated Balance Sheets\n2025 Cash and cash equivalents 300.",
            ),
        ),
        (
            "What was Orion ROA in 2025?",
            "ROA is one of our performance indicators. Our 2025 performance and future investment are under review.",
            (
                "Consolidated Statements of Operations\n2025 Net income 80.",
                "Consolidated Balance Sheets\n2025 Total assets 1000.",
            ),
        ),
        (
            "What was Orion net profit in 2025?",
            "Net income is subject to estimates. Profit expectations are uncertain and may change.",
            ("Financial results\n2025 Net proﬁt 17.",),
        ),
        (
            "What were Orion restructuring costs in 2025?",
            "Restructuring costs are subject to estimates and plans may change in future periods.",
            ("2025 Restructur-\ning costs 17.",),
        ),
        (
            "Is Orion a capital-intensive business based on FY2025 data?",
            "Capital allocation remains an important part of our long-term business strategy. " * 8,
            (
                "Consolidated Statements of Income\n2025 Net sales 1000 Operating expenses 800.",
                "Consolidated Balance Sheets\n2025 Property, plant and equipment, net 250.",
                "Consolidated Statements of Cash Flows\n2025 Purchases of property, plant and equipment 80.",
            ),
        ),
        (
            "If we exclude M&A, which segment dragged down Orion's growth in 2025?",
            "Acquisition and divestiture activity remain under review. " * 8,
            (
                "Worldwide Sales Change by Business Segment\n"
                "Organic sales 1%; Acquisitions 0%; Divestitures (2%); Translation (4%); Total sales change (5%).",
            ),
        ),
        (
            "Do any product or service categories represent more than 20% of Orion revenue in 2025?",
            "Product and service categories are discussed throughout our business review. " * 8,
            (
                "Summary of Business Segment Data\n"
                "Revenues: Commercial Systems 30, Government Services 25, Total revenues 100.",
            ),
        ),
        (
            "Who are Orion's primary customers in 2025?",
            "Our customers support demand for products and services across several markets. " * 8,
            (
                "We derive a significant portion of revenue from commercial airlines.",
                "We derive a substantial portion of revenue from the U.S. government and Department of Defense.",
                "In 2025, 40% of revenues were earned under U.S. government contracts.",
            ),
        ),
        (
            "Is Orion's business subject to cyclicality?",
            "Economic conditions may affect demand, financing and future investment. " * 8,
            ("Historically, the airline industry has been cyclical and highly competitive.",),
        ),
    ],
    ids=[
        "cash-ratio-components",
        "net-debt-components",
        "ratio-acronym",
        "pdf-ligature",
        "pdf-line-wrap",
        "capital-intensive",
        "m-and-a-segment-growth",
        "product-category-revenue",
        "primary-customers",
        "cyclicality",
    ],
)
def test_supporting_pages_survive_discussion_distractors_after_restart(
    tmp_path: Path, question: str, discussion: str, evidence: tuple[str, ...]
) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'support.db'}"))
    document = "ORION_2025_10K"
    pages = [(document, f"Discussion {number}\n2025 {discussion}\n" * 8) for number in range(30)]
    pages.extend((document, text) for text in evidence)

    async def run() -> None:
        scope_id = await _capture_pages(config, pages)
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            citations = await search_pdf_pages(memory, question, limit=20)
            assert len(citations) <= 20
            restored = [(await memory.get(GetMemoryEntryRequest(citation=item))).entry for item in citations]
            assert {f"{document}\n{text}" for text in evidence} <= {entry.text for entry in restored}
            assert len({entry.sources[0].source_id for entry in restored}) == len(restored)

    asyncio.run(run())


@pytest.mark.parametrize(
    "text,topic", [("Proﬁtability 17.", "profitability"), ("Restructur-\ning 17.", "restructuring")]
)
def test_pdf_search_normalizes_typography_without_rewriting_captured_text(
    tmp_path: Path, text: str, topic: str
) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'typography.db'}"))

    async def run() -> None:
        scope_id = await _capture_pages(config, [("ORION_2025_10K", text)])
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            citations = await search_pdf_pages(memory, f"What does Orion say about {topic}?", limit=1)
            assert len(citations) == 1
            entry = await memory.get(GetMemoryEntryRequest(citation=citations[0]))
            assert entry.entry.text == f"ORION_2025_10K\n{text}"

    asyncio.run(run())


@pytest.mark.parametrize(
    ("question", "mention", "evidence"),
    [
        (
            "What countries does Orion operate in as of 2025?",
            "countries",
            "Net revenue by country\nUnited States 100 Germany 40 Japan 30.",
        ),
        (
            "What was Orion research and development expense in 2025?",
            "research development",
            "Consolidated Statements of Operations\nResearch and development 120.\n"
            + "Sales 1000 Interest 10 Taxes 20 " * 40,
        ),
    ],
    ids=["country-disclosure", "research-expense"],
)
def test_report_selectors_do_not_crowd_out_evidence_in_distinct_sections(
    tmp_path: Path, question: str, mention: str, evidence: str
) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'selectors.db'}"))
    # Different sections have independent vocabularies, so duplicate-page
    # diversification cannot compensate for ranking the company/year as evidence.
    pages = []
    for number in range(30):
        vocabulary = " ".join(f"topic{chr(97 + number)}{chr(97 + word)}" for word in range(26))
        pages.append(("ORION_2025_10K", f"Orion 2025 {mention} " + (vocabulary + " ") * 10))
    pages.append(("ORION_2025_10K", evidence))

    async def run() -> None:
        scope_id = await _capture_pages(config, pages)
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            citations = await search_pdf_pages(memory, question, limit=20)
            assert 0 < len(citations) <= 20
            restored = [(await memory.get(GetMemoryEntryRequest(citation=item))).entry for item in citations]
            assert any(entry.text == f"ORION_2025_10K\n{evidence}".strip() for entry in restored)
            assert len({entry.sources[0].source_id for entry in restored}) == len(restored)

    asyncio.run(run())


@pytest.mark.parametrize(
    ("question", "discussion", "evidence"),
    [
        (
            "What fraction of Orion revenue came from the US and the UK in 2025?",
            "Revenue in the US and UK depends on economic conditions and our business strategy.",
            "Geographic information\nU.S. revenue 50%; U.K. revenue 20%.",
        ),
        (
            "When do Orion rental commitments fall due after 2025?",
            "Rental commitments fall due under agreements. Our rental commitments depend on future business needs.",
            "Lease liability maturities\n2026 100 2027 90 2028 80 2029 70 2030 60 Thereafter 50.\n"
            + "Right-of-use assets 90 Finance leases 20 Operating leases 70 " * 12,
        ),
        (
            "Who were Orion largest customers in 2025?",
            "Our largest customers support our business and our largest customers influence our distribution strategy.",
            "Customers exceeding 10% of net revenue: Distributor Alpha 22%; Distributor Beta 15%.\n"
            + "Product development costs 50 Software development costs 60 " * 20,
        ),
        (
            "How were Orion pension funds invested between shares and bonds in 2025?",
            "Pension funds are invested between shares and bonds. We regularly review pension funds invested in shares.",
            "Pension plan asset allocation\nEquity securities 30% Debt securities 70%.",
        ),
    ],
    ids=["dotted-initialisms", "lease-maturities", "customer-concentration", "pension-allocation"],
)
def test_disclosure_evidence_survives_distinct_narrative_sections(
    tmp_path: Path, question: str, discussion: str, evidence: str
) -> None:
    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'disclosures.db'}"))
    pages = []
    for number in range(30):
        vocabulary = " ".join(f"section{chr(97 + number)}{chr(97 + word)}" for word in range(26))
        pages.append(("ORION_2025_10K", discussion + " " + (vocabulary + " ") * 10))
    pages.append(("ORION_2025_10K", evidence))

    async def run() -> None:
        scope_id = await _capture_pages(config, pages)
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            citations = await search_pdf_pages(memory, question, limit=20)
            assert 0 < len(citations) <= 20
            restored = [(await memory.get(GetMemoryEntryRequest(citation=item))).entry for item in citations]
            assert any(entry.text == f"ORION_2025_10K\n{evidence}".strip() for entry in restored)
            assert len({entry.sources[0].source_id for entry in restored}) == len(restored)

    asyncio.run(run())


@pytest.mark.parametrize(
    "paragraph", ["Revenue and assets 123. " * 600, "财报正文与数字123。" * 1000], ids=["ascii", "utf8"]
)
def test_complete_dense_page_exceeding_eight_kib_survives_capture_and_restart(tmp_path: Path, paragraph: str) -> None:
    from powercontext.builtin.artifacts.memory.errors import InvalidMemoryCandidateError

    config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'dense.db'}"))
    text = paragraph + "\nFinal disclosure: unusual warranty obligation 987654321."
    assert len(text.encode("utf-8")) > 8192

    async def run() -> None:
        scope_id = await _capture_pages(config, [("ORION_2025_10K", text)])
        async with open_builtin_runtime(config) as runtime:
            memory = runtime.memory.for_scope(scope_id)
            citations = await search_pdf_pages(memory, "What unusual warranty obligation did Orion disclose?", limit=20)
            assert len(citations) == 1
            record = await memory.get(GetMemoryEntryRequest(citation=citations[0]))
            assert record.entry.text == f"ORION_2025_10K\n{text}"
            assert record.entry.sources[0].source_type == "pdf-page"
            # Ordinary, unbacked memories retain their documented 8 KiB bound.
            with pytest.raises(InvalidMemoryCandidateError, match="8192 UTF-8 bytes"):
                await memory.remember(RememberMemoryRequest(entries=(MemoryEntryInput(kind="note", text=text),)))
            with pytest.raises(InvalidMemoryCandidateError, match="8192 UTF-8 bytes"):
                await memory.remember(
                    RememberMemoryRequest(entries=(MemoryEntryInput(kind="note", text=text, entry=record.entry),))
                )
        async with open_builtin_runtime(config) as runtime:
            restored = await runtime.memory.for_scope(scope_id).get(GetMemoryEntryRequest(citation=citations[0]))
            assert restored.citation == citations[0]
            assert restored.entry.text == f"ORION_2025_10K\n{text}"

    asyncio.run(run())
