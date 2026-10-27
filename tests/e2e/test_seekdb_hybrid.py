# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""Native seekdb regressions with offline synthetic embeddings; no semantic quality claims."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import statistics
import time
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import Engine, event

from powercontext.builtin.artifacts.memory import (
    EmbeddingProfile,
    MemoryEntryInput,
    MemorySearchRequest,
    MemoryService,
)
from powercontext.builtin.artifacts.search import analyze_fts_query
from powercontext.builtin.inference import EmbeddingResult
from powercontext.builtin.persistence.memory import RelationalMemoryBackend
from powercontext.builtin.persistence.memory_index import CompositeMemoryIndex
from powercontext.builtin.persistence.oceanbase.memory_index import OceanBaseMemoryFTSIndex, OceanBaseMemoryVectorIndex
from powercontext.builtin.persistence.seekdb import SeekDBConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts
from powercontext.builtin.tags import MemoryEntryTagTarget, TagFilter

pytest.importorskip("pylibseekdb")

_PROFILE = EmbeddingProfile(
    profile_id="native-hybrid-regression-v1", model="synthetic", dimension=384, distance="l2", normalization="unit"
)


class _DenseEmbedding:
    profile = _PROFILE

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        vectors = []
        for text in texts:
            raw = hashlib.shake_256(text.encode("utf-8")).digest(766)
            vector = [0.95, *(0.04 * (int.from_bytes(raw[i : i + 2], "big") / 65535 - 0.5) for i in range(0, 766, 2))]
            norm = math.sqrt(math.fsum(value * value for value in vector))
            vectors.append(tuple(value / norm for value in vector))
        return EmbeddingResult(vectors=tuple(vectors))


_Statement = tuple[str, tuple[object, ...] | dict[str, object]]


@contextmanager
def _candidate_statements() -> Iterator[list[_Statement]]:
    statements: list[_Statement] = []

    def capture(
        _connection, _cursor, statement, parameters: tuple[object, ...] | dict[str, object], _context, _executemany
    ):
        if "AGAINST" in statement.upper() or "l2_distance" in statement.lower():
            statements.append((statement, parameters))

    event.listen(Engine, "before_cursor_execute", capture)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", capture)


