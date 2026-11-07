# Independent PDF relevance audit

This optional benchmark uses complete original PDFs, independently authored questions,
and physical evidence pages checked against those PDFs. It contains no official
FinanceBench answers or annotated evidence. Product `src/` never imports its files.

The 40 cases cover geographic revenue, inventory accounting, share repurchases,
lease maturities, research spending, pensions, customer concentration, divestitures,
segment investment and financial statement metrics. The first company group and
additional-company group were both reviewed during development; neither is a blind
estimate of the organizer's hidden-set performance. The five public questions have
independently selected evidence pages, which may differ from official annotations.

Eleven complete documents contain 2,352 physical pages. This includes the complete
Pfizer 2015 and PG&E 2018 reports used to reproduce the TJ kerning defect. The
manifest records original-byte SHA-256 digests and independent per-page term counts
from `pdftotext -layout -enc UTF-8`. Eight selected pages also have independent token
multisets for whole-page F1 checks. These references are benchmark fixtures; they
cannot replace PDF parsing and are not available to product code in assessment.

Download preparation is explicit and separate from offline evaluation:

```bash
python benchmark/pdf_retrieval/run.py \
  --cases benchmark/pdf_retrieval/cases.json \
  --pdf-dir .artifacts/pdf-relevance-inputs --download-only

PYTHONPATH=src:competition python benchmark/pdf_retrieval/run.py \
  --cases benchmark/pdf_retrieval/cases.json \
  --pdf-dir .artifacts/pdf-relevance-inputs --minimum-recall 0.95
```

Evaluation parses every original physical page, checks counts and selected-page
F1, and uses the organizer-owned public evidence pipeline to persist the actual
observations. The helper checks retry idempotency and drains ingestion. Retrieval
runs after reopening Runtime and verifies exact citations, original text, report
identity and distinct physical pages before measuring independent Recall@20.

The PDF GitHub workflow performs preparation on the runner and then runs evaluation
in the unchanged official container with one CPU, two GiB, no network and read-only
product sources. The workflow also runs the unmodified public acceptance suite.
Passing this independent benchmark does not establish an official score.

Original financial reports retain their companies' rights. The source collection is
FinanceBench revision `cc39aeb4afdf33909ee1412188bf89035950c2eb`, whose data card
states CC BY-NC 4.0. This benchmark's references were independently derived from
original PDF bytes, not from the FinanceBench answer or evidence files.

Exact single-character overprinting at identical explicitly reset coordinates is
counted once. Repeated text that advances normally is retained.

Dense pages exercise the real Memory storage path above the ordinary 8 KiB note
limit. Parsing logs report the largest UTF-8 page size per document. Single-page
PDF evidence uses the bounded captured-Source budget without truncation; ordinary
Memory entries keep their existing limit. Hashing and restart validation use the
same reference-aware rule.
