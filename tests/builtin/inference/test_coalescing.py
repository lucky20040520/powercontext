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
import gc
from typing import Any

import pytest

from powercontext.builtin.artifacts.memory import EmbeddingProfile
from powercontext.builtin.inference import (
    CoalescingEmbeddingModel,
    EmbeddingResult,
    InferenceUsage,
    embed_query,
)


class _Embedding:
    profile = EmbeddingProfile(profile_id="coalescing-test", model="offline", dimension=1)

    def __init__(self):
        self.calls: list[tuple[str, ...]] = []

    async def embed(self, texts):
        self.calls.append(texts)
        return EmbeddingResult(
            vectors=tuple((float(ord(text[0])),) for text in texts),
            usage=InferenceUsage(requests=3, input_tokens=11, output_tokens=5),
        )


class _GatedEmbedding(_Embedding):
    def __init__(self):
        super().__init__()
        self.started: asyncio.Queue[tuple[str, ...]] = asyncio.Queue()
        self.release = asyncio.Event()
        self.fail = False

    async def embed(self, texts):
        self.started.put_nowait(texts)
        await self.release.wait()
        if self.fail:
            raise RuntimeError("provider failure")  # noqa: TRY003
        return await super().embed(texts)


@pytest.mark.parametrize(
    "settings",
    [
        {"max_batch_size": 0},
        {"max_batch_size": True},
        {"max_batch_size": 1.5},
        {"cache_size": -1},
        {"cache_size": False},
        {"cache_size": "2"},
        {"coalesce_ms": -1},
        {"coalesce_ms": True},
        {"coalesce_ms": "5"},
        {"coalesce_ms": float("nan")},
        {"coalesce_ms": float("inf")},
    ],
)
def test_invalid_resource_settings_are_rejected(settings):
    with pytest.raises(ValueError):
        CoalescingEmbeddingModel(_Embedding(), **settings)


@pytest.mark.parametrize("cache_size", [0, 2])
@pytest.mark.parametrize("cancel_before_start", [False, True])
def test_late_waiter_reuses_inflight_work_after_another_caller_cancels(cache_size, cancel_before_start):
    async def scenario():
        base = _GatedEmbedding()
        model = CoalescingEmbeddingModel(base, coalesce_ms=20 if cancel_before_start else 0, cache_size=cache_size)
        first = asyncio.create_task(model.embed(("a", "a")))
        if cancel_before_start:
            await asyncio.sleep(0)
        else:
            assert await asyncio.wait_for(base.started.get(), 2) == ("a",)
        late = asyncio.create_task(model.embed(("a",)))
        # The new caller has entered embed before the original caller is cancelled.
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        base.release.set()
        result = await asyncio.wait_for(late, 2)
        assert result.vectors == ((97.0,),)
        assert result.usage == InferenceUsage(requests=3, input_tokens=11, output_tokens=5)
        assert base.calls == [("a",)]
        next_result = await model.embed(("a",))
        assert len(base.calls) == (2 if cache_size == 0 else 1)
        assert next_result.usage.requests == (3 if cache_size == 0 else 0)

    asyncio.run(scenario())


def test_each_waiter_counts_shared_batches_once_and_excludes_cache_hits():
    async def scenario():
        base = _Embedding()
        model = CoalescingEmbeddingModel(base, max_batch_size=2, coalesce_ms=5)
        first, second = await asyncio.gather(model.embed(("a", "b", "c", "a")), model.embed(("b", "c", "d")))
        assert base.calls == [("a", "b"), ("c", "d")]
        assert first.vectors == ((97.0,), (98.0,), (99.0,), (97.0,))
        assert second.vectors == ((98.0,), (99.0,), (100.0,))
        assert first.usage == second.usage == InferenceUsage(requests=6, input_tokens=22, output_tokens=10)
        # Callers own their returned metadata, even though they shared provider work.
        first.usage.requests = 999
        assert second.usage.requests == 6
        mixed = await model.embed(("a", "e", "a", "e"))
        assert mixed.usage == InferenceUsage(requests=3, input_tokens=11, output_tokens=5)
        cached = await model.embed(("a", "e"))
        assert cached.usage.requests == 0

    asyncio.run(scenario())


