# PDF page evidence

Install `powercontext[pdf]` to extract text with pypdf. The parser accepts original
PDF bytes and a nonblank document ID. It returns every physical page in order,
including blank pages, with 1-based page numbers and the SHA-256 of the complete
original file. It supports empty-password permissions and rejects documents that
require a password. Invalid or incompletely readable documents fail with
`ValueError` before any pages are returned. The parser does not perform OCR on
scanned pages.
Flate-encoded page streams are checked for complete compressed data before
pypdf's best-effort decoder can silently recover a damaged stream. This also
applies when Flate follows another encoding filter.
Nested Form XObject text streams receive the same checks, so damaged table or
body text cannot be silently skipped. Resource traversal tracks visited objects
to handle cycles; image payloads are outside the text validation path.

```python
from powercontext.sources.pdf_pages import PDFDocumentInput, parse_pdf_document

pages = parse_pdf_document(PDFDocumentInput(document_id="annual-report", content=pdf_bytes))
```

Register `PDF_PAGE_SOURCE_DEFINITION` in a `SourceDefinitionRegistry`, resolve each
page, and use `project_source_for_transport` to create its observation. Register
the definition manifest with Runtime ingestion, submit all observations to the
chosen scope, and flush its Memory with a pipeline preserving each observation's
complete text and Source reference. The standard `powercontext.text-evidence@1`
projection contains `document_id + "\n" + page.text`. Its metadata contains exactly
`document_id`, `document_sha256`, and `page_number`.

Source identities hash an unambiguous encoding of the document ID, original file
digest, and physical page number. They are bounded to 68 characters and do not
depend on extracted text. A changed PDF produces new page identities; old Sources
and Memory citations retain their original revision. PDF physical pages must not
be confused with printed page labels.

After reopening Runtime, call:

```python
from powercontext.sources.pdf_pages import search_pdf_pages
from powercontext.builtin.runtime import GetMemoryEntryRequest

memory = runtime.memory.for_scope(scope_id)
citations = await search_pdf_pages(memory, "What was operating income in 2025?", limit=20)
for citation in citations:
    record = await memory.get(GetMemoryEntryRequest(citation=citation))
```

Retrieval reads active entries through the public scoped `Memory.list()` API. It
uses the exact snapshot's citations and combines three BM25 rankings: complete
page evidence with statement headings, literal question terms and phrases, and
overlapping 120-token passages. Reciprocal-rank fusion retains bounded confidence
from the statement-aware score. Local passages help retrieve short notes within
long pages without changing the captured text or its page citation.
Financial vocabulary covers accounting paraphrases and supporting lines for
ratios, cash conversion, buybacks, leases, taxes, and capital returns. Inflection
normalization preserves words such as loss and business and handles taxes.
Recognized company names in report IDs select the candidate reports before page
ranking. Corporate suffixes and conjunctions are normalized; initialisms are
derived from multiword report identities without a company lookup table.
An explicit annual-report or 10-K/10-Q year selects matching available reports.
A financial year alone also keeps newer reports that may contain comparative
or restated evidence. If no report year matches, the named company's available
reports remain eligible; this fallback is applied separately to each company.
Without a recognized identity, the whole scope
remains searchable. Business overview headings can supply geographical context
even when the page uses regional names rather than repeating the question terms;
those headings may occur after a long preamble.
It returns at most `limit` distinct page Sources, ignoring unrelated memories and
entries combining multiple Sources. Empty questions and nonpositive limits return
an empty tuple. It uses no models, network, file reads, or persistent search cache.

Each query reads and tokenizes the scoped corpus. Time and transient memory grow
linearly with corpus text size; this is intended for small report collections
such as the challenge's 1,151 pages. Larger deployments should use a bounded index
behind the same citation contract. The public 503-page selftest verifies coverage,
persistence, and citation integrity. Hidden evidence recall and token-quality
thresholds require the evaluator's withheld annotations and are not established
by that selftest.

Validation with the competition's fixed offline dependencies:

```sh
make -C competition test-pdf
```

Additional behavior tests live in `tests/test_pdf_pages.py` and
`tests/e2e/test_pdf_page_retrieval.py`.

## Local validation

Python 3.12 with the competition's pypdf 6.19.0 was used on Windows. The official
503-page public acceptance suite passed all six tests. Parser and real-Runtime
regressions cover persistence, scope isolation, revisions, financial paraphrases,
company identities, distinct pages, and exact citation readback.

Five complete original reports were checked: PepsiCo 2022 (503 pages), 3M 2022
(252), Activision Blizzard 2022 (312), Adobe 2022 (99), and AES 2022 (257).
The additional four are the first four companies alphabetically with a 2022 10-K
in the fixed FinanceBench PDF directory. Selection did not use questions or gold.

Across all 1,423 pages, lowercased `[a-z]+|\d+` multiset token counts were within
90%–110% of independent `pdftotext -layout -enc UTF-8` output; minimum page token
F1 against that output was 0.981132. These are independent extraction checks,
not comparisons with the evaluator's frozen counts or annotated evidence.

All 1,423 observations were ingested into one real SQLite Runtime with the fixed
public evidence pipeline. Duplicate submission remained idempotent. After
closing and reopening Runtime, the five public questions and sixteen generic
financial queries returned 420 exact citations. Every citation was read through
`memory.get`, checked against its original Source, and verified to name a distinct
page from the requested report. Local query times were 0.52–0.72 seconds;
ingestion and flush took 46.2 seconds. This was a local Windows run, not the
official CPU/memory-limited container, and is not a general latency guarantee.

No answers, gold evidence, or evidence-page lists were used in this validation.
Evidence-page Recall@20 on the official public and withheld splits and quality
against the evaluator's frozen reference remain unverified. Passing public
acceptance or these independent checks does not establish the 50-point score.
