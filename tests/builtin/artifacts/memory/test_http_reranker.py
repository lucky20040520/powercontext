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

"""HTTP protocol and global selection behavior for Memory reranking."""

from __future__ import annotations

import asyncio
import json
import math
from typing import cast

import httpx
import pytest

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import HTTPMemoryReranker, MemoryHit


def _hit(rank: int) -> MemoryHit:
    return MemoryHit(
        memory_ref=ArtifactRef(family="memory", artifact_id=f"memory-{rank}", revision=rank),
        entry_id=f"entry-{rank}",
        entry_version_id=f"version-{rank}",
        text=f"候选 {rank}: calibration evidence.",
        score=1 / rank,
        matched_by=("fts",),
    )


@pytest.mark.parametrize(("count", "batch_size", "limit"), [(1, 1, 1), (17, 7, 10), (65, 32, 10), (20, 1, 20)])
def test_every_candidate_is_scored_once_before_global_stable_selection(count: int, batch_size: int, limit: int) -> None:
    candidates = tuple(_hit(rank) for rank in range(1, count + 1))
    original = tuple(hit.model_dump() for hit in candidates)
    scores = {rank: (rank * 13) % 11 - 5 for rank in range(1, count + 1)}
    batches: list[tuple[int, ...]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url == httpx.URL("https://reranker.invalid/score")
        assert request.headers["Authorization"] == "Bearer test-token"
        body = json.loads(request.content)
        assert set(body) == {"query", "candidates"}
        assert body["query"] == "传感器 calibration?"
        assert 1 <= len(body["candidates"]) <= batch_size
        for item in body["candidates"]:
            assert set(item) == {"rank", "text"}
            assert item["text"] == candidates[item["rank"] - 1].text
        batches.append(tuple(item["rank"] for item in body["candidates"]))
        return httpx.Response(
            200,
            json={
                "scores": [
                    {"rank": item["rank"], "score": scores[item["rank"]]} for item in reversed(body["candidates"])
                ]
            },
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), headers={"Authorization": "Bearer test-token"}
        ) as client:
            reranker = HTTPMemoryReranker(
                "https://reranker.invalid/score", client=client, batch_size=batch_size, policy_id="test-http-v2"
            )
            decision = await reranker.rerank("传感器 calibration?", candidates, limit)
            assert not client.is_closed
            assert reranker.policy_id == "test-http-v2"
        assert decision.selected_ranks == tuple(sorted(scores, key=lambda rank: (-scores[rank], rank))[:limit])
        assert decision.usage.requests == len(batches) == math.ceil(count / batch_size)
        assert sorted(rank for batch in batches for rank in batch) == list(range(1, count + 1))
        assert decision.discarded_rank_count == 0
        assert not decision.used_fallback
        assert tuple(hit.model_dump() for hit in candidates) == original

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"scores": [], "extra": True},
        {"scores": None},
        {"scores": []},
        {"scores": [{"rank": 1, "score": 1}, {"rank": 1, "score": 2}]},
        {"scores": [{"rank": 2, "score": 1}]},
        {"scores": [{"rank": True, "score": 1}]},
        {"scores": [{"rank": 1.0, "score": 1}]},
        {"scores": [{"rank": "1", "score": 1}]},
        {"scores": [{"rank": 1}]},
        {"scores": [{"rank": 1, "score": True}]},
        {"scores": [{"rank": 1, "score": "0.9"}]},
        {"scores": [{"rank": 1, "score": None}]},
        {"scores": [{"rank": 1, "score": float("nan")}]},
        {"scores": [{"rank": 1, "score": float("inf")}]},
        {"scores": [{"rank": 1, "score": float("-inf")}]},
        {"scores": [{"rank": 1, "score": 1, "text": "replacement"}]},
    ],
)
def test_invalid_response_schema_or_coverage_fails(payload: object) -> None:
    async def scenario() -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(200, content=json.dumps(payload).encode()))
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ValueError):
                await HTTPMemoryReranker("https://reranker.invalid", client=client).rerank("q", (_hit(1),), 1)

    asyncio.run(scenario())


