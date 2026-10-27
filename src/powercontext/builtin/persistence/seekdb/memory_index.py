# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""One-statement native full-text and vector candidate retrieval for seekdb."""

from __future__ import annotations

from pyobvector import VECTOR
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection
from typing_extensions import override

from powercontext.builtin.artifacts.memory import (
    CapabilityNotSupportedError,
    EmbeddingProfile,
    MemorySearchChannels,
    MemorySearchRequest,
)
from powercontext.builtin.artifacts.memory.canonical import validate_embedding
from powercontext.builtin.persistence.memory_index import CompositeMemoryIndex, memory_channel_hits
from powercontext.builtin.persistence.oceanbase.memory_index import OceanBaseMemoryFTSIndex, OceanBaseMemoryVectorIndex
from powercontext.builtin.persistence.tags import memory_tag_parameters, memory_tag_sql

# Each branch keeps its own index-friendly ordering and LIMIT. The outer ordering
# restores channel rank after UNION ALL; its tie breakers use exact stored identities.
# Keep version-body hydration outside the ANN top-k boundary.
_HYBRID_SEARCH_SQL = """
SELECT * FROM (
    SELECT 'fts' AS channel,
           f.memory_artifact_id, f.head_revision, f.entry_id, f.entry_version_id,
           v.text, NULL AS distance,
           -MATCH(f.searchable_text) AGAINST (:query) AS channel_order
    FROM pc_memory_entry_heads AS f
    JOIN pc_memory_entry_versions AS v
      ON v.scope_id = f.scope_id
     AND v.memory_artifact_id = f.memory_artifact_id
     AND v.entry_version_id = f.entry_version_id
    WHERE f.scope_id = :scope_id
      AND f.memory_artifact_id IN :memory_artifact_ids
      AND MATCH(f.searchable_text) AGAINST (:query)
      {fts_tags}
    ORDER BY channel_order, f.memory_artifact_id, f.entry_id, f.entry_version_id
    LIMIT :candidate_limit
) AS lexical_candidates
UNION ALL
SELECT 'vector' AS channel,
       n.memory_artifact_id, n.head_revision, n.entry_id, n.entry_version_id,
       v.text, n.distance, n.distance AS channel_order
FROM (
    SELECT m.scope_id, m.memory_artifact_id, m.head_revision, m.entry_id, m.entry_version_id,
           l2_distance(m.embedding, :query_vector) AS distance
    FROM pc_memory_vector_entries AS m
    {vector_tag_join}
    WHERE m.scope_id = :scope_id
      AND m.memory_artifact_id IN :memory_artifact_ids
    ORDER BY l2_distance(m.embedding, :query_vector) APPROXIMATE
    LIMIT :candidate_limit
) AS n
JOIN pc_memory_entry_versions AS v
  ON v.scope_id = n.scope_id
 AND v.memory_artifact_id = n.memory_artifact_id
 AND v.entry_version_id = n.entry_version_id
ORDER BY channel, channel_order, memory_artifact_id, entry_id, entry_version_id
"""


# A correlated tag subquery can be applied after ANN's internal top-k in seekdb.
# Join the grouped eligible identities before neighbor selection instead. Grouping
# also prevents one entry with several matching tags from consuming multiple slots.
_VECTOR_TAG_JOIN = """
JOIN (
    SELECT scope_id, artifact_id, target_id
    FROM pc_artifact_tags
    WHERE scope_id = :scope_id
      AND family = 'memory'
      AND artifact_id IN :memory_artifact_ids
      AND target_type = 'memory_entry'
      AND tag_key_hash IN :tag_hashes
      AND tag_key IN :tag_keys
    GROUP BY scope_id, artifact_id, target_id
    HAVING COUNT(*) >= :tag_minimum
) AS eligible
  ON eligible.scope_id = m.scope_id
 AND eligible.artifact_id = m.memory_artifact_id
 AND eligible.target_id = m.entry_id
"""


class SeekDBMemoryIndex(CompositeMemoryIndex):
    """Share existing projection lifecycle and single-channel behavior with OceanBase."""

    def __init__(self, profile: EmbeddingProfile) -> None:
        self._vector = OceanBaseMemoryVectorIndex(profile)
        super().__init__(OceanBaseMemoryFTSIndex(), self._vector)
        self._hybrid_sql = {}
        for tagged in (False, True):
            self._hybrid_sql[tagged] = text(
                _HYBRID_SEARCH_SQL.format(
                    fts_tags=memory_tag_sql("f") if tagged else "",
                    vector_tag_join=_VECTOR_TAG_JOIN if tagged else "",
                )
            ).bindparams(
                bindparam("memory_artifact_ids", expanding=True),
                bindparam("query_vector", type_=VECTOR(profile.dimension)),
                *((bindparam("tag_keys", expanding=True), bindparam("tag_hashes", expanding=True)) if tagged else ()),
            )

    @override
    async def search(
        self, connection: AsyncConnection, scope_id: str, request: MemorySearchRequest, /
    ) -> MemorySearchChannels:
        if request.mode != "hybrid":
            return await super().search(connection, scope_id, request)
        profile = self._vector.profile
        if request.embedding_profile != profile or request.query_vector is None:
            raise CapabilityNotSupportedError("embedding-profile")
        if not await self._vector.vector_complete(connection, scope_id, request.memories, profile):
            raise CapabilityNotSupportedError("vector")
        rows = (
            (
                await connection.execute(
                    self._hybrid_sql[request.tag_filter is not None],
                    {
                        "scope_id": scope_id,
                        "memory_artifact_ids": tuple(memory.artifact_id for memory in request.memories),
                        "query": request.analyzed_query,
                        "query_vector": validate_embedding(request.query_vector, dimension=profile.dimension),
                        "candidate_limit": request.candidate_limit,
                        **memory_tag_parameters(request.tag_filter),
                    },
                )
            )
            .mappings()
            .all()
        )
        return MemorySearchChannels(
            fts=memory_channel_hits((row for row in rows if row["channel"] == "fts"), request.memories),
            vector=memory_channel_hits((row for row in rows if row["channel"] == "vector"), request.memories),
        )
