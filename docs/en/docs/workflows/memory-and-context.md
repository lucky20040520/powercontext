---
title: Save and recall Memory
description: Save project decisions, retrieve relevant history, and correct outdated Memory.
---

# Save and recall Memory

Memory keeps durable decisions, constraints, and facts. PreparedContext selects relevant history for one request;
it is temporary and does not create another Memory entry.

## Save, recall, and correct

1. Complete the [Quick Start](../get-started/quickstart.md) and keep the resolved Scope consistent across sessions.
2. Explicitly ask the Agent to save the information. A direct `remember_memory` write does not require a model.
3. Search with `search_memory`, or inspect entries with `list_memory_entries` and `get_memory_entry` where the host
   exposes them. Keep the returned citation when referring to a result.
4. Use the current citation to revise incorrect information or retire information that should no longer be recalled.
   Retirement removes it from active recall while preserving history.

Host tool names differ; see [Connect Agents](../integrations/index.md). The
[HTTP API](../develop/http-api.md) exposes the complete request schemas and concurrency requirements.

FTS uses the same query terms for candidate retrieval and admission. Query normalization excludes common English
function words in longer queries and recognizes standalone execution instructions accompanying a question, such as
"Use only supplied context" and "Do not call tools, read files, inspect old sessions, or delegate." Those instructions
cannot supply evidence for an unrelated fact. Explicitly quoted terms remain searchable, including function words
used as identifiers such as `"AND" "OR" precedence`. Domain-specific directives and unrecognized wording remain searchable;
this is a conservative lexical rule, not a general intent classifier. The default threshold requires 25% of all
remaining distinct terms, with a minimum of two matches; one- or two-term queries require one match. Direct search and
prepared context share this rule, including when the optional recall gate relaxes the threshold. Stored text and
vector queries are unchanged, and matching words alone do not establish semantic relevance.

## Withdraw and restore registered evidence

The Python built-in Runtime exposes `runtime.lifecycle.for_scope(scope_id)` for an explicit, immutable dependency DAG.
Bind existing captured `SourceRef` values, readable `MemoryCitation` values, and Topic Memory `ArtifactRef` values:

```python
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleEvent


async def withdraw_evidence(runtime, scope_id, source_ref, citation, topic_ref):
    service = runtime.lifecycle.for_scope(scope_id)
    await service.register_source("source-a", source_ref, revision=3)
    await service.register_memory("memory-a", citation, parents=("source-a",), policy="all")
    await service.register_topic("topic-a", topic_ref, parents=("memory-a",), policy="any")
    return await service.apply(
        SourceLifecycleEvent(node_id="source-a", revision=3, sequence=1, available=False, reason="Source withdrawn")
    )
```

Node IDs are unique within a Scope. An identical registration is idempotent; a different binding conflicts.
Each native Source, logical Memory entry, or Topic identity has one node. Register parents first and supply at least
one distinct parent for a derived node. `all` requires every parent; `any` means any parent independently supports
the entire body. Split independent claims into separate nodes when that assumption does not hold. Registration
immediately applies current parent availability, including when a Source was already withdrawn. Keep one writer per
Scope and do not externally revise registered Memory body versions while the binding is in use.

Events require nonblank string IDs/reasons, strict positive integer revisions/sequences, a strict boolean availability,
and no extra fields. Only Source nodes accept events, and their registered lifecycle revision must match exactly.
Sequences increase per Source. Replaying the most recent identical event is idempotent; older or conflicting events
raise `SourceLifecycleError`. Restore a Source by sending `available=True` with a higher sequence.

Propagation persists the graph, event, and native Memory state transitions in one transaction. Failed native writes
roll back the event and state, so the same event can be retried after fixing the failure or reopening the database.
Successful replay creates no new Memory revision. Memory state changes preserve entry body versions and remove inactive
entries from ordinary search and PreparedContext. Unsupported Topics are filtered from browse, FTS, vector retrieval,
and Context before candidate limits; their stored projections and exact revisions remain available for audit.

`await service.resolve(node_id, purpose="generation")` returns the original reference only while the node is available.
`purpose="audit"` returns the original reference even after withdrawal. Unknown nodes/purposes raise
`SourceLifecycleError`. `apply()` returns every currently available node ID in sorted order, including Sources.
Bindings and status survive reopening the same database and are isolated by Scope.

Graph updates read one Scope's graph and evaluate its nodes and edges in linear time; native Memory publication
retains its existing manifest and index costs. Resolution uses a keyed lookup. Topic eligibility uses an indexed
Scope/Topic status lookup without rewriting historical content. SQLite behavior is covered by native persistence
tests; live OceanBase/seekdb execution requires those external backend tests.

Graph management is a Python Runtime API. Existing HTTP/MCP search and Context surfaces observe the stored states;
there are no new HTTP/MCP graph-management endpoints.

## Automatic context and extraction

Recall hooks ask the Server for bounded PreparedContext. An `empty` result is valid when no relevant information is
available. Returned history does not override current instructions or live project state.

Use [Prepare standard context text](prepare-context-text.md) to choose Memory, Experience, Profile, and Topic Memory
sections, set their order and limits, and configure the total entry limit.

Capturing a prompt creates Source evidence. It does not guarantee Memory extraction. Enable a generation model and
Source processing through [model configuration](../get-started/configure-models.md); configure embeddings only
when [vector or hybrid search](configure-vector-search.md) is needed. Review the host's prompt-capture switch before
recording project input.

Topic Memory has separate processing and retrieval surfaces (`search_topic_memory` and `get_topic_memory` on MCP).
It is not enabled by a basic explicit Memory write; inspect the Topic Memory settings and enabled runtime capabilities
in [Configuration](../operate/configuration.md).

Use [Handoff](memory-and-handoff.md) to transfer the current task boundary, and [Sources](sources.md) to preserve raw evidence.
