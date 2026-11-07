# PDF page evidence

Install `powercontext[pdf]` to extract complete physical pages with pypdf. The
parser accepts original PDF bytes and a nonblank document ID. It returns all
pages in order, including blanks, with 1-based page numbers and the SHA-256 of
the entire original file. Empty-password permissions are supported; documents
requiring a password are rejected. Invalid or incompletely readable documents
fail atomically with `ValueError`. Scanned images are not processed with OCR.
Flate data in page content and nested Form XObjects is checked before the
extractor can silently recover a damaged text stream.

```python
from powercontext.sources.pdf_pages import PDFDocumentInput, parse_pdf_document

pages = parse_pdf_document(PDFDocumentInput(document_id="annual-report", content=pdf_bytes))
```

Register `PDF_PAGE_SOURCE_DEFINITION` in `SourceDefinitionRegistry`, resolve each
page, and use `project_source_for_transport` to create its observation. Register
the definition manifest with Runtime ingestion, submit all observations to the
chosen scope, and flush Memory with a pipeline preserving each observation's
complete text and Source reference. The standard `powercontext.text-evidence@1`
projection contains `document_id + "\n" + page.text`. Its metadata contains
exactly `document_id`, `document_sha256`, and `page_number`.

Source identities hash an unambiguous encoding of the document ID, original
file digest, and physical page number. They are bounded to 68 characters and do
not depend on extracted text. A changed PDF produces new page identities; old
Sources and Memory citations retain their original revision. Physical page
numbers must not be confused with printed page labels.

After reopening Runtime, call:

```python
from powercontext.sources.pdf_pages import search_pdf_pages
from powercontext.builtin.runtime import GetMemoryEntryRequest

memory = runtime.memory.for_scope(scope_id)
citations = await search_pdf_pages(memory, "What was operating income in 2025?", limit=20)
for citation in citations:
    record = await memory.get(GetMemoryEntryRequest(citation=citation))
```

Retrieval combines native lexical candidates from public scoped `Memory.search()`
in explicit FTS mode with active pages from `Memory.list()`. Only exact citations
from that snapshot are returned, even if the head changes during the query.
It returns that snapshot's real citations, with at most `limit` distinct page
Sources. Entries combining multiple Sources and unrelated memories are ignored.
Blank questions and nonpositive limits return an empty tuple.

The offline ranker combines page BM25, literal phrases, overlapping 120-token
passages, and financial statement headings. Unicode ligatures, dotted initialisms (such as U.S./US), and soft hyphens
are normalized only in the derived search view. A word split across a line is
joined when its complete form is a query or expansion term; ordinary compound
hyphens retain their word boundaries. Captured page text is never rewritten.

Financial vocabulary expands metrics toward their supporting statement lines,
including cash ratios, net debt, EBITDA margins, ROA, ROE, ROIC, and FCF. A
bounded part of the result window retains the strongest pages for separate
metric components so one discussion cannot crowd out a required denominator or
another statement. The remaining slots use the fused ranking. Near-identical
narrative pages from the same report are downweighted, without removing page
identities. Financial statements, number-heavy tables, and other reports are
protected from that narrative treatment.

Company names are derived from caller-supplied report identities, with corporate
suffix and conjunction normalization and derived multiword initialisms. No
company lookup table is used. An explicit annual-report or 10-K/10-Q year selects
matching available reports. A financial year alone also keeps newer reports
which may contain comparative or restated evidence. Fallback to available
reports is applied separately to each company. Without a recognized identity,
the whole scope remains eligible.

Search uses no models, network, source-file reads, or persistent corpus cache.
Each query reads the scoped Memory snapshot, with work proportional to its text
plus diversification over a bounded candidate pool. This is intended for small
report collections, including the challenge's 1,151 pages, rather than an
unbounded knowledge base.

## Validation

Run the organizer-owned public tests with Python 3.12 and their locked
dependencies:

```sh
make -C competition test-pdf
```

