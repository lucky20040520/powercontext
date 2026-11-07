# PDF 页级证据

安装 `powercontext[pdf]` 后，可通过 pypdf 提取完整物理页。解析器接收原始 PDF 字节和非空白
文档 ID，按顺序返回所有页面，包括空白页。页码从 1 开始，每页携带完整原文件的 SHA-256。
支持空密码权限标记；需要非空密码的文件被拒绝。损坏或无法完整读取的文档在返回页面前整体
以 `ValueError` 失败，不进行扫描件 OCR。页内容和嵌套 Form XObject 的 Flate 数据在提取器
容错恢复之前检查，避免损坏的文本流被静默当作成功解析。

```python
from powercontext.sources.pdf_pages import PDFDocumentInput, parse_pdf_document

pages = parse_pdf_document(PDFDocumentInput(document_id="年度报告", content=pdf_bytes))
```

将 `PDF_PAGE_SOURCE_DEFINITION` 注册到 `SourceDefinitionRegistry`，逐页 resolve，再通过
`project_source_for_transport` 创建 observation。向 Runtime ingestion 注册定义清单，把全部
observation 提交到指定 Scope，并使用保留完整投影正文及 Source 引用的 pipeline 刷新 Memory。
标准 `powercontext.text-evidence@1` 投影正文为 `document_id + "\n" + page.text`，metadata 恰好
包含 `document_id`、`document_sha256`、`page_number`。

Source 身份对文档 ID、完整文件摘要和物理页码的无歧义编码计算摘要，固定为 68 个字符，不依赖
提取正文。PDF 修订产生新的页身份，旧 Source 和 citation 继续对应原修订。物理页码不能与报告
印刷页码混用。

重新打开 Runtime 后即可检索：

```python
from powercontext.sources.pdf_pages import search_pdf_pages
from powercontext.builtin.runtime import GetMemoryEntryRequest

memory = runtime.memory.for_scope(scope_id)
citations = await search_pdf_pages(memory, "What was operating income in 2025?", limit=20)
for citation in citations:
    record = await memory.get(GetMemoryEntryRequest(citation=citation))
```

检索通过公开的 scoped `Memory.list()` 读取有效条目，返回该快照的真实 citation，最多返回
`limit` 个不同页 Source。无关记忆或合并多个 Source 的条目不参与检索。空白问题和非正数
上限返回空元组。

离线排序融合整页 BM25、问题原词与词组、120 词重叠窗口，以及财务报表标题。Unicode 连字和
软连字符只在派生检索视图中归一化。跨行断开的单词在合并结果属于查询或扩展词时连接，普通
复合词的词边界保持不变。捕获的页正文不会被改写。

财务词汇把现金比率、净债务、EBITDA 利润率、ROA、ROE、ROIC、FCF 等指标扩展到支撑科目。
结果窗口的一部分保留不同指标组成部分的优先证据页，避免重复讨论挤掉分母或另一张报表；其余
位置按融合排序补齐。同一报告中近重复的叙述页会被降权，但不会删除页面身份。财务报表、数字
密集表格和不同报告不参与这种叙述去重处理。

公司名从调用方报告身份推导，忽略常见法律后缀和连接词，并支持多词名称的首字母缩写，不使用
公司查找表。明确指定年报或 10-K/10-Q 年份时选择匹配报告；只询问财务年度时，还保留可能载有
对比或重述数据的较新报告。没有对应年份时逐公司回退到其可用报告。没有识别出身份时，整个
Scope 保持可检索。

检索不调用模型或网络，不读取源文件、预解析文件或持久化语料缓存。每次查询读取 scoped Memory
快照，工作量与正文总量及有界候选集的多样性排序有关，适用于题目中 1,151 页规模的小型报告集。

## 验证

使用 Python 3.12 和官方固定依赖运行公开自测：

```sh
make -C competition test-pdf
```

产品行为测试位于 `tests/test_pdf_pages.py` 和 `tests/e2e/test_pdf_page_retrieval.py`，覆盖原子
解析、权限、修订、Scope 隔离、持久化、重启、精确引用回查、财务同义问法与缩写、多页支撑
证据不被讨论页淹没，以及检索字形归一化不改变已保存正文。

`PDF page evidence acceptance` GitHub Actions 工作流在官方容器中执行公开及产品 PDF 测试。
compose 配置限制一颗 CPU、2 GiB 内存，测试时禁用外部网络且只读挂载产品源码；镜像准备阶段
先下载固定依赖。

独立提取检查覆盖十份完整 2022 年原始财报：PepsiCo、3M、Activision Blizzard、Adobe、AES、
Apple、Coca-Cola、Johnson & Johnson、Microsoft、Walmart。全部 2,126 页以小写
`[a-z]+|\d+` 词频多重集合，与 `pdftotext -layout -enc UTF-8` 独立提取结果比较；每页词项数
都在 90%–110% 内，整页词项 F1 最低为 0.981132。这里没有使用平台冻结值或标注证据。

全部 2,126 页 observation 还通过公开 evidence pipeline 提交到同一个真实 SQLite Runtime，
重复提交保持幂等。重启后，35 个公开或通用财务问题返回 700 条精确 citation，逐条通过
`memory.get` 核对原文档、完整 SHA-256、物理页和未改写的证据正文。这组 Windows 检查使用
固定 pypdf 6.19.0，但未施加容器资源限制，观察到的最大检索耗时为 1.875 秒。引用完整性
不等同对标注证据页的召回率。

公开验收和上述检查通过，不能等同平台已经给出 50 分。正式 evidence-page Recall@20 和对标注
证据的质量只能由评测方确认。产品解析及检索过程均不读取答案、gold、证据页清单、预解析正文
或判题资产。


## 字距解析与独立召回验证

解析器检测 PDF `TJ` 数组内微小水平字距引起的错误断词。比较原始提取和合并字距片段后的词项，
只对受影响页面启用布局提取，并要求所有非空白字符完整保留；包含旋转文本，压缩布局填充空白。
普通页面继续使用原有提取结果。原始字节摘要、物理页边界和 Source 身份不随提取模式改变。

检索通过公开 `Memory.search()` 的显式 FTS 模式取得原生候选，再与 `Memory.list()` 的当前快照
页级排序融合。引用始终来自同一真实快照。地域附注、客户与百分比关系、租赁到期和养老金配置
作为有界的披露支持分量参与召回；小返回上限保留主要财务报表的排序。检索视图统一 U.S./US 等缩写，
不改写采集的正文，也不调用向量模型。

`benchmark/pdf_retrieval` 提供从原始 PDF 独立编写的 40 条问题和物理证据页。修复前，第一公司组
召回 14/16 页，其他公司组召回 18/21 页；修复后，本地重启的 2,126 页 Runtime 中分别为 16/16、
21/21，公开问题的独立标注为 9/9。两组均在开发期间复查过，不能当作未接触的隐藏盲测结果。

工作流还在官方禁网、1 核、2 GiB 容器中解析并入库 11 份完整财报，共 2,352 页，核对独立页词项数、
所选页面全文 F1，再运行 40 题召回与精确引用验证。夹具及脚本均在 `src/` 之外，判题产品不会读取它们。
这些独立指标不是组织方 gold 指标，不能据此宣称平台已获得 50 分。
