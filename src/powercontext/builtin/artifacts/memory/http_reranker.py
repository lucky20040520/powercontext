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

"""Batched HTTP scoring with identity-preserving global Memory selection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, FiniteFloat

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

if TYPE_CHECKING:
    import httpx


class _Score(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    rank: int
    score: int | FiniteFloat


class _Response(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    scores: list[_Score]


class HTTPMemoryReranker:
    """Select original candidates using scores from a caller-owned HTTP client.

    Each batch uses one POST request. Responses must score every rank in that
    batch exactly once. All scores participate in one global selection, ordered
    by descending score and then ascending original rank. HTTP errors propagate;
    malformed JSON, schemas, and rank coverage raise ``ValueError``.

    The caller owns the client's lifetime, authentication, and timeout settings.
    The adapter neither retries requests nor follows redirects.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = "http-cross-encoder-v1",
    ) -> None:
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")  # noqa: TRY003
        self.policy_id = policy_id
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        """Score every candidate and select up to ``limit`` original ranks."""

        if not candidates:
            raise ValueError("rerank requires at least one candidate")  # noqa: TRY003
        if type(limit) is not int or not 1 <= limit <= len(candidates):
            raise ValueError("rerank limit must be between one and the candidate count")  # noqa: TRY003

        scores: list[_Score] = []
        requests = 0
        for offset in range(0, len(candidates), self._batch_size):
            batch = candidates[offset : offset + self._batch_size]
            requests += 1
            response = await self._client.post(
                self._endpoint,
                json={
                    "query": query,
                    "candidates": [
                        {"rank": rank, "text": candidate.text} for rank, candidate in enumerate(batch, start=offset + 1)
                    ],
                },
                follow_redirects=False,
            )
            response.raise_for_status()
            batch_scores = _Response.model_validate(response.json()).scores
            expected_ranks = set(range(offset + 1, offset + len(batch) + 1))
            if len(batch_scores) != len(batch) or {item.rank for item in batch_scores} != expected_ranks:
                raise ValueError("response must score every rank in the current batch exactly once")  # noqa: TRY003
            scores.extend(batch_scores)

        scores.sort(key=lambda item: (-item.score, item.rank))
        return MemoryRerankDecision(
            selected_ranks=tuple(item.rank for item in scores[:limit]),
            usage=InferenceUsage(requests=requests),
        )


__all__ = ["HTTPMemoryReranker"]
