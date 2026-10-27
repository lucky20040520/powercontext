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

"""Shared pre-limit eligibility for native Topic retrieval channels."""

from typing import Literal

from sqlalchemy import Table, select
from sqlalchemy.sql import ColumnElement

from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_NODES_TABLE


def topic_lifecycle_predicate(topics: Table) -> ColumnElement[bool]:
    nodes = SOURCE_LIFECYCLE_NODES_TABLE
    return (
        ~select(nodes.c.node_key)
        .where(
            nodes.c.scope_id == topics.c.scope_id,
            nodes.c.topic_artifact_id == topics.c.artifact_id,
            nodes.c.available.is_(False),
        )
        .correlate(topics)
        .exists()
    )


def topic_lifecycle_sql(
    table_name: Literal[
        "pc_topic_memory_topic_fts",
        "pc_topic_memory_chunk_fts",
        "pc_topic_memory_vector_topics",
        "pc_topic_memory_vector_chunks",
        "v",
    ],
) -> str:
    """Render the same predicate for static backend SQL table names/aliases."""

    return (
        "NOT EXISTS (SELECT 1 FROM pc_source_lifecycle_nodes AS lifecycle "  # noqa: S608 - fixed internal identifiers
        f"WHERE lifecycle.scope_id = {table_name}.scope_id "
        f"AND lifecycle.topic_artifact_id = {table_name}.artifact_id AND lifecycle.available = 0)"
    )
