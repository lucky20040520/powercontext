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
import sqlite3

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import MemoryEntryInput
from powercontext.builtin.inference import EmbeddingResult
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.records import ArtifactWrite
from powercontext.builtin.runtime import (
    BuiltinConfig,
    CaptureSource,
    GetMemoryEntryRequest,
    GetTopicMemoryRequest,
    RememberMemoryRequest,
    SearchMemoryRequest,
    SearchTopicMemoryRequest,
    open_builtin_runtime,
)
from powercontext.builtin.runtime.source_lifecycle import SourceLifecycleError, SourceLifecycleEvent
from powercontext.builtin.scope import ScopeDraft
from powercontext.sources import SourceRef


def _event(available, *, sequence=1, node_id="a"):
    return SourceLifecycleEvent(
        node_id=node_id, revision=7, sequence=sequence, available=available, reason="evidence status"
    )


async def _seed(runtime, key):
    assert runtime.scopes is not None
    scope = (await runtime.scopes.create(ScopeDraft(title=key, summary="Evidence DAG", idempotency_key=key))).scope_id
    service = runtime.lifecycle.for_scope(scope)
    roots = {}
    for name in ("a", "b"):
        receipt = await runtime.sources.for_scope(scope).capture(
            CaptureSource(source_id=name, content=name, metadata={})
        )
        roots[name] = receipt.source_ref
        await service.register_source(name, receipt.source_ref, revision=7)
    refs = {}
    for name, parents, policy in (("all", ("a", "b"), "all"), ("any", ("a", "b"), "any"), ("child", ("all",), "all")):
        saved = await runtime.memory.for_scope(scope).remember(
            RememberMemoryRequest(entries=(MemoryEntryInput(kind="fact", text=f"{name} persistent evidence"),))
        )
        assert saved.entry is not None
        refs[name] = saved.entry.citation
        await service.register_memory(name, refs[name], parents=parents, policy=policy)
    topic = await runtime.records.for_scope(scope).create_artifact(
        "topic-memory",
        ArtifactWrite(content={"title": "traceabletopic", "summary": "supported evidence", "detail": "original body"}),
    )
    reference = ArtifactRef(family="topic-memory", artifact_id=topic.artifact_id, revision=topic.revision)
    await service.register_topic("topic", reference, parents=("child",), policy="all")
    refs["topic"] = reference
    return scope, service, roots, refs


async def _states(runtime, scope):
    page = await runtime.memory.for_scope(scope).list(include_inactive=True)
    return page.memory_ref, {record.entry.text.split()[0]: record.state for record in page.entries}


@pytest.mark.parametrize("failure_stage", ["memory_projection", "lifecycle_commit"])
def test_storage_failure_rolls_back_native_state_and_same_event_retries_after_restart(tmp_path, failure_stage):
    async def scenario():
        database = tmp_path / "lifecycle.db"
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{database}"))
        async with open_builtin_runtime(config) as runtime:
            scope, service, _, references = await _seed(runtime, "failure")
            before_ref, before_states = await _states(runtime, scope)
            with sqlite3.connect(database) as connection:
                if failure_stage == "memory_projection":
                    connection.execute(
                        "CREATE TRIGGER interrupt BEFORE DELETE ON pc_memory_entry_heads BEGIN SELECT RAISE(ABORT, 'controlled failure'); END"
                    )
                else:
                    connection.execute(
                        "CREATE TRIGGER interrupt BEFORE UPDATE ON pc_source_lifecycle_nodes WHEN OLD.topic_artifact_id IS NOT NULL BEGIN SELECT RAISE(ABORT, 'controlled failure'); END"
                    )
            with pytest.raises(DBAPIError):
                await service.apply(_event(False))
            assert await _states(runtime, scope) == (before_ref, before_states)
            assert await service.resolve("child", purpose="generation") == references["child"]
            assert (
                await runtime.topic_memory.for_scope(scope).search(SearchTopicMemoryRequest(query="traceabletopic"))
            ).hits
        with sqlite3.connect(database) as connection:
            connection.execute("DROP TRIGGER interrupt")
        async with open_builtin_runtime(config) as runtime:
            service = runtime.lifecycle.for_scope(scope)
            assert await service.apply(_event(False)) == ["any", "b"]
            changed_ref, states = await _states(runtime, scope)
            assert states == {"all": "inactive", "any": "active", "child": "inactive"}
            assert await service.resolve("child", purpose="audit") == references["child"]
            exact = await runtime.memory.for_scope(scope).get(GetMemoryEntryRequest(citation=references["child"]))
            assert exact.entry.text == "child persistent evidence"
            assert await service.apply(_event(False)) == ["any", "b"]
            assert (await _states(runtime, scope))[0] == changed_ref
            assert await service.apply(_event(True, sequence=2)) == ["a", "all", "any", "b", "child", "topic"]
            assert (await _states(runtime, scope))[1] == before_states
            assert await service.resolve("child", purpose="generation") == references["child"]

    asyncio.run(scenario())


