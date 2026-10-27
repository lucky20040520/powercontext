# HTTP Memory reranking

`HTTPMemoryReranker` implements the existing Memory reranker port with an HTTP scoring service.
Inject it through `memory_reranker` when opening Runtime or built-in contexts. The caller supplies
an `httpx.AsyncClient` and owns its authentication, timeouts, transport, and lifetime.

```python
import httpx

from powercontext.builtin.artifacts.memory import HTTPMemoryReranker
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_runtime

async with httpx.AsyncClient(timeout=10) as client:
    reranker = HTTPMemoryReranker(
        "http://127.0.0.1:8080/score",
        client=client,
        batch_size=7,
        policy_id="http-cross-encoder-v1",
    )
    async with open_builtin_runtime(BuiltinConfig(), memory_reranker=reranker) as runtime:
        memory = runtime.memory.for_scope("project")
        # Use memory.search() for an existing Scope containing captured evidence.
```

Each POST contains exactly the query and one candidate batch:

```json
{"query":"sensor calibration","candidates":[{"rank":1,"text":"Calibration record."}]}
```

The service returns scores in any order:

```json
{"scores":[{"rank":1,"score":0.75}]}
```

Ranks refer to the complete input pool, starting at one, and never restart at batch boundaries.
Each candidate is sent exactly once. A response must contain only `scores`, with one record per
rank in that request. Each record contains only an integer `rank` and a finite numeric `score`.
Boolean, string, NaN, and infinite scores are invalid, as are missing, duplicate, or cross-batch ranks.

After every batch succeeds, the adapter selects the first `limit` ranks by descending score,
breaking ties by ascending original rank. Native Memory search resolves these ranks to the original
hits, preserving their text, scores, Artifact references, entry IDs, and entry version IDs.
Reranking writes no Memory revisions. `result.rerank.usage.requests` reports the number of HTTP
requests issued, which is `ceil(candidate_count / batch_size)` on success. An empty native search
does not call the reranker.

Direct calls require nonempty candidates, a positive integer `batch_size`, and an integer
`limit` between one and the candidate count. Invalid arguments, JSON, schemas, or coverage raise
`ValueError`. Non-2xx responses and transport errors preserve httpx exceptions. Cancellation
propagates. The adapter performs no retries, follows no redirects, and returns no partial selection
when a batch fails. Concurrent calls keep their query scores and usage separate.

Focused protocol tests use `httpx.MockTransport`. The end-to-end test uses a real loopback HTTP
server and a file-backed SQLite database, closing and reopening the contexts before searching and
expanding exact entry versions. Run them with:

```sh
uv run --locked python -m pytest tests/builtin/artifacts/memory/test_http_reranker.py tests/e2e/test_http_memory_reranker.py
```

The competition's fixed offline environment runs its published acceptance tests with:

```sh
make -C competition test-rerank
```

The [challenge](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/te7ynwpbeg0cbufs)
also requires mean Recall@10 ≥0.95 and mean MRR@10 ≥0.80 over 20 SciFact queries and 173 abstracts
using its frozen 384-dimensional MiniLM vectors. The published sample contains one query and eight
abstracts, without qrels or those frozen vectors. Protocol and integration tests do not establish
those full-set quality thresholds. The HTTP adapter uses service scores without loading evaluation
labels, implementing its own relevance model, or reordering results using corpus-specific rules.
