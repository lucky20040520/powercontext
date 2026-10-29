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

Text extraction starts with pypdf's default mode. It measures text length,
non-whitespace characters, abnormal short words, isolated letters and repeated
text. Repeated line breaks next to abnormal short fragments also indicate risk,
even when a table's numeric content dilutes their overall proportion. On sparse
pages, supported CID positions and widths can independently confirm a split word
before trying layout. A local abnormal short fragment beside a line break can
also trigger this coordinate check without meeting a page-wide ratio. Geometry
uses explicitly mapped ASCII or nonbreaking-space advances and preserves those
Unicode word separators; annotation strings never decide whether to remove them.
Improvements compare fragment counts over the conserved
character inventory; a smaller word denominator cannot penalize successful joins.
The candidate must preserve every non-whitespace character and avoid increased
repeated-text risk. When complete horizontal Identity-H geometry is available,
its numeric multiset certifies boundaries, including uniquely located whitespace
splits. Otherwise existing multi-digit numeric anchors remain protected.
If layout inserts a nearby footnote inside a number, the complete coordinate
candidate may be used under the same conservation and improvement checks.
Unsupported geometry disables this additional evidence, not extraction. Empty,
incomplete or unverified candidates retain the default result. These guards do
not establish perfect reading order or disambiguate every numeric fragment.

For Identity-H fonts with NUL Unicode mappings, the parser can recover a character
from the PDF's own single-glyph `ActualText` spans. Every occurrence of that code
on the page must have the same explicit replacement; conflicting, uncovered,
nested or unsupported spans are retained unchanged. Pages containing Forms are
excluded from this repair, as are graphics-state font overrides. Alphabetic presentation ligatures expand to their
Unicode letter sequences. Exact duplicate draws inside one text object are removed
only when font dictionaries, position and text state match and the following
position reset makes removal safe. Text at different positions, sizes or colors
is preserved, including headers, footers and white text. No OCR or answer-based
word reconstruction is performed.

Consecutive spaces and tabs collapse to one space, preserving newlines without
truncation. Extraction errors still fail the complete document.
Existing persisted Sources and Memory entries
are not rewritten, and their citations continue to identify the original versions.
Submitting different text for an existing page identity in the same Scope raises
an identity conflict. Reingest PDFs captured by an older extraction strategy into
a new Scope to preserve the existing versions and citations.

`scripts/pdf_fragment_experiment.py INPUT.pdf OUTPUT_DIR --pages 1 2` runs an
isolated coordinate reconstruction experiment. It records character codes,
original CID widths, positions, gaps, complete text and term-frequency differences
for default, layout and coordinate candidates, including PDF `ActualText` recovery.
It requires horizontal Identity-H fonts and rejects unsupported geometry and Forms.
This experiment uses pypdf internal positioning helpers and is not a production
extraction mode. It reads no reference answers; score comparisons belong in a
separate offline evaluation step.

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
preserves complete page projections up to Memory's 32768 UTF-8 byte entry bound
after NFC normalization and trimming. Longer entries fail Memory validation;
the parser does not truncate their page text. Existing entry hashes and citations
remain unchanged. The collection's configured entry and manifest budgets must
also accommodate every page. Processes reading new long entries must support
the 32 KiB bound; runtimes enforcing 8 KiB cannot read those entries.
It uses the exact snapshot's citations and ranks complete page text with BM25,
financial vocabulary expansion, statement phrases, and document/year hints.
Every active PDF page remains eligible: company or year recognition never removes
another report or revision. A company match supplies a 3x preference and a report
year match supplies a 1.25x preference, bounded to 3.75x together. An absent match
adds no corresponding preference. Original query terms remain available to text
matching, and comparative disclosures in another year's report can be retrieved.

Financial body text with relevant terms and numbers that do not match the year
pattern receives a 1.25x base weight. Statement headings receive structural credit
only with that supporting body evidence. The combined structural bonus cannot
exceed twice the page's weighted lexical and phrase score. A cover sheet with
headings or years alone receives no statement-heading credit. Explicit geography,
region, or segment questions may expand toward general regional vocabulary such
as Europe, EMEA, and APAC. Business-heading credit also requires a regional
expression in the remaining body. Business headings after a long preamble remain
recognizable; regional evidence without a business heading remains searchable.
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

