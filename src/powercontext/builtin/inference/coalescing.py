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

"""Event-loop-local embedding request sharing and bounded result caching."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from dataclasses import dataclass

from powercontext.builtin.inference.models import EmbeddingResult, EmbeddingVector, InferenceUsage
from powercontext.builtin.inference.protocols import EmbeddingModel, QueryEmbeddingModel, embed_query

_Key = tuple[bool, str]


@dataclass(frozen=True, slots=True)
class _CompletedVector:
    vector: EmbeddingVector
    batch_id: int
    usage: InferenceUsage


class CoalescingEmbeddingModel:
    """Share queued/in-flight text and cache successful vectors within one model.

    Concurrent callers must use the same event loop. Caller cancellation leaves
    shared provider work running. Query-capable providers retain separate query
    and document cache identities; symmetric models share both paths.
    """

    def __init__(
        self,
        model: EmbeddingModel,
        *,
        max_batch_size: int = 64,
        coalesce_ms: float = 5.0,
        cache_size: int = 1024,
    ) -> None:
        if type(max_batch_size) is not int or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")  # noqa: TRY003
        if type(cache_size) is not int or cache_size < 0:
            raise ValueError("cache_size must be a nonnegative integer")  # noqa: TRY003
        if (
            isinstance(coalesce_ms, bool)
            or not isinstance(coalesce_ms, (int, float))
            or not math.isfinite(coalesce_ms)
            or coalesce_ms < 0
        ):
            raise ValueError("coalesce_ms must be finite and nonnegative")  # noqa: TRY003
        self.profile = model.profile
        self._model = model
        self._max_batch_size = max_batch_size
        self._delay = coalesce_ms / 1000
        self._cache_size = cache_size
        self._cache: OrderedDict[_Key, EmbeddingVector] = OrderedDict()
        self._pending: dict[_Key, asyncio.Future[_CompletedVector]] = {}
        self._queued: dict[_Key, asyncio.Future[_CompletedVector]] = {}
        self._dispatch_handle: asyncio.Handle | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._batch_id = 0

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Return document vectors in original order, including duplicates."""

        return await self._embed(texts, query=False)

    async def embed_query(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        """Keep provider-specific query embeddings separate from documents."""

        return await self._embed(texts, query=isinstance(self._model, QueryEmbeddingModel))

    async def _embed(self, texts: tuple[str, ...], *, query: bool) -> EmbeddingResult:
        if isinstance(texts, str) or any(not isinstance(text, str) for text in texts):
            raise TypeError("texts must be a sequence of strings")  # noqa: TRY003
        if not texts:
            return EmbeddingResult(vectors=())
        loop = asyncio.get_running_loop()
        if self._pending and next(iter(self._pending.values())).get_loop() is not loop:
            raise RuntimeError("in-flight embeddings belong to another event loop")  # noqa: TRY003
        cached: dict[_Key, EmbeddingVector] = {}
        waiting: dict[_Key, asyncio.Future[_CompletedVector]] = {}
        keys = tuple((query, text) for text in texts)
        for key in keys:
            if key in self._cache:
                cached[key] = self._cache[key]
                self._cache.move_to_end(key)
            else:
                future = self._pending.get(key)
                if future is None:
                    future = loop.create_future()
                    self._pending[key] = self._queued[key] = future
                waiting[key] = future
        if self._queued and self._dispatch_handle is None:
            # Even a zero window yields to concurrent callers before dispatch.
            self._dispatch_handle = loop.call_later(self._delay, self._dispatch)
        results = await asyncio.gather(*(asyncio.shield(future) for future in waiting.values()))
        usage_by_batch: dict[int, InferenceUsage] = {}
        for key, result in zip(waiting, results, strict=True):
            cached[key] = result.vector
            usage_by_batch[result.batch_id] = result.usage
        usages = tuple(usage_by_batch.values())
        return EmbeddingResult(
            vectors=tuple(cached[key] for key in keys),
            usage=InferenceUsage(
                requests=sum(usage.requests for usage in usages),
                input_tokens=None
                if all(usage.input_tokens is None for usage in usages)
                else sum(usage.input_tokens or 0 for usage in usages),
                output_tokens=None
                if all(usage.output_tokens is None for usage in usages)
                else sum(usage.output_tokens or 0 for usage in usages),
            ),
        )

    def _dispatch(self) -> None:
        queued, self._queued = self._queued, {}
        self._dispatch_handle = None
        for query in (False, True):
            items = tuple((key, future) for key, future in queued.items() if key[0] is query)
            for start in range(0, len(items), self._max_batch_size):
                self._batch_id += 1
                task = asyncio.create_task(
                    self._run_batch(items[start : start + self._max_batch_size], self._batch_id, query=query)
                )
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

    async def _run_batch(
        self,
        items: tuple[tuple[_Key, asyncio.Future[_CompletedVector]], ...],
        batch_id: int,
        *,
        query: bool,
    ) -> None:
        try:
            texts = tuple(key[1] for key, _ in items)
            result = await embed_query(self._model, texts) if query else await self._model.embed(texts)
            if len(result.vectors) != len(items):
                raise ValueError("embedding vector count does not match batch text count")  # noqa: TRY003, TRY301
            usage = result.usage.model_copy(deep=True)
            for (key, future), vector in zip(items, result.vectors, strict=True):
                if self._cache_size:
                    self._cache[key] = vector
                    self._cache.move_to_end(key)
                    while len(self._cache) > self._cache_size:
                        self._cache.popitem(last=False)
                future.set_result(_CompletedVector(vector, batch_id, usage))
        except asyncio.CancelledError:
            for _, future in items:
                future.cancel()
            raise
        except Exception as error:
            for _, future in items:
                future.set_exception(error)
                # Every caller may already have cancelled its shield. Retrieve
                # the private Future's exception without changing await behavior.
                future.exception()
        finally:
            for key, _ in items:
                self._pending.pop(key)


__all__ = ["CoalescingEmbeddingModel"]