def test_native_hybrid_preserves_same_database_results_at_384_dimensions(tmp_path):
    async def scenario():
        model = _DenseEmbedding()
        latencies = []
        config = BuiltinConfig(database=SeekDBConfig(path=tmp_path / "native"))
        async with open_builtin_contexts(config, embedding_model=model) as contexts:
            frozen_index = CompositeMemoryIndex(OceanBaseMemoryFTSIndex(), OceanBaseMemoryVectorIndex(_PROFILE))
            for scope_index in range(3):
                scope = f"scope-{scope_index}"
                memory = (await contexts.get(scope)).artifacts.memory
                inputs = tuple(
                    MemoryEntryInput(kind="fact", text=f"Topic{index % 20} signal{index % 20} observation {index}.")
                    for index in range(173)
                )
                previous = await memory.remember(memory=None, entries=inputs[:-1], mode="append")
                assert previous is not None
                head = await memory.remember(memory=previous, entries=inputs[-1:], mode="append")
                assert head is not None
                baseline = MemoryService(
                    backend=RelationalMemoryBackend(
                        database=contexts.database,
                        scope_id=scope,
                        artifacts=contexts.repositories.artifacts,
                        index=frozen_index,
                    ),
                    embedding_model=model,
                )
                # A second Memory in the same Scope must not consume the selected artifact's top-k.
                decoy = await baseline.remember(
                    memory=None, entries=(MemoryEntryInput(kind="fact", text="Topic0 signal0 decoy."),), mode="append"
                )
                assert decoy is not None and decoy.artifact_id != head.artifact_id
                entries = {entry.entry_id: entry for entry in await memory.entries(head)}
                for query_index in range(20):
                    query = f"Topic{query_index} signal{query_index}"
                    # Warm both paths, then alternate measurement order against identical stored identities.
                    await memory.search(query, memories=(head,), mode="hybrid", limit=10)
                    await baseline.search(query, memories=(head,), mode="hybrid", limit=10)
                    results = {}
                    services = (("candidate", memory), ("frozen", baseline))
                    for name, service in services if query_index % 2 else reversed(services):
                        with _candidate_statements() as statements:
                            start = time.perf_counter()
                            results[name] = await service.search(query, memories=(head,), mode="hybrid", limit=10)
                            elapsed = (time.perf_counter() - start) * 1000
                        assert len(statements) == (1 if name == "candidate" else 2)
                        if name == "candidate":
                            latencies.append(elapsed)
                    assert results["candidate"].hits == results["frozen"].hits
                    hits = results["candidate"].hits
                    assert len({(h.entry_id, h.entry_version_id) for h in hits}) == len(hits) == 10
                    for hit in hits:
                        exact = entries[hit.entry_id]
                        assert hit.memory_ref == head.as_ref()
                        assert hit.entry_version_id == exact.entry_version_id and hit.text == exact.text
                        assert hit.matched_by and set(hit.matched_by) <= {"fts", "vector"}
                for mode in ("fts", "vector"):
                    actual = await memory.search("Topic0 signal0", memories=(head,), mode=mode, limit=10)
                    frozen = await baseline.search("Topic0 signal0", memories=(head,), mode=mode, limit=10)
                    assert actual.hits == frozen.hits
                repeated = await memory.search("Topic0 signal0", memories=(head,), mode="hybrid", limit=10)
                assert (
                    repeated.hits
                    == (await memory.search("Topic0 signal0", memories=(head,), mode="hybrid", limit=10)).hits
                )

                # Select sparse entries beyond a small top-k; both channels must filter before LIMIT.
                query = "observation"
                (vector,) = (await model.embed((query,))).vectors
                entry_list = list(entries.values())
                embedded = (await model.embed(tuple(entry.text for entry in entry_list))).vectors
                tagged = [
                    pair[0]
                    for pair in sorted(
                        zip(entry_list, embedded, strict=True),
                        key=lambda pair: math.fsum((a - b) ** 2 for a, b in zip(pair[1], vector, strict=True)),
                    )[-2:]
                ]
                labels = ("chosen", "海洋' OR 1=1 --")
                for entry in tagged:
                    target = MemoryEntryTagTarget(artifact_id=head.artifact_id, entry_id=entry.entry_id)
                    empty = await contexts.records.get_tags(scope, target)
                    await contexts.records.replace_tags(scope, target, labels, expected_etag=empty.etag)
                for match in ("all", "any"):
                    request = MemorySearchRequest(
                        query=query,
                        analyzed_query=analyze_fts_query(query),
                        memories=(head.as_ref(),),
                        candidate_limit=1,
                        mode="hybrid",
                        query_vector=vector,
                        embedding_profile=_PROFILE,
                        tag_filter=TagFilter(tags=labels, match=match),
                    )
                    async with contexts.database.transaction() as connection:
                        with _candidate_statements() as statements:
                            channels = await contexts.index.search(connection, scope, request)
                        assert len(statements) == 1
                        assert len(channels.fts) == len(channels.vector) == 1
                        assert all(
                            hit.entry_id in {entry.entry_id for entry in tagged}
                            for hit in (*channels.fts, *channels.vector)
                        )
                        statement, parameters = statements[0]
                        plan = "\n".join(
                            str(row[0])
                            for row in (await connection.exec_driver_sql("EXPLAIN " + statement, parameters)).all()
                        )
                        assert "TEXT RETRIEVAL SCAN" in plan and "VECTOR INDEX" in plan
                excluded = await memory.search(
                    query, memories=(head,), mode="hybrid", tag_filter=TagFilter(tags=("missing",))
                )
                assert excluded.hits == ()
        print(
            json.dumps({
                "scopes": 3,
                "entries_per_scope": 173,
                "queries": len(latencies),
                "embedding": "synthetic-384-unit-l2",
                "p50_latency_ms": statistics.median(latencies),
            })
        )

    asyncio.run(scenario())