def test_previous_batch_rank_cannot_replace_current_batch_rank() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        rank = json.loads(request.content)["candidates"][0]["rank"]
        return httpx.Response(200, json={"scores": [{"rank": rank if rank == 1 else 1, "score": 0.5}]})

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            reranker = HTTPMemoryReranker("https://reranker.invalid", client=client, batch_size=1)
            with pytest.raises(ValueError):
                await reranker.rerank("q", (_hit(1), _hit(2)), 1)

    asyncio.run(scenario())


def test_malformed_json_is_a_value_error() -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text="{broken"))
        ) as client:
            with pytest.raises(ValueError):
                await HTTPMemoryReranker("https://reranker.invalid", client=client).rerank("q", (_hit(1),), 1)

    asyncio.run(scenario())


def test_integer_scores_keep_their_original_precision() -> None:
    async def scenario() -> None:
        transport = httpx.MockTransport(
            lambda _: httpx.Response(
                200, json={"scores": [{"rank": 1, "score": 2**53}, {"rank": 2, "score": 2**53 + 1}]}
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            decision = await HTTPMemoryReranker("https://reranker.invalid", client=client).rerank(
                "q", (_hit(1), _hit(2)), 2
            )
            assert decision.selected_ranks == (2, 1)

    asyncio.run(scenario())


def test_concurrent_queries_keep_scores_and_usage_independent() -> None:
    requests: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        query = body["query"]
        requests.append(query)
        await asyncio.sleep(0)
        sign = 1 if query == "ascending" else -1
        return httpx.Response(
            200,
            json={"scores": [{"rank": item["rank"], "score": sign * item["rank"]} for item in body["candidates"]]},
        )

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            reranker = HTTPMemoryReranker("https://reranker.invalid", client=client, batch_size=2)
            first, second = await asyncio.gather(
                reranker.rerank("ascending", tuple(_hit(rank) for rank in range(1, 6)), 3),
                reranker.rerank("descending", tuple(_hit(rank) for rank in range(1, 4)), 2),
            )
            assert first.selected_ranks == (5, 4, 3)
            assert second.selected_ranks == (1, 2)
            assert first.usage.requests == requests.count("ascending") == 3
            assert second.usage.requests == requests.count("descending") == 2

    asyncio.run(scenario())


@pytest.mark.parametrize("batch_size", [0, -1, True, 1.5, "2"])
def test_invalid_batch_size_is_rejected(batch_size: object) -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient() as client:
            with pytest.raises(ValueError):
                HTTPMemoryReranker("https://reranker.invalid", client=client, batch_size=cast(int, batch_size))

    asyncio.run(scenario())


@pytest.mark.parametrize(("count", "limit"), [(0, 1), (1, 0), (1, 2), (1, True), (1, 1.5), (1, "1")])
def test_invalid_rerank_bounds_fail_before_sending_requests(count: int, limit: object) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("invalid input must not be sent")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(ValueError):
                await HTTPMemoryReranker("https://reranker.invalid", client=client).rerank(
                    "q", tuple(_hit(rank) for rank in range(1, count + 1)), cast(int, limit)
                )

    asyncio.run(scenario())


@pytest.mark.parametrize("status", [302, 429, 503])
def test_non_success_responses_preserve_http_status_errors(status: int) -> None:
    async def scenario() -> None:
        transport = httpx.MockTransport(lambda _: httpx.Response(status, headers={"Location": "/redirect"}))
        async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
            with pytest.raises(httpx.HTTPStatusError) as failure:
                await HTTPMemoryReranker("https://reranker.invalid", client=client).rerank("q", (_hit(1),), 1)
            assert failure.value.response.status_code == status

    asyncio.run(scenario())


@pytest.mark.parametrize("error_type", [httpx.ConnectError, httpx.ReadTimeout, asyncio.CancelledError])
def test_transport_errors_and_cancellation_propagate(error_type: type[BaseException]) -> None:
    error = error_type("scoring interrupted")

    def handler(_: httpx.Request) -> httpx.Response:
        raise error

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(error_type) as failure:
                await HTTPMemoryReranker("https://reranker.invalid", client=client).rerank("q", (_hit(1),), 1)
            assert failure.value is error

    asyncio.run(scenario())
