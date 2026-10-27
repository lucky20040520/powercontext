# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

from __future__ import annotations

import asyncio
import json

import httpx

from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.client import PowerContextClient
from powercontext.http import (
    CreateScopeRequest,
    GetMemoryEntryRequest,
    MemoryCitation,
    PrepareContextRequest,
    RememberMemoryRequest,
    ReviseMemoryEntryRequest,
)
from powercontext.server.factory import create_server_app
from powercontext.server.settings import McpConfig, MetricsConfig, ServerSettings


def test_http_evidence_selection_round_trips_exact_historical_memory_and_default_context(tmp_path):
    async def scenario():
        app = create_server_app(
            settings=ServerSettings(
                database=SQLiteConfig(url=f"sqlite+aiosqlite:///{tmp_path / 'evidence.db'}"),
                mcp=McpConfig(enabled=False),
                metrics=MetricsConfig(enabled=False),
            ),
            scheduler_path=tmp_path / "scheduler.db",
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as transport,
        ):
            client = PowerContextClient("http://testserver", http_client=transport, trust_transport_security=True)
            scope = await client.create_scope(
                CreateScopeRequest(title="Evidence", summary="Literal selection", idempotency_key="literal-selection")
            )
            text = "Administrative records. " * 80 + "The cobalt sensor calibration is 37 degrees."
            remembered = await client.remember_memory(
                RememberMemoryRequest(scope_id=scope.scope_id, kind="fact", text=text)
            )
            request = PrepareContextRequest.model_validate({
                "scope_id": scope.scope_id,
                "query": "cobalt sensor calibration",
                "max_bytes": 1000,
                "evidence_selection": True,
                "assembly": {"sections": []},
                "include_code": True,
            })
            prepared = await client.prepare_context(request)
            assert prepared.content is not None
            assert prepared.content_bytes == len(prepared.content.encode("utf-8")) <= 1000
            (item,) = json.loads(prepared.content.splitlines()[-2])["items"]
            assert item["citation"]["scope_id"] == scope.scope_id
            citation = MemoryCitation.model_validate({k: v for k, v in item["citation"].items() if k != "scope_id"})
            assert remembered.entry is not None
            assert citation == remembered.entry.citation
            assert item["start"] > 1000 and "37 degrees" in item["content"]
            await client.revise_memory_entry(
                ReviseMemoryEntryRequest(
                    scope_id=scope.scope_id,
                    citation=citation,
                    kind="fact",
                    text="The cobalt sensor now uses 38 degrees.",
                )
            )
            historical = await client.get_memory_entry(
                GetMemoryEntryRequest(scope_id=scope.scope_id, citation=citation)
            )
            assert historical.text[item["start"] : item["end"]] == item["content"]
            legacy = await client.prepare_context(PrepareContextRequest(scope_id=scope.scope_id, query="cobalt sensor"))
            assert legacy.content is not None
            (legacy_item,) = json.loads(legacy.content.splitlines()[-2])["items"]
            assert legacy_item["content"] == "The cobalt sensor now uses 38 degrees."
            assert "start" not in legacy_item and "end" not in legacy_item
            for value in (1, "true", None):
                response = await transport.post(
                    "/v1/context/prepare",
                    json={"scope_id": scope.scope_id, "query": "cobalt sensor", "evidence_selection": value},
                )
                assert response.status_code == 422

    asyncio.run(scenario())
