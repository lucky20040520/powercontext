# HTTP Memory 重排

`HTTPMemoryReranker` 使用 HTTP 评分服务实现现有的 Memory 重排接口，通过构造 Runtime 或内置
contexts 时的 `memory_reranker` 参数注入。调用方提供 `httpx.AsyncClient`，并负责认证、超时、
transport 和客户端生命周期。

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
        # 对已经捕获证据的现有 Scope 调用 memory.search()。
```

每条 POST 请求恰好包含查询和一个候选批次：

```json
{"query":"sensor calibration","candidates":[{"rank":1,"text":"Calibration record."}]}
```

服务可以乱序返回分数：

```json
{"scores":[{"rank":1,"score":0.75}]}
```

rank 始终是完整候选池中的一基序号，分批后不重新编号。每个候选恰好发送一次。响应只能包含
`scores`，必须为当前请求中的每个 rank 恰好返回一条记录。每条记录只能包含整数 `rank` 和有限
数值 `score`；拒绝布尔值、字符串、NaN、无穷值，以及缺失、重复或跨批次的 rank。

所有批次成功后，统一按 score 降序选择前 `limit` 个 rank，同分按原始 rank 升序。原生 Memory
搜索将这些序号映射回原候选，保留正文、原检索分数、Artifact 引用、entry ID 和 entry version ID，
不会写入新的 Memory 修订。`result.rerank.usage.requests` 报告实际发出的 HTTP 请求数，成功时等于
`ceil(candidate_count / batch_size)`。原生搜索没有候选时不会调用重排服务。

直接调用要求候选非空、`batch_size` 为正整数、`limit` 为一至候选数之间的整数。非法参数、JSON、
schema 或覆盖情况抛出 `ValueError`；非 2xx 响应和网络错误保留 httpx 异常，取消信号原样传播。
适配器不重试、不跟随重定向，任一批次失败时不返回部分选择。并发查询的分数和请求统计各自独立。

协议测试使用 `httpx.MockTransport`。端到端测试使用真实的本地 HTTP 服务和文件 SQLite，关闭并
重新打开 contexts 后搜索，再展开精确的 entry version。运行方式：

```sh
uv run --locked python -m pytest tests/builtin/artifacts/memory/test_http_reranker.py tests/e2e/test_http_memory_reranker.py
```

比赛固定依赖的离线环境运行公开验收：

```sh
make -C competition test-rerank
```

[赛题](https://oceanbase.yuque.com/org-wiki-obtech-vh7w9r/hc3pio/te7ynwpbeg0cbufs)还要求在 173 篇
SciFact 摘要和 20 条查询上，使用冻结的 384 维 MiniLM 向量，平均 Recall@10 ≥0.95、平均
MRR@10 ≥0.80。公开样本只有一条查询和八篇摘要，不包含 qrels 和这些冻结向量。协议和集成测试
不能证明完整质量集达标。HTTP 适配器直接使用服务分数，不读取评测标签、不自行实现相关性模型，
也不按特定语料规则调整排序。
