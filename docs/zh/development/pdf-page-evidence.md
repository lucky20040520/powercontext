# PDF 页级证据

安装 `powercontext[pdf]` 后，可通过 pypdf 提取正文。解析器接收原始 PDF 字节和非空白文档 ID，
按顺序返回所有物理页，包括空白页。页码从 1 开始，每页携带完整原文件的 SHA-256 摘要。
支持空密码权限标记；需要非空密码的文件会被拒绝。损坏或无法完整读取的文档在返回页面之前
整体以 `ValueError` 失败。扫描图像不进行 OCR。
Flate 编码的页内容会在 pypdf 尝试容错恢复之前检查压缩数据完整性，避免把损坏流当作成功解析。
Flate 位于其他编码之后的过滤链也会执行该校验。
嵌套 Form XObject 的文本流执行相同校验，防止损坏的表格或正文被提取器静默跳过。
资源遍历记录已访问的对象，避免循环引用导致无限递归；图像内容不参与文本流校验。

```python
from powercontext.sources.pdf_pages import PDFDocumentInput, parse_pdf_document

pages = parse_pdf_document(PDFDocumentInput(document_id="年度报告", content=pdf_bytes))
```

将 `PDF_PAGE_SOURCE_DEFINITION` 注册到 `SourceDefinitionRegistry`，逐页 resolve，
再通过 `project_source_for_transport` 创建 observation。向 Runtime ingestion 注册定义清单，
把全部 observation 提交到指定 Scope，并使用保留完整投影正文及 Source 引用的 pipeline
刷新 Memory。标准 `powercontext.text-evidence@1` 投影正文为 `document_id + "\n" + page.text`，
metadata 恰好包含 `document_id`、`document_sha256`、`page_number`。

Source 身份对文档 ID、完整文件摘要和物理页码的无歧义编码计算摘要，固定为 68 个字符，
不依赖提取正文。PDF 修订会产生新的页身份，旧 Source 和 Memory citation 继续对应原修订。
物理页码不能当作报告印刷页码使用。

重新打开 Runtime 后即可检索：

```python
from powercontext.sources.pdf_pages import search_pdf_pages
from powercontext.builtin.runtime import GetMemoryEntryRequest

memory = runtime.memory.for_scope(scope_id)
citations = await search_pdf_pages(memory, "What was operating income in 2025?", limit=20)
for citation in citations:
    record = await memory.get(GetMemoryEntryRequest(citation=citation))
```

检索通过公开的 scoped `Memory.list()` 读取有效条目，使用该精确快照的真实 citation。
排序结合 BM25、财务词汇扩展、报表短语以及文档和年份匹配，最多返回 `limit` 个不同页 Source。
能够识别的问题公司名会先选择对应报告，再进行页排序；存在匹配报告年份时优先使用该年份，
没有对应年份时保留该公司的可用报告。涉及多个公司或年份的问题保留相应报告；没有识别出身份时
搜索整个 Scope。业务概览可以为地区问题提供上下文，即使正文只列地区名称而没有复述问题关键词；
出现在长前言之后的业务标题也参与识别。
不返回无关记忆或合并多个 Source 的条目。空白问题和非正数上限返回空元组。
检索不调用模型、网络，不读取文件，也不依赖进程缓存。

每次查询读取并分词该 Scope 的全部正文，时间和临时内存随正文总量线性增长，适合题目中
1,151 页规模的小型报告集。更大的部署应在同样的精确引用契约下使用有界索引。
公开的 503 页自测验证全页覆盖、持久化及引用完整性；隐藏证据的召回率和词项质量门槛需要
评测方未公开的标注，不能由公开自测结果推定。

本机在官方 1 CPU、2 GB 容器中，以公开报告页面的副本组成 1,151 页 observation 进行规模检查。
原始 503 页解析约 7.3 秒，合成语料持久化及刷新约 47.3 秒。重新打开 Runtime 后，单次查询约
0.55–0.63 秒，进程峰值 RSS 约 206 MiB。这些数据只描述该合成负载，不代表隐藏集召回率，
也不是通用延迟保证。

