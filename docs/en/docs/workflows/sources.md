---
title: Sources and capture
description: Capture evidence, inspect Source records, and configure processing.
---

# Sources and capture

Sources preserve evidence before it becomes selected knowledge. A Content Source stores captured text; other Source
types can refer to material supplied by a connector. Work Contracts and Task Outcomes also preserve Source evidence.

## Capture and inspect

1. Choose an existing Scope. The [API Quick Start](../develop/api-quickstart.md) demonstrates content capture through
   `POST /v1/sources/content` and retains the returned Source reference.
2. Use `GET /v1/scopes/{scope_id}/sources` to browse the Source journal, then
   `GET /v1/scopes/{scope_id}/sources/{source_type}/{source_id}` to read the selected Source.
3. To process eligible evidence into Memory, configure a generation model and choose scheduled processing, a Source
   count threshold, or an explicit Memory flush. See [Enable extraction and vector search](../get-started/configure-models.md).

A successful capture means evidence was stored; it does not mean extraction succeeded or that the result was worth
keeping. Use Source references to trace a generated result back to its input. Do not retry a capture with changed
content under the same identity as if it were a new observation.

## Choose a capture path

- Agent prompt hooks: use the host-specific capture switch in [Connect Agents](../integrations/index.md).
- Files and object stores: use the [OpenDAL connector](ingest-text-files-with-opendal.md).
- Subject evidence for a Scope profile: follow [Scope profiles](use-profiles.md).
- Application or evaluation events: use the application's adapter; [Bub capture](../integrations/evaluation.md) is opt-in.

Source writes and reads are subject to the selected [Scope and access policy](scopes-and-access.md).

## Process after enough new Sources

Configure independent positive integer thresholds on `RuntimeConfig`:

```python
from powercontext.builtin.runtime import RuntimeConfig

runtime_policy = RuntimeConfig(
    memory_source_count_threshold=3,
    topic_memory_source_count_threshold=5,
    source_window_limit=1,
    topic_memory_source_window_limit=2,
)
```

Both thresholds default to `None` (disabled). Python configuration rejects booleans, strings, floats, zero, and
negative values. For the Server, set decimal integer environment values such as
`POWERCONTEXT_SERVER_RUNTIME_MEMORY_SOURCE_COUNT_THRESHOLD=3` and
`POWERCONTEXT_SERVER_RUNTIME_TOPIC_MEMORY_SOURCE_COUNT_THRESHOLD=5`. A configured generation provider and enabled
processing Family are still required. These settings also govern Sources captured through HTTP and MCP; capture
returns after storage, while generation runs asynchronously.

Counts are local to each Scope and Family: the committed Source journal head minus that Family's last successful
cursor. Repeated capture of an existing identity and receipt trust upgrades do not add entries. Lineage-only Sources
count toward admission but remain excluded from generation evidence. Native supervisors inspect pending metadata in
bounded pages, with a one-second pause between completed passes. This inspection reads no Source bodies and does
not invoke a model; its work scales with the number of dirty Scopes, including those below threshold.

Count and time conditions are independent: either admits work. Explicit Memory or Topic Memory `flush()` also
bypasses the threshold. With a Memory threshold of 3 and `source_window_limit=1`, three new entries admit one window;
the remaining two wait for another entry, a scheduled activation, or an explicit flush. Topic Memory finishes all
windows of an already accepted wave before applying the threshold to its next wave.

Accepted work keeps its existing retry behavior. A failed publication does not advance the successful cursor.
Restarting the same database preserves pending entries and accepted requests, and successful processing retains
the ordinary searchable results and exact Source references. Count inspection does not reset schedule checkpoints.

## Capture CSV rows from Python

Use `powercontext.sources.csv_rows` to capture each CSV record independently. Parsing is offline and uses no model or
network service. Supply the complete UTF-8 bytes, a stable document ID, and the exact primary-key column name:

```python
from powercontext.builtin.runtime import SubmitSourceObservation
from powercontext.sources import (
    SourceDefinitionRegistry,
    manifest_for_definition,
    project_source_for_transport,
)
from powercontext.sources.csv_rows import (
    CSV_ROW_SOURCE_DEFINITION,
    CSVDocumentInput,
    parse_csv_document,
)


async def capture_csv(runtime, scope_id: str, csv_bytes: bytes) -> None:
    rows = parse_csv_document(
        CSVDocumentInput(document_id="airports", primary_key="id", content=csv_bytes)
    )
    registry = SourceDefinitionRegistry((CSV_ROW_SOURCE_DEFINITION,))
    await runtime.ingestion.register(manifest_for_definition(CSV_ROW_SOURCE_DEFINITION))
    for row in rows:
        source = await registry.resolve(row)
        observation = project_source_for_transport(registry, source)
        await runtime.ingestion.submit(SubmitSourceObservation(scope_id=scope_id, observation=observation))
```

`parse_csv_document` validates the entire document before returning a tuple. It accepts an initial UTF-8 BOM, quoted
commas, escaped quotes, and multiline fields. Empty physical records after the header are ignored; a header-only
document returns `()`. Invalid encoding, quoting, headers, row widths, missing or duplicate keys, and oversized Source
identities raise `ValueError`. Parsing failure returns no partial rows; the later Runtime submissions are separate writes.

Header names and field values keep their original strings and order. Column names must be unique and nonblank;
`primary_key` matches a column exactly, including surrounding spaces. The document ID must be nonempty with no
surrounding whitespace. Key values must be nonblank; surrounding key whitespace remains significant.

Each captured Source has type `csv-row`, definition version `1`, and identity
`csv:{encoded document_id}:{encoded primary_key_value}`. Components use `urllib.parse.quote(value, safe="")` and the
complete identity is limited to 256 characters. Reordering records or changing non-key values keeps the logical row ID.
The existing ingestion rules still govern reuse of an already captured identity; this adapter does not add an update API.

The `powercontext.text-evidence` projection contains a compact JSON object in original column order. Its metadata has
exactly `document_id`, `primary_key`, `primary_key_value`, `columns`, and `row`; all CSV values, including empty fields
and numeric strings, remain strings. Registered manifests and submitted observations preserve this evidence across
Runtime restarts. A configured Memory pipeline can consume the projection, and a search hit's exact `MemoryCitation`
can retrieve the corresponding Memory entry and Source reference. CSV parsing and capture do not configure extraction.
