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
排序融合三路 BM25：带报表标题的整页证据、问题原词与词组、120 词滑动窗口中的局部证据。
融合时保留有界的整页置信分数，避免只重复关键词的讨论页压过实际报表；短附注也能凭局部
匹配进入候选。窗口仅用于排序，不修改捕获的正文或页级引用。最多返回 `limit` 个不同页 Source。
财务词汇扩展覆盖比率计算所需科目、现金转换周期、股票回购、租赁、税项和资本回报等通用概念；
词形处理保留 loss、business 等单词，并归一化 taxes 等形式。
能够识别的问题公司名会先选择对应报告，再进行页排序；存在匹配报告年份时优先使用该年份，
没有对应年份时保留该公司的可用报告。公司名匹配忽略常见法律后缀和连接词，并从多词报告名
推导首字母缩写，不使用公司查找表。涉及多个公司或年份的问题保留相应报告；没有识别出身份时
搜索整个 Scope。业务概览可以为地区问题提供上下文，即使正文只列地区名称而没有复述问题关键词；
出现在长前言之后的业务标题也参与识别。
不返回无关记忆或合并多个 Source 的条目。空白问题和非正数上限返回空元组。
检索不调用模型、网络，不读取文件，也不依赖进程缓存。

每次查询读取并分词该 Scope 的全部正文，时间和临时内存随正文总量线性增长，适合题目中
1,151 页规模的小型报告集。更大的部署应在同样的精确引用契约下使用有界索引。
公开的 503 页自测验证全页覆盖、持久化及引用完整性；隐藏证据的召回率和词项质量门槛需要
评测方未公开的标注，不能由公开自测结果推定。

在比赛固定依赖、离线环境中运行：

```sh
make -C competition test-pdf
```

补充行为测试位于 `tests/test_pdf_pages.py` 和 `tests/e2e/test_pdf_page_retrieval.py`。

## 本地验证

在 Windows 上使用 Python 3.12 和比赛锁定的 pypdf 6.19.0。官方 503 页公开验收的 6 项测试
全部通过。解析器与真实 Runtime 回归覆盖持久化、Scope 隔离、修订身份、财务同义问法、公司名
匹配、不同页要求和精确引用回查。

完整原始 PDF 检查包含 PepsiCo 2022（503 页）、3M 2022（252 页）、Activision Blizzard 2022
（312 页）、Adobe 2022（99 页）、AES 2022（257 页）。额外四份报告从固定 FinanceBench PDF
目录中具备 2022 年 10-K 的公司按名称排序选取，不依据问题或 gold 选择。

全部 1,423 页以小写 `[a-z]+|\d+` 进行词频多重集合比较，词项数均在独立
`pdftotext -layout -enc UTF-8` 提取结果的 90%–110% 内，逐页词项 F1 最低为 0.981132。
这些是独立提取交叉检查，不等同平台冻结值或标注证据。

全部 1,423 页 observation 通过固定公开 evidence pipeline 入库同一个真实 SQLite Runtime，
重复提交保持幂等。关闭并重开 Runtime 后，对 5 个公开问题和 16 个通用财务查询共返回
420 条精确 citation，逐条通过 `memory.get` 核对正文及原 Source，检查页身份无重复且来自
指定公司的报告。本机单次查询约 0.52–0.72 秒，入库及 flush 约 46.2 秒。此次是本地 Windows
运行，未施加官方容器的 CPU 和内存限制，也不构成通用延迟保证。

本次验证没有使用答案、gold 证据或证据页清单。官方公开及隐藏划分的 evidence-page
Recall@20，以及对平台冻结参考的质量门槛仍未验证。公开验收和独立交叉检查通过不能证明
已经获得 50 分。