在比赛固定依赖、离线环境中运行：

```sh
make -C competition test-pdf
```

补充行为测试位于 `tests/test_pdf_pages.py` 和 `tests/e2e/test_pdf_page_retrieval.py`。

## 公开组质量验证

2026-10-27 对实现进行了独立评测，
使用完整公开 PDF 和全部 5 道公开问题。参考仅包含这些问题的 8 条证据标注，涉及 6 张不同物理页，
来自 [FinanceBench 固定版本公开数据](https://github.com/patronus-ai/financebench/blob/cc39aeb4afdf33909ee1412188bf89035950c2eb/data/financebench_open_source.jsonl)。
参考文件不包含答案和解释。数据许可沿用 CC BY-NC 4.0，原财报保留相应权利。

推理使用官方离线 1 CPU、2 GB 容器，候选源码只读，标注文件没有挂入容器。
全部 503 页提交真实 SQLite Runtime；关闭并重新打开 Runtime 后检索，逐条通过 `memory.get`
回查引用。独立评分器将固定候选的输出与参考标注比对。

两侧文本转小写，以 `[a-z]+|\d+` 分词，交集按词频多重集合计数，不应用检索使用的词形归一化。
每条证据的召回率和每张标注页的 F1 分别检查，不用平均值容纳低于阈值的条目。
标注中的 0 起始页码统一加 1，
转换为物理页码。Recall@20 对每道问题的不同文档页去重，再将命中页数累加后除以标注页数之和。

| 指标 | 要求 | 实测 | 结论 |
| --- | --- | --- | --- |
| 每页词项数与平台冻结值比较 | 90%–110% | 未获得平台冻结参考 | 尚未验证 |
| 每页词项数与独立 Poppler 提取结果比较 | 90%–110% | 503/503 页在范围内 | 交叉检查通过，不等同平台冻结参考 |
| 词项数与标注整页文本比较 | 90%–110% | 6/6 张标注页在范围内，比例为 1.0000–1.0139 | 标注页通过 |
| 每条证据词项召回率 | ≥0.95 | 最低 0.9962121212，8 条全部通过 | 公开组通过 |
| 标注整页词项 F1 | ≥0.95 | 最低 0.9793459552，8 次标注整页比较全部通过 | 公开组通过 |
| evidence-page Recall@20 | 整组 ≥0.70 | 8/8 = 1.000 | 公开组通过 |

独立全页参考由 Poppler `pdftotext 25.02.0 -layout -enc UTF-8` 提取，不能证明与平台未发布的冻结值
也全部一致。5 道公开问题均完整命中其标注页。留出组尚未验证。

### 额外公开回归样本

另外将完整的 `VERIZON_2022_10K`（124 页）和 `WALMART_2020_10K`（170 页）提交到独立的同一
Scope 中检索。选择规则是同一上游公开数据集中公司名字母顺序最后两家公司，再取各自报告 ID
字母顺序最后一份，不根据分数选择。两份报告的 4 道公开问题共有 6 条证据标注，涉及 5 张不同页。
推理与标注隔离、逐条评分方法与公开组一致。

| 指标 | 实测 | 结论 |
| --- | --- | --- |
| 每条证据词项召回率 | 最低 0.9912663755，6 条均 ≥0.95 | 通过 |
| 标注整页词项 F1 | 最低 0.9925558313，6 次比较均 ≥0.95 | 通过 |
| evidence-page Recall@20 | 5/6 = 0.8333333333 | 达到本样本的 0.70 门槛 |
| 独立 Poppler 词项数交叉检查 | 294/294 页位于 90%–110% | 通过，不等同平台冻结参考 |

其中一道问题仍漏掉标注页。这个补充公开样本不能证明官方隐藏组得分。公开组和隐藏组各自必须
达到 Recall@20 ≥0.70，不能合并两个组的分数来补偿某一组未达标。