Product behavior tests are in `tests/test_pdf_pages.py` and
`tests/e2e/test_pdf_page_retrieval.py`. They cover atomic parsing, permissions,
revisions, scope isolation, persistence, restart, exact citation readback,
financial paraphrases and acronyms, supporting pages under discussion
distractors, and typography normalization without changing stored evidence.

The `PDF page evidence acceptance` GitHub Actions workflow runs the public and
product PDF tests in the official container. Its compose configuration supplies
one CPU, two GiB of memory, no external network, and read-only product sources.
Container image preparation downloads dependencies before offline execution.

Independent extraction checks used ten complete original 2022 reports: PepsiCo,
3M, Activision Blizzard, Adobe, AES, Apple, Coca-Cola, Johnson & Johnson,
Microsoft, and Walmart. The 2,126 pages were compared with
`pdftotext -layout -enc UTF-8` using lowercased `[a-z]+|\d+` token multisets.
Every page's term count was within 90%–110% of that independent extraction;
minimum whole-page token F1 was 0.981132. These checks use original PDFs and
independent extraction, not the evaluator's frozen counts or annotated evidence.

All 2,126 observations were also submitted to one real SQLite Runtime using the
public evidence pipeline. Duplicate submission remained idempotent. After
restart, 35 public or generic financial questions returned 700 exact citations.
Each was read through `memory.get` and checked against the original document,
complete SHA-256, physical page, and unchanged evidence text. These Windows
checks used the fixed pypdf 6.19.0 environment without the container's resource
limits; their maximum observed search time was 1.875 seconds. Citation integrity
does not measure annotated evidence-page recall.

Passing public acceptance and these checks does not establish the platform's
50-point result. Official evidence-page Recall@20 and annotated-evidence quality
can only be confirmed by the evaluator. Neither runtime parsing nor retrieval
reads answers, gold, evidence-page lists, pre-extracted files, or judging assets.


## Kerning and independent relevance validation

The parser detects a plain-extraction failure around small horizontal advances
inside PDF TJ arrays. It compares the original and coalesced word boundaries and
uses layout extraction only for affected pages when every non-whitespace character
is preserved. Rotated text is included, and layout padding is compacted. Ordinary
pages retain plain extraction. All byte digests, physical page boundaries and Source
identities remain independent of extraction mode.

An independently authored 40-question benchmark is available in
`benchmark/pdf_retrieval`. Before the relevance fixes, its first company group
recalled 14/16 pages and its additional-company group 18/21. After the fixes, local
queries over the reopened 2,126-page Runtime recalled 16/16, 21/21, and 9/9 pages
for the independently annotated public questions. These company groups were
reviewed during development and do not constitute a blind hidden-set evaluation.
The fixes combine a bounded native FTS channel with explicit disclosure components,
geographic headings, customer-percentage relationships and initialism normalization.
Small result limits preserve the primary statement ranking.

The workflow additionally captures fourteen complete original reports (2,853 pages),
checks independent term counts and selected whole-page token F1, then runs the
40-case benchmark in the official offline container. The fixtures and evaluation
script are outside `src/` and never participate in assessed parsing or retrieval.


Complete dense PDF pages may exceed Memory's ordinary 8,192-byte body ceiling.
Only entries backed by exactly one validated `pdf-page` Source use the existing
captured-Source byte budget instead. The same rule applies to write validation,
canonical content hashes and persisted-version rebuilding, so restarting does not
make a long page unreadable. Ordinary entries retain the 8 KiB contract and errors.
The raw page is never truncated or split to fit an ordinary note limit.

A page that only paints one Form is extracted with that Form's own font resources.
Multiple painted objects and additional page text retain the original page path.
Trailing backwards kerning also admits character-preserving layout extraction to
repair words spanning text runs. Latin presentation ligatures expand to their
letters, and page text uses NFC so persistence does not change its projection.
Regression tests cover page fonts and two nested Form canvases.

Densely glyph-wise TJ encoding also admits layout repair, even if joining its
internal kerning leaves plain extraction unchanged. Sparse word-level kerning
retains plain text unless another concrete layout defect is detected.
