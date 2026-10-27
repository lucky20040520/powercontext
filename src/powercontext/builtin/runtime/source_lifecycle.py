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

"""Persistent Scope-local evidence DAGs and transactional availability changes."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.memory import MemoryService
from powercontext.builtin.artifacts.memory.errors import InvalidMemoryCitationError, MemoryEntryNotFoundError
from powercontext.builtin.persistence.codec import dump_model, load_model, stored_bytes
from powercontext.builtin.persistence.errors import RepositoryNotFoundError
from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_NODES_TABLE
from powercontext.builtin.sources import validate_scope_id
from powercontext.builtin.statistics import ModelUsagePurpose
from powercontext.errors import ArtifactNotFoundError
from powercontext.sources import SourceRef

if TYPE_CHECKING:
    from powercontext.builtin.runtime.application import BuiltinRuntime
    from powercontext.builtin.runtime.relational import RelationalContexts


class SourceLifecycleError(ValueError):
    """Invalid registration, unsupported generation, or conflicting event."""


def _require_text(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceLifecycleError("node IDs and reasons must be nonblank strings")  # noqa: TRY003
    return value


class SourceLifecycleEvent(BaseModel):
    """One strictly typed, replayable Source availability event."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    node_id: str
    revision: int = Field(gt=0)
    sequence: int = Field(gt=0)
    available: bool
    reason: str

    _nonblank = field_validator("node_id", "reason")(_require_text)


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    reference: SourceRef | MemoryCitation | ArtifactRef
    parents: tuple[str, ...] = ()
    policy: Literal["all", "any"] = "all"
    revision: int = 1
    available: bool = True
    event: SourceLifecycleEvent | None = None


def _key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _binding_key(reference: SourceRef | MemoryCitation | ArtifactRef) -> str:
    if isinstance(reference, MemoryCitation):
        identity = ("memory", reference.memory_ref.artifact_id, reference.entry_id)
    elif isinstance(reference, SourceRef):
        identity = ("source", reference.source_type, reference.source_id)
    else:
        identity = ("topic", reference.artifact_id)
    return _key(json.dumps(identity, ensure_ascii=False, separators=(",", ":")))


def _propagate(nodes: dict[str, _Node]) -> dict[str, _Node]:
    """Evaluate the entire bounded Scope DAG in O(nodes + edges)."""

    remaining = {key: len(node.parents) for key, node in nodes.items()}
    children: dict[str, list[str]] = {key: [] for key in nodes}
    for key, node in nodes.items():
        for parent in node.parents:
            children[parent].append(key)
    ready = deque(key for key, count in remaining.items() if count == 0)
    evaluated: dict[str, _Node] = {}
    while ready:
        key = ready.popleft()
        node = nodes[key]
        if node.parents:
            supported = (evaluated[parent].available for parent in node.parents)
            node = node.model_copy(update={"available": all(supported) if node.policy == "all" else any(supported)})
        evaluated[key] = node
        for child in children[key]:
            remaining[child] -= 1
            if remaining[child] == 0:
                ready.append(child)
    if len(evaluated) != len(nodes):
        raise SourceLifecycleError("dependency graph contains a cycle")  # noqa: TRY003
    return evaluated


