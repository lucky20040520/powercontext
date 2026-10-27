---
title: Configure vector search
description: Enable embedding-backed vector and hybrid Memory search, then verify the Runtime capability.
---

# Configure vector search

Vector search needs an embedding model, a stable profile ID, and the model's output dimension.

## 1. Set one embedding profile

```bash
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_MODEL=provider:embedding-model
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_PROFILE_ID=embedding-model-v1
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_DIMENSION=1024
```

Replace the example values with one supported provider model, a profile ID you keep stable for that model, and its
documented output dimension. `POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_NORMALIZATION` defaults to `unit`.

The output dimension is always required. It fixes the local vector index width and validates returned vectors. By
default that value is also sent as the `dimensions` request field. Some OpenAI-compatible services reject the field,
including SiliconFlow `BAAI/bge-m3`. Keep the documented output dimension (1024 for bge-m3) and disable sending:

```bash
export POWERCONTEXT_SERVER_INFERENCE_EMBEDDING_SEND_DIMENSIONS=false
```

## 2. Start the Server

```bash
powercontext server run
```

With SQLite, PowerContext loads the bundled sqlite-vec extension when it opens the database. Startup fails if the
installed extension is incompatible with the platform or SQLite build.

## 3. Verify the capability

```bash
powercontext capabilities
```

The result reports the enabled search modes. Without an embedding profile, SQLite full-text search remains available.

For timeouts, batch size, storage settings, and exact defaults, see [Configuration](../operate/configuration.md).

## Native seekdb hybrid candidates

With the seekdb backend and an embedding profile configured, `Memory.search(mode="hybrid")` retrieves its two candidate
rankings through one SQL statement on the existing connection. Each branch applies Scope, requested Memory artifacts,
optional tag predicates, and its own candidate limit in the database. The branches use the native FULLTEXT and HNSW
indexes; shared admission and reciprocal-rank fusion continue to run in the Memory service.

The one-statement guarantee covers candidate retrieval. Current-head and embedding-completeness validation and exact
body reads remain separate operations. Incremental projections need not be rewritten to stamp a new head revision:
returned citations use the requested, validated current Memory head and the selected entry version. Revision,
deactivation, reactivation, and projection recovery continue through the existing transactional write path.

No new configuration or schema migration is required. FTS-only and vector-only searches retain their existing paths;
OceanBase and SQLite keep their existing backend behavior. This query consolidation does not by itself establish
end-to-end speed or semantic retrieval quality; those require measurement with the chosen corpus and embeddings.