In the official offline 1-CPU, 2-GB container, queries after reopening Runtime
took about 0.30–0.36 seconds on the 503-page public sample and 0.23–0.31 seconds
on the additional 294-page public sample. These measurements characterize those
samples; they do not establish hidden-set performance or a general latency guarantee.

Validation with the competition's fixed offline dependencies:

```sh
make -C competition test-pdf
```

Additional behavior tests live in `tests/test_pdf_pages.py` and
`tests/e2e/test_pdf_page_retrieval.py`.

## Public quality validation

The implementation was evaluated on 2026-10-28 against the complete public PDF and all five published
questions. The reference was restricted to those questions' eight evidence
annotations, covering six distinct physical pages, from
[FinanceBench's fixed public dataset](https://github.com/patronus-ai/financebench/blob/cc39aeb4afdf33909ee1412188bf89035950c2eb/data/financebench_open_source.jsonl).
Answers and explanations were excluded. Dataset licensing remains CC BY-NC 4.0;
the original report retains its respective rights.

Inference used the official offline 1-CPU, 2-GB container with read-only candidate
sources. Annotation files were not mounted in that container. All 503 pages were
ingested into real SQLite Runtime; retrieval ran after closing and reopening
Runtime, and every returned citation was read back through `memory.get`.
An external scorer compared the frozen candidate's outputs with the references.

Both texts were lowercased and tokenized with `[a-z]+|\d+`. Token overlap used
multiset counts, without applying retrieval's inflection normalization. Each
annotation's recall and each annotated page's F1 were checked separately, rather
than admitting failures through an average. Reference page numbers were converted from zero-based numbering
to 1-based physical pages. Recall@20 summed each question's distinct matching
document-page pairs and divided by the sum of distinct reference pages.

| Metric | Required | Observed | Status |
| --- | --- | --- | --- |
| Per-page token counts against platform frozen counts | 90%–110% | Platform reference unavailable | Not verified |
| Per-page token counts against independent Poppler extraction | 90%–110% | 503/503 pages within range | Cross-check passed; not the platform reference |
| Token counts against annotated full-page text | 90%–110% | 6/6 pages within range; ratios 1.0000–1.0139 | Annotated pages passed |
| Evidence-token recall | ≥0.95 per annotation | Minimum 0.9962121212; all 8 annotations passed | Public split passed |
| Annotated full-page token F1 | ≥0.95 per page | Minimum 0.9793459552; all 8 annotation comparisons passed | Public split passed |
| Evidence-page Recall@20 | ≥0.70 for the split | 8/8 = 1.000 | Public split passed |

The independent full-document reference used Poppler `pdftotext 25.02.0` with
`-layout -enc UTF-8`. It cannot establish agreement with the platform's undistributed
frozen counts. All five published questions retrieved all their reference pages.
The withheld split has not been evaluated.

### Additional public regression sample

Two additional complete reports, `VERIZON_2022_10K` (124 pages) and
`WALMART_2020_10K` (170 pages), were ingested into a separate shared scope. They
were selected as the last two companies alphabetically in the same upstream
public dataset, then the last report ID alphabetically for each company, without
selecting by scores. Their four published questions have six evidence annotations
covering five distinct pages. The same offline inference/reference isolation and
per-annotation scoring rules applied.

| Metric | Observed | Status |
| --- | --- | --- |
| Evidence-token recall | Minimum 0.9912663755; all 6 annotations ≥0.95 | Passed |
| Annotated full-page F1 | Minimum 0.9925558313; all 6 comparisons ≥0.95 | Passed |
| Evidence-page Recall@20 | 5/6 = 0.8333333333 | Passed the 0.70 threshold for this sample |
| Independent Poppler token-count cross-check | 294/294 pages within 90%–110% | Passed; not the platform frozen reference |

All 503 public page texts and all 294 additional public page texts matched the
fixed control exactly. Recall@20 remained 1.000 and 0.8333333333 respectively.
One additional question still missed its reference page. This supplementary
public sample does not establish the challenge's withheld-split score. The public
and withheld splits must each satisfy Recall@20 ≥0.70 independently; scores cannot
be pooled to compensate for a failing split.