class ScopedSourceLifecycle:
    """Register immutable dependencies and atomically publish availability."""

    def __init__(self, runtime: BuiltinRuntime, contexts: RelationalContexts | None, scope_id: str) -> None:
        self._runtime = runtime
        self._contexts = contexts
        self.scope_id = validate_scope_id(scope_id)

    async def register_source(self, node_id: str, source_ref: SourceRef, *, revision: int = 1) -> None:
        if not isinstance(source_ref, SourceRef) or type(revision) is not int or revision < 1:
            raise SourceLifecycleError("Source registration requires a SourceRef and positive integer revision")  # noqa: TRY003
        await self._register(_Node(node_id=_require_text(node_id), reference=source_ref, revision=revision))

    async def register_memory(
        self, node_id: str, citation: MemoryCitation, *, parents: tuple[str, ...], policy: Literal["all", "any"] = "all"
    ) -> None:
        if not isinstance(citation, MemoryCitation) or citation.memory_ref.family != "memory":
            raise SourceLifecycleError("Memory registration requires a MemoryCitation")  # noqa: TRY003
        await self._register(self._derived(node_id, citation, parents, policy))

    async def register_topic(
        self,
        node_id: str,
        artifact_ref: ArtifactRef,
        *,
        parents: tuple[str, ...],
        policy: Literal["all", "any"] = "all",
    ) -> None:
        if not isinstance(artifact_ref, ArtifactRef) or artifact_ref.family != "topic-memory":
            raise SourceLifecycleError("Topic registration requires a Topic Memory ArtifactRef")  # noqa: TRY003
        await self._register(self._derived(node_id, artifact_ref, parents, policy))

    @staticmethod
    def _derived(node_id, reference, parents, policy) -> _Node:
        _require_text(node_id)
        if (
            not isinstance(parents, (tuple, list))
            or not parents
            or not isinstance(policy, str)
            or policy not in {"all", "any"}
        ):
            raise SourceLifecycleError("derived nodes need parents and an all/any policy")  # noqa: TRY003
        if any(not isinstance(parent, str) or not parent.strip() for parent in parents):
            raise SourceLifecycleError("parent IDs must be nonblank strings")  # noqa: TRY003
        if len(set(parents)) != len(parents) or node_id in parents:
            raise SourceLifecycleError("duplicate parents and self dependencies are forbidden")  # noqa: TRY003
        return _Node(node_id=node_id, reference=reference, parents=tuple(sorted(parents)), policy=policy)

    def _contexts_or_error(self) -> RelationalContexts:
        if self._contexts is None:
            raise SourceLifecycleError("Source lifecycle requires a built-in relational Runtime")  # noqa: TRY003
        return self._contexts

    async def _load(self, connection: AsyncConnection) -> dict[str, _Node]:
        rows = await connection.scalars(
            select(SOURCE_LIFECYCLE_NODES_TABLE.c.payload).where(
                SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == self.scope_id
            )
        )
        nodes = [
            load_model(_Node, stored_bytes(row, column="payload"), kind="source-lifecycle", name=self.scope_id)
            for row in rows
        ]
        return {node.node_id: node for node in nodes}

    async def _register(self, node: _Node) -> None:
        contexts = self._contexts_or_error()
        async with (
            self._runtime._context(self.scope_id, embedding_purpose=ModelUsagePurpose.MEMORY_INDEXING),
            self._runtime._locked(self.scope_id),
            contexts.database.transaction() as conn,
        ):
            nodes = await self._load(conn)
            existing = nodes.get(node.node_id)
            if existing is not None:
                if existing.model_copy(update={"available": True, "event": None}) != node:
                    raise SourceLifecycleError("node ID is already bound differently")  # noqa: TRY003
                return
            if any(parent not in nodes for parent in node.parents):
                raise SourceLifecycleError("parents must be registered first")  # noqa: TRY003
            if any(_binding_key(other.reference) == _binding_key(node.reference) for other in nodes.values()):
                raise SourceLifecycleError("native identity is already bound to another node")  # noqa: TRY003
            services = contexts._services_for(self.scope_id)
            _, catalog = services.sources(conn)
            memory = services.memory(catalog, conn)
            try:
                if isinstance(node.reference, SourceRef):
                    await contexts.repositories.sources.get(conn, self.scope_id, node.reference)
                elif isinstance(node.reference, MemoryCitation):
                    await memory.validate_citation(node.reference)
                else:
                    await contexts.repositories.topic_memories.get_exact(conn, self.scope_id, node.reference)
            except (
                RepositoryNotFoundError,
                ArtifactNotFoundError,
                InvalidMemoryCitationError,
                MemoryEntryNotFoundError,
            ) as error:
                raise SourceLifecycleError("registration reference is not readable in this Scope") from error  # noqa: TRY003
            updated = _propagate({**nodes, node.node_id: node})[node.node_id]
            await self._sync_memory(memory, (updated,), reason="Source lifecycle registration")
            await conn.execute(insert(SOURCE_LIFECYCLE_NODES_TABLE).values(**self._values(updated)))

    def _values(self, node: _Node) -> dict[str, object]:
        return {
            "scope_id": self.scope_id,
            "node_key": _key(node.node_id),
            "binding_key": _binding_key(node.reference),
            "topic_artifact_id": node.reference.artifact_id if isinstance(node.reference, ArtifactRef) else None,
            "available": node.available,
            "payload": dump_model(node, kind="source-lifecycle", name=node.node_id),
        }

    async def apply(self, event: SourceLifecycleEvent) -> list[str]:
        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("apply requires a SourceLifecycleEvent")  # noqa: TRY003
        contexts = self._contexts_or_error()
        async with (
            self._runtime._context(self.scope_id, embedding_purpose=ModelUsagePurpose.MEMORY_INDEXING),
            self._runtime._locked(self.scope_id),
            contexts.database.transaction() as conn,
        ):
            nodes = await self._load(conn)
            source = nodes.get(event.node_id)
            if source is None or not isinstance(source.reference, SourceRef) or source.revision != event.revision:
                raise SourceLifecycleError("unknown Source or mismatched lifecycle revision")  # noqa: TRY003
            if source.event is not None and event.sequence <= source.event.sequence:
                if event != source.event:
                    raise SourceLifecycleError("obsolete or conflicting event sequence")  # noqa: TRY003
                return sorted(key for key, node in nodes.items() if node.available)
            nodes_after = _propagate({
                **nodes,
                event.node_id: source.model_copy(update={"available": event.available, "event": event}),
            })
            changed = tuple(node for key, node in nodes_after.items() if node != nodes[key])
            services = contexts._services_for(self.scope_id)
            _, catalog = services.sources(conn)
            await self._sync_memory(services.memory(catalog, conn), changed, reason=event.reason)
            for node in changed:
                await conn.execute(
                    update(SOURCE_LIFECYCLE_NODES_TABLE)
                    .where(
                        SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == self.scope_id,
                        SOURCE_LIFECYCLE_NODES_TABLE.c.node_key == _key(node.node_id),
                    )
                    .values(**self._values(node))
                )
            return sorted(key for key, node in nodes_after.items() if node.available)

    @staticmethod
    async def _sync_memory(memory: MemoryService, nodes: tuple[_Node, ...], *, reason: str) -> None:
        references = [node for node in nodes if isinstance(node.reference, MemoryCitation)]
        if not references:
            return
        # Group state changes by Memory identity, preserving immutable body versions.
        for artifact_id in sorted({
            node.reference.memory_ref.artifact_id for node in references if isinstance(node.reference, MemoryCitation)
        }):
            current, entries = await memory.head_entries(artifact_id)
            by_id = {entry.entry_id: entry for entry in entries}
            for available in (False, True):
                selected = []
                for node in references:
                    ref = node.reference
                    if (
                        isinstance(ref, MemoryCitation)
                        and ref.memory_ref.artifact_id == artifact_id
                        and node.available == available
                    ):
                        entry = by_id.get(ref.entry_id)
                        if entry is None or entry.entry_version_id != ref.entry_version_id:
                            raise SourceLifecycleError("registered Memory body version has changed")  # noqa: TRY003
                        selected.append(entry)
                if selected:
                    operation = memory.reactivate if available else memory.forget
                    current = await operation(current, entries=selected, reason=reason)

    async def resolve(
        self, node_id: str, *, purpose: Literal["generation", "audit"] = "generation"
    ) -> SourceRef | MemoryCitation | ArtifactRef:
        _require_text(node_id)
        if not isinstance(purpose, str) or purpose not in {"generation", "audit"}:
            raise SourceLifecycleError("unknown resolution purpose")  # noqa: TRY003
        contexts = self._contexts_or_error()
        async with self._runtime._operation(), contexts.database.transaction() as conn:
            payload = await conn.scalar(
                select(SOURCE_LIFECYCLE_NODES_TABLE.c.payload).where(
                    SOURCE_LIFECYCLE_NODES_TABLE.c.scope_id == self.scope_id,
                    SOURCE_LIFECYCLE_NODES_TABLE.c.node_key == _key(node_id),
                )
            )
            node = (
                None
                if payload is None
                else load_model(_Node, stored_bytes(payload, column="payload"), kind="source-lifecycle", name=node_id)
            )
            if node is None or (purpose == "generation" and not node.available):
                raise SourceLifecycleError("unknown or unavailable node")  # noqa: TRY003
            return node.reference


class SourceLifecycleApplication:
    def __init__(self, runtime: BuiltinRuntime, contexts: RelationalContexts | None) -> None:
        self._runtime = runtime
        self._contexts = contexts

    def for_scope(self, scope_id: str) -> ScopedSourceLifecycle:
        return ScopedSourceLifecycle(self._runtime, self._contexts, scope_id)


__all__ = ["SourceLifecycleError", "SourceLifecycleEvent"]
