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
from typing import Any, cast

import pytest
from pydantic import ValidationError

from powercontext.builtin.persistence.cursors import SourceCursorRepository
from powercontext.builtin.persistence.sources import SourceRepository
from powercontext.builtin.runtime import RuntimeConfig
from powercontext.builtin.runtime.artifact_processing import ArtifactProcessingBinding, ArtifactProcessingSupervisor
from powercontext.builtin.runtime.processing_discovery import SourceCountThreshold
from powercontext.builtin.sources import CONTENT_SOURCE_ADAPTER, ContentSource, SourceCursor
from powercontext.builtin.triggers import SOURCE_WINDOW_TRIGGER_NAME
from powercontext.server.settings import ServerSettings
from powercontext.sources import SourceMaterialization
from tests.builtin.runtime.test_processing_scheduler import _intent, _Launcher, _profile, _wait

FIELDS = ("memory_source_count_threshold", "topic_memory_source_count_threshold")


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", [True, False, "3", 1.0, 0, -1, [], {}])
def test_count_configuration_rejects_coercions(field, value):
    with pytest.raises(ValidationError):
        RuntimeConfig.model_validate({field: value})


@pytest.mark.parametrize("field", FIELDS)
def test_count_configuration_defaults_and_serialization(field):
    assert getattr(RuntimeConfig(), field) is None
    configured = RuntimeConfig.model_validate({field: 3})
    restored = RuntimeConfig.model_validate_json(configured.model_dump_json())
    assert restored.model_dump() == configured.model_dump()
    assert getattr(restored, field) == 3


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", ["1", "3", "100"])
def test_server_environment_parses_decimal_thresholds(monkeypatch, field, value):
    monkeypatch.setenv(f"POWERCONTEXT_SERVER_RUNTIME_{field.upper()}", value)
    assert getattr(ServerSettings().runtime, field) == int(value)


@pytest.mark.parametrize("value", ["true", "false", "0", "-1", "1.0", '"3"'])
def test_server_environment_preserves_threshold_validation(monkeypatch, value):
    monkeypatch.setenv("POWERCONTEXT_SERVER_RUNTIME_MEMORY_SOURCE_COUNT_THRESHOLD", value)
    with pytest.raises(ValidationError):
        ServerSettings()


def test_server_threshold_sources_and_explicit_precedence(tmp_path, monkeypatch):
    monkeypatch.setenv("POWERCONTEXT_SERVER_RUNTIME_MEMORY_SOURCE_COUNT_THRESHOLD", "3")
    assert (
        ServerSettings(runtime=RuntimeConfig(memory_source_count_threshold=7)).runtime.memory_source_count_threshold
        == 7
    )
    env_file = tmp_path / "count.env"
    env_file.write_text("POWERCONTEXT_SERVER_RUNTIME_TOPIC_MEMORY_SOURCE_COUNT_THRESHOLD=4\n", encoding="utf-8")
    assert cast(Any, ServerSettings)(_env_file=env_file).runtime.topic_memory_source_count_threshold == 4
    with pytest.raises(ValidationError):
        ServerSettings(runtime=cast(Any, {"memory_source_count_threshold": "7"}))


def test_count_admission_reaches_later_scopes_and_revisits_new_input_without_a_wake(tmp_path):
    """A page of subthreshold Scopes cannot hide a busy Scope or need a capture hook."""

    async def scenario():
        async with _profile(tmp_path, "count-pages") as profile:
            sources = SourceRepository((CONTENT_SOURCE_ADAPTER,))
            cursors = SourceCursorRepository()
            binding = SOURCE_WINDOW_TRIGGER_NAME

            async def capture(scope, number):
                async with profile.database.transaction() as connection:
                    await sources.add(
                        connection,
                        scope,
                        ContentSource(
                            name=f"note-{number}",
                            content="Observed evidence",
                            materialization=SourceMaterialization.CAPTURED,
                        ),
                    )

            # More than one scheduler page; almost all rows are ineligible.
            scopes = [f"scope-{i}" for i in range(125)]
            for scope in scopes:
                await capture(scope, 1)
            await capture(scopes[-1], 2)

            async def consume(work):
                async with profile.database.transaction() as connection:
                    cursor = await cursors.load(connection, work.scope_id, binding)
                    high = await sources.journal_position(connection, work.scope_id)
                    await cursors.save(
                        connection,
                        work.scope_id,
                        binding,
                        SourceCursor(sequence=high),
                        expected_generation=None if cursor is None else cursor.generation,
                    )

            launcher = _Launcher(profile.database, on_work=consume)
            async with ArtifactProcessingSupervisor(
                database=profile.database,
                bindings=(
                    ArtifactProcessingBinding(
                        binding, "memory", launcher, automatic_count_filter=SourceCountThreshold(binding, 2)
                    ),
                ),
                lease_mode="single-process",
                oceanbase_tick_seconds=0.1,
            ) as supervisor:
                await _wait(lambda: supervisor.family_status["memory"]["completed"] == 1)
                assert [work.scope_id for work in launcher.assignments] == [scopes[-1]]
                await capture(scopes[0], 2)
                await _wait(lambda: supervisor.family_status["memory"]["completed"] == 2)
                assert [work.scope_id for work in launcher.assignments] == [scopes[-1], scopes[0]]
                # Only one new identity remains after the successful cursor.
                await capture(scopes[0], 3)
                await capture(scopes[0], 3)
                await asyncio.sleep(0.35)
                assert supervisor.family_status["memory"]["completed"] == 2
                await capture(scopes[0], 4)
                await _wait(lambda: supervisor.family_status["memory"]["completed"] == 3)
                assert (await _intent(profile.database, binding, scopes[0])).handled_generation == 2

    asyncio.run(scenario())