def test_batch_failure_does_not_block_independent_work_and_failed_text_can_retry():
    async def scenario():
        release = asyncio.Event()

        class PartlyFailing(_Embedding):
            fail = True

            async def embed(self, texts):
                if texts == ("bad",) and self.fail:
                    await release.wait()
                    raise RuntimeError("bad batch")  # noqa: TRY003
                return await super().embed(texts)

        base = PartlyFailing()
        model = CoalescingEmbeddingModel(base, max_batch_size=1, coalesce_ms=0)
        failed = asyncio.create_task(model.embed(("bad",)))
        survivor = asyncio.create_task(model.embed(("good",)))
        assert (await asyncio.wait_for(survivor, 2)).vectors == ((103.0,),)
        release.set()
        with pytest.raises(RuntimeError, match="bad batch"):
            await failed
        assert (await model.embed(("good",))).usage.requests == 0
        # A different provider outcome for the failed identity must be observed.
        base.fail = False
        assert (await model.embed(("bad",))).vectors == ((98.0,),)

    asyncio.run(scenario())


@pytest.mark.parametrize("returned_count", [0, 2])
def test_invalid_count_is_not_partially_cached(returned_count):
    async def scenario():
        class InvalidOnce(_Embedding):
            async def embed(self, texts):
                if not self.calls:
                    self.calls.append(texts)
                    return EmbeddingResult(vectors=((1.0,),) * returned_count)
                return await super().embed(texts)

        base = InvalidOnce()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0)
        with pytest.raises(ValueError):
            await model.embed(("a",))
        assert (await model.embed(("a",))).vectors == ((97.0,),)
        assert base.calls == [("a",), ("a",)]

    asyncio.run(scenario())


def test_all_cancelled_waiters_leave_no_unretrieved_provider_failure():
    async def scenario():
        base = _GatedEmbedding()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0)
        errors: list[dict[str, Any]] = []
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda _loop, context: errors.append(context))
        try:
            callers = [asyncio.create_task(model.embed(("a",))) for _ in range(2)]
            await asyncio.wait_for(base.started.get(), 2)
            for task in callers:
                task.cancel()
            await asyncio.gather(*callers, return_exceptions=True)
            base.fail = True
            base.release.set()
            # Settle the abandoned batch without inspecting wrapper internals.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            gc.collect()
            assert errors == []
            base.fail = False
            assert (await model.embed(("a",))).vectors == ((97.0,),)
        finally:
            loop.set_exception_handler(previous)

    asyncio.run(scenario())


def test_query_embeddings_preserve_provider_semantics_and_separate_cache_identity():
    async def scenario():
        class Asymmetric(_Embedding):
            async def embed_query(self, texts):
                self.calls.append(texts)
                return EmbeddingResult(vectors=tuple((-float(ord(text[0])),) for text in texts))

        base = Asymmetric()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0)
        documents, queries = await asyncio.gather(model.embed(("a",)), embed_query(model, ("a",)))
        assert documents.vectors == ((97.0,),)
        assert queries.vectors == ((-97.0,),)
        assert (await model.embed(("a",))).vectors == documents.vectors
        assert (await embed_query(model, ("a",))).vectors == queries.vectors
        assert len(base.calls) == 2
        assert model.profile is base.profile

    asyncio.run(scenario())


def test_symmetric_query_path_reuses_document_cache():
    async def scenario():
        base = _Embedding()
        model = CoalescingEmbeddingModel(base, coalesce_ms=0)
        await model.embed(("a",))
        result = await embed_query(model, ("a", "a"))
        assert result.vectors == ((97.0,), (97.0,))
        assert result.usage.requests == 0
        assert base.calls == [("a",)]

    asyncio.run(scenario())


def test_usage_tracks_invocations_when_provider_reuses_the_same_result_object():
    async def scenario():
        class ReusedResult(_Embedding):
            result = EmbeddingResult(
                vectors=((1.0,),), usage=InferenceUsage(requests=2, input_tokens=7, output_tokens=0)
            )

            async def embed(self, texts):
                self.calls.append(texts)
                return self.result

        base = ReusedResult()
        model = CoalescingEmbeddingModel(base, max_batch_size=1, coalesce_ms=0)
        result = await model.embed(("a", "b", "a"))
        assert result.vectors == ((1.0,),) * 3
        assert result.usage == InferenceUsage(requests=4, input_tokens=14, output_tokens=0)

    asyncio.run(scenario())
