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

"""Exercise HTTP reranking through persisted Memory and a real loopback server."""

from __future__ import annotations

import asyncio
import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from powercontext.artifacts import ArtifactRef
from powercontext.builtin.artifacts.memory import HTTPMemoryReranker, MemoryEntryInput
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts


def test_reopened_memory_uses_http_scores_and_preserves_exact_entry_versions(tmp_path: Path) -> None:
    batches: list[tuple[int, ...]] = []

    def score(text: str) -> int:
        return int(text.split()[-1].removesuffix(".")) % 4

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            if self.path != "/score":
                self.send_error(404)
                return
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            candidates = body["candidates"]
            batches.append(tuple(item["rank"] for item in candidates))
            raw = json.dumps({
                "scores": [{"rank": item["rank"], "score": score(item["text"])} for item in reversed(candidates)]
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - Match the HTTP server's public signature.
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def scenario() -> None:
        config = BuiltinConfig(database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'memory.db'}"))
        async with open_builtin_contexts(config) as contexts:
            service = (await contexts.get("http-rerank")).artifacts.memory
            memory = await service.remember(
                memory=None,
                entries=tuple(
                    MemoryEntryInput(kind="fact", text=f"Project evidence {number}.") for number in range(17)
                ),
                mode="append",
            )
            assert memory is not None
            stored = await service.entries(memory)

        async with httpx.AsyncClient(trust_env=False) as client:
            reranker = HTTPMemoryReranker(f"http://127.0.0.1:{server.server_port}/score", client=client, batch_size=7)
            async with open_builtin_contexts(config, memory_reranker=reranker) as contexts:
                service = (await contexts.get("http-rerank")).artifacts.memory
                result = await service.search("project", memories=(memory,), limit=10, mode="fts")
                assert result.rerank is not None
                candidates = result.rerank.candidate_hits
                assert len(candidates) == len(stored) == 17
                expected_ranks = tuple(
                    sorted(range(1, len(candidates) + 1), key=lambda rank: (-score(candidates[rank - 1].text), rank))[
                        :10
                    ]
                )
                assert result.rerank.selected_ranks == expected_ranks
                assert result.hits == tuple(candidates[rank - 1] for rank in expected_ranks)
                assert result.rerank.policy_id == "http-cross-encoder-v1"
                assert result.rerank.usage.requests == len(batches) == math.ceil(len(candidates) / 7)
                assert all(1 <= len(batch) <= 7 for batch in batches)
                assert sorted(rank for batch in batches for rank in batch) == list(range(1, len(candidates) + 1))
                versions = await service.expand(result.hits)
                assert tuple(version.entry_version_id for version in versions) == tuple(
                    hit.entry_version_id for hit in result.hits
                )
                reference = ArtifactRef(family=memory.family, artifact_id=memory.artifact_id, revision=memory.revision)
                assert all(hit.memory_ref == reference for hit in result.hits)
                assert await service.entries(memory) == stored
                empty = await service.search("absentword", memories=(memory,), limit=10, mode="fts")
                assert not empty.hits
                assert empty.rerank is None
                assert len(batches) == result.rerank.usage.requests
            assert not client.is_closed

    try:
        asyncio.run(scenario())
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