def test_registration_validation_idempotency_and_scope_isolation():
    async def scenario():
        async with open_builtin_runtime(BuiltinConfig(database=SQLiteConfig())) as runtime:
            left, service, roots, refs = await _seed(runtime, "left")
            right, peer, _, _ = await _seed(runtime, "right")
            before = await _states(runtime, left)
            await service.register_source("a", roots["a"], revision=7)
            await service.register_memory("all", refs["all"], parents=("b", "a"), policy="all")
            assert await _states(runtime, left) == before
            for operation in (
                service.register_source("missing", SourceRef(source_type="content", source_id="absent")),
                service.register_source("a", roots["b"], revision=7),
                service.register_memory("alias", refs["all"], parents=("a",)),
                service.register_memory("self", refs["all"], parents=("self",)),
                service.register_memory("unknown-parent", refs["all"], parents=("missing",)),
                service.register_memory("duplicates", refs["all"], parents=("a", "a")),
            ):
                with pytest.raises(SourceLifecycleError):
                    await operation
            await service.apply(_event(False))
            assert (await _states(runtime, right))[1] == {"all": "active", "any": "active", "child": "active"}
            assert await peer.resolve("a", purpose="generation") == roots["a"]
            with pytest.raises(SourceLifecycleError):
                await service.resolve("topic", purpose="generation")
            assert await service.resolve("topic", purpose="audit") == refs["topic"]
            exact_topic = await runtime.topic_memory.for_scope(left).get(GetTopicMemoryRequest(artifact=refs["topic"]))
            assert exact_topic.topic.content.detail == "original body"
            assert await runtime.topic_memory.for_scope(left).browse(limit=100) == ()
            for invalid in (
                SourceLifecycleEvent(node_id="all", revision=7, sequence=2, available=True, reason="not a Source"),
                SourceLifecycleEvent(node_id="a", revision=7, sequence=1, available=False, reason="changed reason"),
            ):
                with pytest.raises(SourceLifecycleError):
                    await service.apply(invalid)

    asyncio.run(scenario())


@pytest.mark.parametrize("with_vectors", [False, True])
def test_withdrawn_topics_cannot_fill_search_candidate_budget(with_vectors):
    from powercontext.builtin.artifacts.memory import EmbeddingProfile

    class Embedding:
        profile = EmbeddingProfile(profile_id="lifecycle-vector", model="offline", dimension=2)

        async def embed(self, texts):
            return EmbeddingResult(vectors=tuple((1.0, 0.0) for _ in texts))

    async def scenario():
        async with open_builtin_runtime(
            BuiltinConfig(database=SQLiteConfig()), embedding_model=Embedding() if with_vectors else None
        ) as runtime:
            scope, service, _, _ = await _seed(runtime, "search-budget")
            for number in range(40):
                topic = await runtime.records.for_scope(scope).create_artifact(
                    "topic-memory", ArtifactWrite(content={"title": "needle", "summary": "needle", "detail": "needle"})
                )
                await service.register_topic(
                    f"bound-{number}",
                    ArtifactRef(family="topic-memory", artifact_id=topic.artifact_id, revision=topic.revision),
                    parents=("a",),
                )
            surviving = await runtime.records.for_scope(scope).create_artifact(
                "topic-memory",
                ArtifactWrite(
                    content={
                        "title": "needle surviving",
                        "summary": "independent evidence",
                        "detail": "needle remains available",
                    }
                ),
            )
            await service.apply(_event(False))
            results = await runtime.topic_memory.for_scope(scope).search(
                SearchTopicMemoryRequest(query="needle", limit=1)
            )
            assert len(results.hits) == 1
            assert results.hits[0].artifact_ref.artifact_id == surviving.artifact_id
            await service.apply(_event(True, sequence=2))
            restored = await runtime.memory.for_scope(scope).search(
                SearchMemoryRequest(query="all", mode="vector" if with_vectors else "fts", limit=10)
            )
            assert any(hit.text == "all persistent evidence" for hit in restored.hits)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "field,value",
    [
        ("node_id", ""),
        ("node_id", " \t"),
        ("node_id", 3),
        ("reason", ""),
        ("reason", "\n"),
        ("reason", None),
        ("revision", True),
        ("revision", 0),
        ("revision", "7"),
        ("revision", 7.0),
        ("sequence", False),
        ("sequence", -1),
        ("sequence", "1"),
        ("sequence", 1.0),
        ("available", 0),
        ("available", "false"),
        ("extra", True),
    ],
)
def test_event_fields_are_strict(field, value):
    values = {"node_id": "a", "revision": 7, "sequence": 1, "available": False, "reason": "withdrawn"}
    values[field] = value
    with pytest.raises(ValidationError):
        SourceLifecycleEvent.model_validate(values)
