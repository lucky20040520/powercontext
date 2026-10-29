# 十四条 PDF 解析质量自测未达标记录：逐条原因分析

开发分支：`feat/pdf-layout-fallback`。解析源码树 SHA256：`636d58e0f1a84d20d203c19c2666a12a30824b5123352da6dad5ffd488a007eb`。

本文分析的是最近一次完整重解析后的 14 条本地自测未达标记录，**不是比赛官方平台判定的 14 条失败**。数据来自 FinanceBench 固定 revision `cc39aeb4afdf33909ee1412188bf89035950c2eb` 的 84 份完整报告、12,013 页、150 个问题及 189 条证据标注。14 条记录对应 14 个不同物理页，且同时在证据词项召回与全文 F1 两项上未达 0.95，并非 28 个不同页面。

## 1. 判定依据与结论范围

| 检查 | 使用的参考 | 可以得出的结论 |
| --- | --- | --- |
| 证据词项召回 | FinanceBench 原始 `evidence_text` | 按公开证据标注和题面公式的本地自测结果 |
| 标注全文 F1 | FinanceBench 原始 `evidence_text_full_page` | 按公开全文标注和题面公式的本地自测结果 |
| 页面词项数 90%–110% | 本地 Poppler `pdftotext` 独立提取并统计的词数 | 独立数量检查，不能代替平台冻结值 |

原始标注文本已逐条核对：这里只转换文档字段和页码基准，没有修补、清洗或改写 `evidence_text`、`evidence_text_full_page`。全部 189 条标注均重新计算，两项指标均未出现下降。

当前 14 页的评分词频多重集合均与独立 Poppler 结果完全相同。原 PDF 字形坐标进一步显示，许多连写标注对应真实的词间空格、不换行空格或被字体映射为换行的分隔字形。这支持将其列为**需要官方冻结参考核验的词边界差异**，不能直接认定标注或解析器必然错误。

“缺失词项”仅指没有匹配到相同的评分词项，不等于原 PDF 的组成文字一定缺失；“额外词项”同样不等于混入无关正文。比如原页 `Cost of goods sold` 解析为 4 个词，标注 `Costofgoodssold` 为 1 个词，交集会减少，同时产生 1 个缺失词项和 4 个额外词项。

全部 14 条的证据标注与全文标注在本次分词后的多重集合相同。因此下文每条“完整缺失/额外词频”同时适用于该条证据和全文比较，两个指标未达标不能作为两次独立正文丢失来解释。差异中没有数字词项缺失或新增；这项结论限于本轮评分分词。

## 2. 十四条记录总览

| 编号 | 文档 / 物理页 | 证据召回 | 全文 F1 | 当前解析 / 标注词数 | 主因 |
| --- | --- | ---: | ---: | ---: | --- |
| 01 | BESTBUY_2017_10K / 56 | 0.849246 | 0.689796 | 291 / 199 | 词间空白与标注连写差异 |
| 02 | BESTBUY_2019_10K / 52 | 0.834146 | 0.716981 | 272 / 205 | 词间空白与标注连写差异 |
| 03 | BLOCK_2016_10K / 68 | 0.787645 | 0.655949 | 363 / 259 | 词间空白与标注连写差异 |
| 04 | BLOCK_2020_10K / 86 | 0.870722 | 0.772344 | 330 / 263 | 词间空白与标注连写差异 |
| 05 | BLOCK_2020_10K / 90 | 0.831909 | 0.617336 | 595 / 351 | 词间空白与标注连写差异 |
| 06 | CORNING_2020_10K / 70 | 0.827338 | 0.682493 | 198 / 139 | 词间空白与标注连写差异 |
| 07 | CORNING_2020_10K / 72 | 0.805668 | 0.674576 | 343 / 247 | 词间空白与标注连写差异 |
| 08 | CORNING_2021_10K / 65 | 0.801205 | 0.600451 | 277 / 166 | 词间空白与标注连写差异 |
| 09 | CVSHEALTH_2018_10K / 302 | 0.821101 | 0.662963 | 322 / 218 | 词间空白与标注连写差异 |
| 10 | CVSHEALTH_2018_10K / 304 | 0.764706 | 0.630849 | 339 / 238 | 词间空白与标注连写差异 |
| 11 | MGMRESORTS_2018_10K / 57 | 0.945763 | 0.891374 | 331 / 295 | 词间空白与标注连写差异 |
| 12 | MGMRESORTS_2020_10K / 65 | 0.947674 | 0.900552 | 380 / 344 | 原解析问题已修复；剩余词边界差异 |
| 13 | MGMRESORTS_2020_10K / 67 | 0.851441 | 0.686941 | 667 / 451 | 原解析问题已修复；剩余词边界差异 |
| 14 | WALMART_2019_10K / 48 | 0.925926 | 0.812065 | 242 / 189 | 词间空白与标注连写差异 |

## 3. 计算口径

两侧均转小写，以 `[a-z]+|\d+` 分词，保留出现频次。设解析页词频为 P、证据词频为 E、标注全文词频为 G，则证据召回为 `|P∩E| / |E|`，全文 F1 为 `2|P∩G| / (|P|+|G|)`，交集采用多重集合交集。所有阈值保持原值 0.95。

下文每条给出实际交集及分母，词项差异完整列出，不只列举前几项。示例文字按评分口径转为小写；其中 `␠` 表示普通空格，`⍽` 表示 U+00A0 不换行空格，`↵` 表示映射/提取结果中的换行。这些符号仅供报告显示，没有写入生产正文。

## 4. 逐条分析

### 01. BESTBUY_2017_10K：物理页 56

**页面类型：** 合并利润表。**标注标识：** `financebench_id_02608`，该问题第 1 条证据。

**失败表现：** 召回率 `169/199 = 0.849246`；全文 F1 `2×169/(291+199) = 0.689796`，均低于 0.95。当前解析和独立参考均为 291 词项，标注为 199 词项；按独立数量参考，本页数量比例为 100%，通过该独立检查。

**直接原因：** 大量表格行名使用真实的不换行空格，标注则将其连成一个词项。`continuingoperations` 与 `discontinuedoperations` 等差异还出现多次，同一种边界差异重复影响交集。解析端较多的 earnings、operations、income 等来自这些真实短语，不能视为新增无关正文。

**词频影响：** 缺失 27 种词项、合计 30 次；额外 51 种词项、合计 122 次。主要缺失为 `continuingoperations` × 2、`discontinuedoperations` × 2、`pershareattributabletobestbuyco` × 2、`averagecommonsharesoutstanding` × 1、`basicearnings` × 1；主要额外为 `earnings` × 9、`operations` × 8、`income` × 5、`net` × 5、`of` × 5、`to` × 5。

**原 PDF 对照示例：**

| 标注中的连写词项 | 原 PDF 字形文本（仅替换空白显示符号） | 对应字形空白依据 |
| --- | --- | --- |
| `pershareattributabletobestbuyco` | `per⍽share⍽attributable⍽to⍽best⍽buy⍽co` | U+00A0；字形及位置已保存 |
| `discontinuedoperations` | `discontinued⍽operations` | U+00A0；字形及位置已保存 |
| `continuingoperations` | `continuing⍽operations` | U+00A0；字形及位置已保存 |
| `netearningsfromdiscontinuedoperationsattributabletononcontrollinginterests` | `net⍽earnings⍽from⍽discontinued⍽operations⍽attributable⍽to⍽noncontrolling⍽interests` | U+00A0；字形及位置已保存 |

**字符与重绘检查：** 当前输出未发现 NUL 或 Unicode 替代字符；原内容流未提供可用于恢复的 ActualText。0.01 pt 容差下疑似重复为 0 个。

**数量与 F1 的兼容性：** 当前独立参考为 R=291，数量要求 A≥262；标注 G=199。即使标注词项全部匹配，在该数量范围内理论 F1 上限也只有 `0.863341`，低于 0.95。需核对官方冻结词数和标注词边界；这不是对官方合同有误的判定。

**建议处理：** 核对官方冻结全文的词间分隔规则。可独立改善可读性和行结构，但不要把真实多词标签拼成标注中的单词，也不要为减少额外项删除正文。

**完整缺失词项及频次（证据与全文相同）：**

```text
continuingoperations × 2； discontinuedoperations × 2； pershareattributabletobestbuyco × 2；
averagecommonsharesoutstanding × 1； basicearnings × 1； basicearningspershare × 1； costofgoodssold × 1；
dilutedearnings × 1； dilutedearningspershare × 1； earningsfromcontinuingoperationsbeforeincometaxexpense × 1；
fromdiscontinuedoperations × 1； gainonsaleofinvestments × 1； generalandadministrativeexpenses × 1； grossprofit ×
1； incometaxexpense × 1； interestexpense × 1； investmentincomeandother × 1； netearningsattributabletobestbuyco ×
1； netearningsfromcontinuingoperations × 1；
netearningsfromdiscontinuedoperationsattributabletononcontrollinginterests × 1；
netearningsincludingnoncontrollinginterests × 1； netoftaxexpenseof × 1； operatingincome × 1； otherincome × 1；
restructuringcharges × 1； restructuringchargescostofgoodssold × 1； seenotestoconsolidatedfinancialstatements × 1
```

**完整额外词项及频次（相对证据与全文相同）：**

```text
earnings × 9； operations × 8； income × 5； net × 5； of × 5； to × 5； attributable × 4； continuing × 4；
discontinued × 4； expense × 4； from × 4； per × 4； share × 4； best × 3； buy × 3； co × 3； tax × 3； and × 2； basic
× 2； charges × 2； cost × 2； diluted × 2； goods × 2； interests × 2； noncontrolling × 2； other × 2； restructuring
× 2； sold × 2； administrative × 1； average × 1； before × 1； common × 1； consolidated × 1； expenses × 1；
financial × 1； gain × 1； general × 1； gross × 1； including × 1； interest × 1； investment × 1； investments × 1；
notes × 1； on × 1； operating × 1； outstanding × 1； profit × 1； sale × 1； see × 1； shares × 1； statements × 1
```

证据文件：[原始页图](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BESTBUY_2017_10K-p0056/original.png) · [最终解析正文](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BESTBUY_2017_10K-p0056/selected-fixed.txt) · [证据标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BESTBUY_2017_10K-p0056/annotation-evidence.txt) · [全文标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BESTBUY_2017_10K-p0056/annotation-full-page.txt) · [逐字形坐标与字体](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BESTBUY_2017_10K-p0056/chars.json) · [原始绘制操作](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BESTBUY_2017_10K-p0056/raw-operators.txt)

### 02. BESTBUY_2019_10K：物理页 52

**页面类型：** 合并资产负债表。**标注标识：** `financebench_id_04417`，该问题第 1 条证据。

**失败表现：** 召回率 `171/205 = 0.834146`；全文 F1 `2×171/(272+205) = 0.716981`，均低于 0.95。当前解析和独立参考均为 272 词项，标注为 205 词项；按独立数量参考，本页数量比例为 100%，通过该独立检查。

**直接原因：** 资产、负债、股本及页脚说明中的多词标签在标注中连写，例如现金及现金等价物、固定资产、应付及股本说明。`parvalue` 出现两次；解析结果中的 and、current、property、equipment 等是对应真实标签被正常分词后的组成部分。

**词频影响：** 缺失 33 种词项、合计 34 次；额外 70 种词项、合计 101 次。主要缺失为 `parvalue` × 2、`accountspayable` × 1、`accruedcompensationandrelatedexpenses` × 1、`accruedliabilities` × 1、`accumulatedothercomprehensiveincome` × 1；主要额外为 `and` × 9、`current` × 4、`equipment` × 3、`liabilities` × 3、`property` × 3、`total` × 3。

**原 PDF 对照示例：**

| 标注中的连写词项 | 原 PDF 字形文本（仅替换空白显示符号） | 对应字形空白依据 |
| --- | --- | --- |
| `parvalue` | `par⍽value` | U+00A0；字形及位置已保存 |
| `seenotestoconsolidatedfinancialstatements` | `see⍽notes⍽to⍽consolidated⍽financial⍽statements` | U+00A0；字形及位置已保存 |
| `propertyundercapitalandfinancingleases` | `property⍽under⍽capital⍽and⍽financing⍽leases` | U+00A0；字形及位置已保存 |
| `accruedcompensationandrelatedexpenses` | `accrued⍽compensation⍽and⍽related⍽expenses` | U+00A0；字形及位置已保存 |

**字符与重绘检查：** 当前输出未发现 NUL 或 Unicode 替代字符；原内容流未提供可用于恢复的 ActualText。0.01 pt 容差下疑似重复为 0 个。

**数量与 F1 的兼容性：** 当前独立参考为 R=272，数量要求 A≥245；标注 G=205。即使标注词项全部匹配，在该数量范围内理论 F1 上限也只有 `0.911111`，低于 0.95。需核对官方冻结词数和标注词边界；这不是对官方合同有误的判定。

**建议处理：** 核对官方冻结全文的词间分隔规则。可独立改善可读性和行结构，但不要把真实多词标签拼成标注中的单词，也不要为减少额外项删除正文。

**完整缺失词项及频次（证据与全文相同）：**

```text
parvalue × 2； accountspayable × 1； accruedcompensationandrelatedexpenses × 1； accruedliabilities × 1；
accumulatedothercomprehensiveincome × 1； additionalpaid × 1； bestbuyco × 1； billionshares × 1；
cashandcashequivalents × 1； commonstock × 1； currentportionoflong × 1； deferredrevenue × 1； fixturesandequipment
× 1； grosspropertyandequipment × 1； incapital × 1； issuedandoutstanding × 1； issuedandoutstandingnone × 1；
landandbuildings × 1； leaseholdimprovements × 1； lessaccumulateddepreciation × 1； merchandiseinventories × 1；
netpropertyandequipment × 1； othercurrentassets × 1； preferredstock × 1； propertyundercapitalandfinancingleases
× 1； retainedearnings × 1； seenotestoconsolidatedfinancialstatements × 1； termdebt × 1； terminvestments × 1；
totalcurrentassets × 1； totalcurrentliabilities × 1； totalequity × 1； unredeemedgiftcardliabilities × 1
```

**完整额外词项及频次（相对证据与全文相同）：**

```text
and × 9； current × 4； equipment × 3； liabilities × 3； property × 3； total × 3； accrued × 2； accumulated × 2；
assets × 2； capital × 2； cash × 2； issued × 2； other × 2； outstanding × 2； par × 2； stock × 2； term × 2； value ×
2； accounts × 1； additional × 1； best × 1； billion × 1； buildings × 1； buy × 1； card × 1； co × 1； common × 1；
compensation × 1； comprehensive × 1； consolidated × 1； debt × 1； deferred × 1； depreciation × 1； earnings × 1；
equity × 1； equivalents × 1； expenses × 1； financial × 1； financing × 1； fixtures × 1； gift × 1； gross × 1；
improvements × 1； in × 1； income × 1； inventories × 1； investments × 1； land × 1； leasehold × 1； leases × 1；
less × 1； long × 1； merchandise × 1； net × 1； none × 1； notes × 1； of × 1； paid × 1； payable × 1； portion × 1；
preferred × 1； related × 1； retained × 1； revenue × 1； see × 1； shares × 1； statements × 1； to × 1； under × 1；
unredeemed × 1
```

证据文件：[原始页图](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BESTBUY_2019_10K-p0052/original.png) · [最终解析正文](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BESTBUY_2019_10K-p0052/selected-fixed.txt) · [证据标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BESTBUY_2019_10K-p0052/annotation-evidence.txt) · [全文标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BESTBUY_2019_10K-p0052/annotation-full-page.txt) · [逐字形坐标与字体](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BESTBUY_2019_10K-p0052/chars.json) · [原始绘制操作](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BESTBUY_2019_10K-p0052/raw-operators.txt)

### 03. BLOCK_2016_10K：物理页 68

**页面类型：** SQUARE 合并资产负债表。**标注标识：** `financebench_id_04660`，该问题第 1 条证据。

**失败表现：** 召回率 `204/259 = 0.787645`；全文 F1 `2×204/(363+259) = 0.655949`，均低于 0.95。当前解析和独立参考均为 363 词项，标注为 259 词项；按独立数量参考，本页数量比例为 100%，通过该独立检查。

**直接原因：** 除表格行名外，股本说明中的重复短语造成了成倍的词项差异：`anddecember` 缺失频次为 6，`issuedandoutstandingatdecember`、`sharesauthorizedatdecember`、`parvalue` 各为 3。它们对应真实说明的多次出现，不是已证明的重复绘制，不能通过去重处理。

**词频影响：** 缺失 42 种词项、合计 55 次；额外 68 种词项、合计 159 次。主要缺失为 `anddecember` × 6、`issuedandoutstandingatdecember` × 3、`parvalue` × 3、`sharesauthorizedatdecember` × 3、`restrictedcash` × 2；主要额外为 `and` × 14、`december` × 12、`liabilities` × 7、`assets` × 6、`at` × 6、`current` × 6。

**原 PDF 对照示例：**

| 标注中的连写词项 | 原 PDF 字形文本（仅替换空白显示符号） | 对应字形空白依据 |
| --- | --- | --- |
| `anddecember` | `and⍽december` | U+00A0；字形及位置已保存 |
| `issuedandoutstandingatdecember` | `issued⍽and⍽outstanding⍽at⍽december` | U+00A0；字形及位置已保存 |
| `sharesauthorizedatdecember` | `shares⍽authorized⍽at⍽december` | U+00A0；字形及位置已保存 |
| `parvalue` | `par⍽value` | U+00A0；字形及位置已保存 |

**字符与重绘检查：** 当前输出未发现 NUL 或 Unicode 替代字符；原内容流未提供可用于恢复的 ActualText。0.01 pt 容差下疑似重复为 0 个。

**数量与 F1 的兼容性：** 当前独立参考为 R=363，数量要求 A≥327；标注 G=259。即使标注词项全部匹配，在该数量范围内理论 F1 上限也只有 `0.883959`，低于 0.95。需核对官方冻结词数和标注词边界；这不是对官方合同有误的判定。

**建议处理：** 核对官方冻结全文的词间分隔规则。可独立改善可读性和行结构，但不要把真实多词标签拼成标注中的单词，也不要为减少额外项删除正文。 股本说明中的重复短语必须按实际位置保留，不能当作重复绘制去除。

**完整缺失词项及频次（证据与全文相同）：**

```text
anddecember × 6； issuedandoutstandingatdecember × 3； parvalue × 3； sharesauthorizedatdecember × 3；
restrictedcash × 2； terminvestments × 2； accountspayable × 1； accruedexpenses × 1； accruedtransactionlosses × 1；
accumulateddeficit × 1； accumulatedothercomprehensiveloss × 1； acquiredintangibleassets × 1； additionalpaid × 1；
cashandcashequivalents × 1； classacommonstock × 1； classbcommonstock × 1； commitmentsandcontingencies × 1；
consolidatedbalancesheets × 1； currentassets × 1； currentliabilities × 1； customerfundsheld × 1；
customerfundsobligation × 1； customerspayable × 1； incapital × 1； liabilitiesandstockholdersequity × 1；
loansheldforsale × 1； merchantcashadvancereceivable × 1； otherassets × 1； othercurrentassets × 1；
othercurrentliabilities × 1； otherliabilities × 1； preferredstock × 1； propertyandequipment × 1；
seeaccompanyingnotestoconsolidatedfinancialstatements × 1； settlementsreceivable × 1； stockholdersequity × 1；
totalassets × 1； totalcurrentassets × 1； totalcurrentliabilities × 1； totalliabilities × 1；
totalliabilitiesandstockholdersequity × 1； totalstockholdersequity × 1
```

**完整额外词项及频次（相对证据与全文相同）：**

```text
and × 14； december × 12； liabilities × 7； assets × 6； at × 6； current × 6； total × 6； cash × 5； other × 5；
equity × 4； stockholders × 4； authorized × 3； issued × 3； outstanding × 3； par × 3； shares × 3； stock × 3； value
× 3； accrued × 2； accumulated × 2； class × 2； common × 2； consolidated × 2； customer × 2； funds × 2； held × 2；
investments × 2； payable × 2； receivable × 2； restricted × 2； term × 2； a × 1； accompanying × 1； accounts × 1；
acquired × 1； additional × 1； advance × 1； b × 1； balance × 1； capital × 1； commitments × 1； comprehensive × 1；
contingencies × 1； customers × 1； deficit × 1； equipment × 1； equivalents × 1； expenses × 1； financial × 1； for
× 1； in × 1； intangible × 1； loans × 1； loss × 1； losses × 1； merchant × 1； notes × 1； obligation × 1； paid × 1；
preferred × 1； property × 1； sale × 1； see × 1； settlements × 1； sheets × 1； statements × 1； to × 1； transaction
× 1
```

证据文件：[原始页图](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2016_10K-p0068/original.png) · [最终解析正文](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2016_10K-p0068/selected-fixed.txt) · [证据标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2016_10K-p0068/annotation-evidence.txt) · [全文标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2016_10K-p0068/annotation-full-page.txt) · [逐字形坐标与字体](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2016_10K-p0068/chars.json) · [原始绘制操作](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2016_10K-p0068/raw-operators.txt)

### 04. BLOCK_2020_10K：物理页 86

**页面类型：** SQUARE 合并经营报表。**标注标识：** `financebench_id_03838`，该问题第 1 条证据。

**失败表现：** 召回率 `229/263 = 0.870722`；全文 F1 `2×229/(330+263) = 0.772344`，均低于 0.95。当前解析和独立参考均为 330 词项，标注为 263 词项；按独立数量参考，本页数量比例为 100%，通过该独立检查。

**直接原因：** 收入、成本和费用标签在连字符两侧仍有真实词间空白，标注却出现 `basedrevenue`、`basedcosts`、`subscriptionandservices` 等连写词。连字符本身不是问题根因；评分差异来自相邻英文单词是否分开计数，不能删除连字符或空格来迁就标注。

**词频影响：** 缺失 29 种词项、合计 34 次；额外 57 种词项、合计 101 次。主要缺失为 `basedcosts` × 2、`basedrevenue` × 2、`netincome` × 2、`pershare` × 2、`subscriptionandservices` × 2；主要额外为 `revenue` × 7、`income` × 6、`and` × 5、`of` × 5、`based` × 4、`costs` × 4。

**原 PDF 对照示例：**

| 标注中的连写词项 | 原 PDF 字形文本（仅替换空白显示符号） | 对应字形空白依据 |
| --- | --- | --- |
| `subscriptionandservices` | `subscription⍽and⍽services` | U+00A0；字形及位置已保存 |
| `basedrevenue` | `based⍽revenue` | U+00A0；字形及位置已保存 |
| `basedcosts` | `based⍽costs` | U+00A0；字形及位置已保存 |
| `netincome` | `net⍽income` | U+00A0；字形及位置已保存 |

**字符与重绘检查：** 当前输出未发现 NUL 或 Unicode 替代字符；原内容流未提供可用于恢复的 ActualText。0.01 pt 容差下疑似重复为 0 个。

**数量与 F1 的兼容性：** 当前独立参考为 R=330，数量要求 A≥297；标注 G=263。即使标注词项全部匹配，在该数量范围内理论 F1 上限也只有 `0.939286`，低于 0.95。需核对官方冻结词数和标注词边界；这不是对官方合同有误的判定。

**建议处理：** 核对官方冻结全文的词间分隔规则。可独立改善可读性和行结构，但不要把真实多词标签拼成标注中的单词，也不要为减少额外项删除正文。 连字符、负号和金额含义必须保留，不能全局改写金融标签。

**完整缺失词项及频次（证据与全文相同）：**

```text
basedcosts × 2； basedrevenue × 2； netincome × 2； pershare × 2； subscriptionandservices × 2；
amortizationofacquiredcustomerassets × 1； amortizationofacquiredtechnology × 1；
averagesharesusedtocomputenetincome × 1； beforeincometax × 1； bitcoincosts × 1； bitcoinrevenue × 1；
costofrevenue × 1； gainonsaleofassetgroup × 1； generalandadministrative × 1； grossprofit × 1； hardwarecosts × 1；
hardwarerevenue × 1； interestexpense × 1； operatingexpenses × 1； operatingincome × 1； otherexpense × 1；
productdevelopment × 1； provisionforincometaxes × 1； salesandmarketing × 1；
seeaccompanyingnotestoconsolidatedfinancialstatements × 1； totalcostofrevenue × 1； totalnetrevenue × 1；
totaloperatingexpenses × 1； transactionandloanlosses × 1
```

**完整额外词项及频次（相对证据与全文相同）：**

```text
revenue × 7； income × 6； and × 5； of × 5； based × 4； costs × 4； net × 4； operating × 3； total × 3； acquired × 2；
amortization × 2； bitcoin × 2； cost × 2； expense × 2； expenses × 2； hardware × 2； per × 2； services × 2； share ×
2； subscription × 2； to × 2； accompanying × 1； administrative × 1； asset × 1； assets × 1； average × 1； before ×
1； compute × 1； consolidated × 1； customer × 1； development × 1； financial × 1； for × 1； gain × 1； general × 1；
gross × 1； group × 1； interest × 1； loan × 1； losses × 1； marketing × 1； notes × 1； on × 1； other × 1； product ×
1； profit × 1； provision × 1； sale × 1； sales × 1； see × 1； shares × 1； statements × 1； tax × 1； taxes × 1；
technology × 1； transaction × 1； used × 1
```

证据文件：[原始页图](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2020_10K-p0086/original.png) · [最终解析正文](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2020_10K-p0086/selected-fixed.txt) · [证据标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2020_10K-p0086/annotation-evidence.txt) · [全文标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2020_10K-p0086/annotation-full-page.txt) · [逐字形坐标与字体](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2020_10K-p0086/chars.json) · [原始绘制操作](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2020_10K-p0086/raw-operators.txt)

### 05. BLOCK_2020_10K：物理页 90

**页面类型：** SQUARE 合并现金流量表。**标注标识：** `financebench_id_07661`，该问题第 1 条证据。

**失败表现：** 召回率 `292/351 = 0.831909`；全文 F1 `2×292/(595+351) = 0.617336`，均低于 0.95。当前解析和独立参考均为 595 词项，标注为 351 词项；按独立数量参考，本页数量比例为 100%，通过该独立检查。

**直接原因：** 现金流行名与调整项目较长，标注将多个完整短语连成单词，例如净利润调整项及融资现金流说明。每个长连写词既减少标注总词数，又让解析结果中的多个正常词失去交集，因此全文 F1 明显低于证据召回。解析额外项中的 of、cash、from、proceeds 等来自真实行名，并非混入其他页面。

**词频影响：** 缺失 55 种词项、合计 59 次；额外 120 种词项、合计 303 次。主要缺失为 `cashequivalentsandrestrictedcash` × 3、`netcashprovidedby` × 2、`usedin` × 2、`adjustmentstoreconcilenetlosstonetcashprovidedbyoperatingactivities` × 1、`basedcompensation` × 1；主要额外为 `of` × 26、`cash` × 16、`from` × 13、`and` × 12、`proceeds` × 10、`net` × 8。

**原 PDF 对照示例：**

| 标注中的连写词项 | 原 PDF 字形文本（仅替换空白显示符号） | 对应字形空白依据 |
| --- | --- | --- |
| `cashequivalentsandrestrictedcash` | `cash⍽equivalents⍽and⍽restricted⍽cash` | U+00A0；字形及位置已保存 |
| `netcashprovidedby` | `net⍽cash⍽provided⍽by` | U+00A0；字形及位置已保存 |
| `usedin` | `used⍽in` | U+00A0；字形及位置已保存 |
| `proceedsfromtheexerciseofstockoptionsandpurchasesundertheemployeestockpurchaseplan` | `proceeds⍽from⍽the⍽exercise⍽of⍽stock⍽options⍽and⍽purchases⍽under⍽the⍽employee⍽stock⍽purchase⍽plan` | U+00A0；字形及位置已保存 |

**字符与重绘检查：** 当前输出未发现 NUL 或 Unicode 替代字符；原内容流未提供可用于恢复的 ActualText。0.01 pt 容差下疑似重复为 0 个。

**数量与 F1 的兼容性：** 当前独立参考为 R=595，数量要求 A≥536；标注 G=351。即使标注词项全部匹配，在该数量范围内理论 F1 上限也只有 `0.791432`，低于 0.95。需核对官方冻结词数和标注词边界；这不是对官方合同有误的判定。

**建议处理：** 核对官方冻结全文的词间分隔规则。可独立改善可读性和行结构，但不要把真实多词标签拼成标注中的单词，也不要为减少额外项删除正文。

**完整缺失词项及频次（证据与全文相同）：**

```text
cashequivalentsandrestrictedcash × 3； netcashprovidedby × 2； usedin × 2；
adjustmentstoreconcilenetlosstonetcashprovidedbyoperatingactivities × 1； basedcompensation × 1；
beginningoftheyear × 1； businesscombinations × 1； cashinterestandother × 1； cashleaseexpense × 1；
changeindeferredincometaxes × 1； changesinoperatingassetsandliabilities × 1； customerfunds × 1； customerspayable
× 1； depreciationandamortization × 1； effectofforeignexchangerateoncashandcashequivalents × 1； endoftheyear × 1；
financingactivities × 1； gainonsaleofassetgroup × 1； incash × 1； investingactivities × 1；
lossonextinguishmentoflong × 1； netcashprovidedbyoperatingactivities × 1； netincome × 1； netincrease × 1；
netofcashacquired × 1； offstoaccruedtransactionlosses × 1； onrevaluationofequityinvestment × 1；
otherassetsandliabilities × 1； otherfinancingactivities × 1；
paymentsfortaxwithholdingrelatedtovestingofrestrictedstockunits × 1； principalpaymentonconversionofseniornotes ×
1； proceedsfromissuanceofconvertibleseniornotes × 1； proceedsfromissuanceofwarrants × 1；
proceedsfrommaturitiesofmarketabledebtsecurities × 1；
proceedsfrommaturitiesofmarketabledebtsecuritiesfromcustomerfunds × 1； proceedsfrompppliquidityfacilityadvances
× 1； proceedsfromsaleofassetgroup × 1； proceedsfromsaleofequityinvestment × 1；
proceedsfromsaleofmarketabledebtsecurities × 1； proceedsfromsaleofmarketabledebtsecuritiesfromcustomerfunds × 1；
proceedsfromtheexerciseofstockoptionsandpurchasesundertheemployeestockpurchaseplan × 1；
purchaseofconvertibleseniornotehedges × 1； purchaseofintangibleassets × 1； purchaseofloansheldforsale × 1；
purchaseofmarketabledebtsecurities × 1； purchaseofmarketabledebtsecuritiesfromcustomerfunds × 1；
purchaseofotherinvestments × 1； purchaseofpropertyandequipment × 1；
replacementstockawardsissuedinconnectionwithacquisition × 1； salesandprincipalpaymentsofloansheldforsale × 1；
seeaccompanyingnotestoconsolidatedfinancialstatements × 1； settlementspayable × 1； settlementsreceivable × 1；
termdebt × 1； transactionandloanlosses × 1
```

**完整额外词项及频次（相对证据与全文相同）：**

```text
of × 26； cash × 16； from × 13； and × 12； proceeds × 10； net × 8； purchase × 8； debt × 7； sale × 7； in × 6；
marketable × 6； securities × 6； activities × 5； on × 5； to × 5； by × 4； customer × 4； equivalents × 4； funds ×
4； other × 4； provided × 4； restricted × 4； stock × 4； the × 4； assets × 3； for × 3； notes × 3； operating × 3；
senior × 3； asset × 2； convertible × 2； equity × 2； financing × 2； group × 2； held × 2； income × 2； investment ×
2； issuance × 2； liabilities × 2； loans × 2； loss × 2； losses × 2； maturities × 2； payable × 2； payments × 2；
principal × 2； settlements × 2； transaction × 2； used × 2； year × 2； accompanying × 1； accrued × 1； acquired ×
1； acquisition × 1； adjustments × 1； advances × 1； amortization × 1； awards × 1； based × 1； beginning × 1；
business × 1； change × 1； changes × 1； combinations × 1； compensation × 1； connection × 1； consolidated × 1；
conversion × 1； customers × 1； deferred × 1； depreciation × 1； effect × 1； employee × 1； end × 1； equipment × 1；
exchange × 1； exercise × 1； expense × 1； extinguishment × 1； facility × 1； financial × 1； foreign × 1； gain × 1；
hedges × 1； increase × 1； intangible × 1； interest × 1； investing × 1； investments × 1； issued × 1； lease × 1；
liquidity × 1； loan × 1； long × 1； note × 1； offs × 1； options × 1； payment × 1； plan × 1； ppp × 1； property ×
1； purchases × 1； rate × 1； receivable × 1； reconcile × 1； related × 1； replacement × 1； revaluation × 1； sales
× 1； see × 1； statements × 1； tax × 1； taxes × 1； term × 1； under × 1； units × 1； vesting × 1； warrants × 1；
with × 1； withholding × 1
```

证据文件：[原始页图](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2020_10K-p0090/original.png) · [最终解析正文](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2020_10K-p0090/selected-fixed.txt) · [证据标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2020_10K-p0090/annotation-evidence.txt) · [全文标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2020_10K-p0090/annotation-full-page.txt) · [逐字形坐标与字体](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2020_10K-p0090/chars.json) · [原始绘制操作](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/BLOCK_2020_10K-p0090/raw-operators.txt)

### 06. CORNING_2020_10K：物理页 70

**页面类型：** 合并利润表。**标注标识：** `financebench_id_10130`，该问题第 1 条证据。

**失败表现：** 召回率 `115/139 = 0.827338`；全文 F1 `2×115/(198+139) = 0.682493`，均低于 0.95。当前解析和独立参考均为 198 词项，标注为 139 词项；按独立数量参考，本页数量比例为 100%，通过该独立检查。

**直接原因：** 收入、费用、每股收益及页脚说明中的真实不换行空格与标注连写不一致。页脚长句被当作一个标注词项时，解析中的多个普通英文词都会计入额外项。较宽容差下检测到的 8 个疑似重复是位置相差约 0.671 pt 的空白字形，没有证据支持删除真实正文。

**词频影响：** 缺失 24 种词项、合计 24 次；额外 57 种词项、合计 83 次。主要缺失为 `amortizationofpurchasedintangibles` × 1、`corningincorporated` × 1、`costofsales` × 1、`developmentandengineeringexpenses` × 1、`earningsofaffiliatedcompanies` × 1；主要额外为 `income` × 6、`of` × 4、`earnings` × 3、`expenses` × 3、`and` × 2、`attributable` × 2。

**原 PDF 对照示例：**

| 标注中的连写词项 | 原 PDF 字形文本（仅替换空白显示符号） | 对应字形空白依据 |
| --- | --- | --- |
| `theaccompanyingnotesareanintegralpartoftheseconsolidatedfinancialstatements` | `the⍽accompanying⍽notes⍽are⍽an⍽integral⍽part⍽of⍽these⍽consolidated⍽financial⍽statements` | U+00A0；字形及位置已保存 |
| `netincomeattributabletocorningincorporated` | `net⍽income⍽attributable⍽to⍽corning⍽incorporated` | U+00A0；字形及位置已保存 |
| `earningspercommonshareattributableto` | `earnings⍽per⍽common⍽share⍽attributable⍽to` | U+00A0；字形及位置已保存 |
| `amortizationofpurchasedintangibles` | `amortization⍽of⍽purchased⍽intangibles` | U+00A0；字形及位置已保存 |

**字符与重绘检查：** 当前输出未发现 NUL 或 Unicode 替代字符；原内容流未提供可用于恢复的 ActualText。0.01 pt 容差下疑似重复为 0 个。
1 pt 容差下报告 8 个疑似重复；已有坐标检查确认这些是位置不同的空白字形，不能据此删除正文。

**数量与 F1 的兼容性：** 当前独立参考为 R=198，数量要求 A≥179；标注 G=139。即使标注词项全部匹配，在该数量范围内理论 F1 上限也只有 `0.874214`，低于 0.95。需核对官方冻结词数和标注词边界；这不是对官方合同有误的判定。

**建议处理：** 核对官方冻结全文的词间分隔规则。可独立改善可读性和行结构，但不要把真实多词标签拼成标注中的单词，也不要为减少额外项删除正文。

**完整缺失词项及频次（证据与全文相同）：**

```text
amortizationofpurchasedintangibles × 1； corningincorporated × 1； costofsales × 1；
developmentandengineeringexpenses × 1； earningsofaffiliatedcompanies × 1； earningspercommonshareattributableto ×
1； equityin × 1； exceptpershareamounts × 1； generalandadministrativeexpenses × 1； grossmargin × 1；
incomebeforeincometaxes × 1； inmillions × 1； interestexpense × 1； interestincome × 1；
netincomeattributabletocorningincorporated × 1； netsales × 1； operatingexpenses × 1； operatingincome × 1；
otherexpense × 1； provisionforincometaxes × 1； relatedgain × 1；
theaccompanyingnotesareanintegralpartoftheseconsolidatedfinancialstatements × 1； translatedearningscontract × 1；
yearendeddecember × 1
```

**完整额外词项及频次（相对证据与全文相同）：**

```text
income × 6； of × 4； earnings × 3； expenses × 3； and × 2； attributable × 2； corning × 2； expense × 2； in × 2；
incorporated × 2； interest × 2； net × 2； operating × 2； per × 2； sales × 2； share × 2； taxes × 2； to × 2；
accompanying × 1； administrative × 1； affiliated × 1； amortization × 1； amounts × 1； an × 1； are × 1； before ×
1； common × 1； companies × 1； consolidated × 1； contract × 1； cost × 1； december × 1； development × 1； ended ×
1； engineering × 1； equity × 1； except × 1； financial × 1； for × 1； gain × 1； general × 1； gross × 1；
intangibles × 1； integral × 1； margin × 1； millions × 1； notes × 1； other × 1； part × 1； provision × 1；
purchased × 1； related × 1； statements × 1； the × 1； these × 1； translated × 1； year × 1
```

证据文件：[原始页图](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2020_10K-p0070/original.png) · [最终解析正文](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2020_10K-p0070/selected-fixed.txt) · [证据标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2020_10K-p0070/annotation-evidence.txt) · [全文标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2020_10K-p0070/annotation-full-page.txt) · [逐字形坐标与字体](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2020_10K-p0070/chars.json) · [原始绘制操作](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2020_10K-p0070/raw-operators.txt)

### 07. CORNING_2020_10K：物理页 72

**页面类型：** 合并资产负债表。**标注标识：** `financebench_id_10130`，该问题第 2 条证据。

**失败表现：** 召回率 `199/247 = 0.805668`；全文 F1 `2×199/(343+247) = 0.674576`，均低于 0.95。当前解析和独立参考均为 343 词项，标注为 247 词项；按独立数量参考，本页数量比例为 100%，通过该独立检查。

**直接原因：** 资产负债项目及股本授权、发行说明中的多词短语在标注中连写，典型差异为 `sharesauthorized`、`sharesissued`、`millionand`。该页不是现金流量表。较宽容差下的 5 个疑似重复同样是纵向位置不同的空白字形，不构成可删除正文的依据。

**词频影响：** 缺失 44 种词项、合计 48 次；额外 82 种词项、合计 144 次。主要缺失为 `millionand` × 2、`pershare` × 2、`sharesauthorized` × 2、`sharesissued` × 2、`accountspayable` × 1；主要额外为 `and` × 7、`other` × 7、`current` × 6、`assets` × 5、`liabilities` × 5、`shares` × 5。

**原 PDF 对照示例：**

| 标注中的连写词项 | 原 PDF 字形文本（仅替换空白显示符号） | 对应字形空白依据 |
| --- | --- | --- |
| `sharesauthorized` | `shares⍽authorized` | U+00A0；字形及位置已保存 |
| `sharesissued` | `shares⍽issued` | U+00A0；字形及位置已保存 |
| `millionand` | `million⍽and` | U+00A0；字形及位置已保存 |
| `pershare` | `per⍽share` | U+00A0；字形及位置已保存 |

**字符与重绘检查：** 当前输出未发现 NUL 或 Unicode 替代字符；原内容流未提供可用于恢复的 ActualText。0.01 pt 容差下疑似重复为 0 个。
1 pt 容差下报告 5 个疑似重复；已有坐标检查确认这些是位置不同的空白字形，不能据此删除正文。

**数量与 F1 的兼容性：** 当前独立参考为 R=343，数量要求 A≥309；标注 G=247。即使标注词项全部匹配，在该数量范围内理论 F1 上限也只有 `0.888489`，低于 0.95。需核对官方冻结词数和标注词边界；这不是对官方合同有误的判定。

**建议处理：** 核对官方冻结全文的词间分隔规则。可独立改善可读性和行结构，但不要把真实多词标签拼成标注中的单词，也不要为减少额外项删除正文。

**完整缺失词项及频次（证据与全文相同）：**

```text
millionand × 2； pershare × 2； sharesauthorized × 2； sharesissued × 2； accountspayable × 1；
accumulatedothercomprehensiveloss × 1； additionalpaid × 1； atcost × 1； cashandcashequivalents × 1；
commonstockparvalue × 1； contingenciesandguarantees × 1； convertiblepreferredstock × 1； currentassets × 1；
currentliabilities × 1； currentportionoflong × 1； deferredincometaxes × 1； exceptshareandpershareamounts × 1；
incapitalcommonstock × 1； inmillions × 1； netofaccumulateddepreciation × 1； netofdoubtfulaccounts × 1；
noncontrollinginterests × 1； otheraccruedliabilities × 1； otherassets × 1； othercurrentassets × 1；
otherintangibleassets × 1； otherliabilities × 1； plantandequipment × 1； postretirementbenefitsotherthanpensions
× 1； retainedearnings × 1； seriesaparvalue × 1； shareholdersequity × 1； sharesheld × 1； termborrowings × 1；
termdebt × 1； termdebtandshort × 1； theaccompanyingnotesareanintegralpartoftheseconsolidatedfinancialstatements
× 1； totalcorningincorporatedshareholdersequity × 1； totalcurrentassets × 1； totalcurrentliabilities × 1；
totalequity × 1； totalliabilities × 1； tradeaccountsreceivable × 1； treasurystock × 1
```

**完整额外词项及频次（相对证据与全文相同）：**

```text
and × 7； other × 7； current × 6； assets × 5； liabilities × 5； shares × 5； total × 5； of × 4； share × 4； stock ×
4； accounts × 3； equity × 3； per × 3； term × 3； accumulated × 2； authorized × 2； cash × 2； common × 2； debt × 2；
in × 2； issued × 2； million × 2； net × 2； par × 2； shareholders × 2； value × 2； a × 1； accompanying × 1； accrued
× 1； additional × 1； amounts × 1； an × 1； are × 1； at × 1； benefits × 1； borrowings × 1； capital × 1；
comprehensive × 1； consolidated × 1； contingencies × 1； convertible × 1； corning × 1； cost × 1； deferred × 1；
depreciation × 1； doubtful × 1； earnings × 1； equipment × 1； equivalents × 1； except × 1； financial × 1；
guarantees × 1； held × 1； income × 1； incorporated × 1； intangible × 1； integral × 1； interests × 1； long × 1；
loss × 1； millions × 1； noncontrolling × 1； notes × 1； paid × 1； part × 1； payable × 1； pensions × 1； plant × 1；
portion × 1； postretirement × 1； preferred × 1； receivable × 1； retained × 1； series × 1； short × 1； statements
× 1； taxes × 1； than × 1； the × 1； these × 1； trade × 1； treasury × 1
```

证据文件：[原始页图](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2020_10K-p0072/original.png) · [最终解析正文](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2020_10K-p0072/selected-fixed.txt) · [证据标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2020_10K-p0072/annotation-evidence.txt) · [全文标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2020_10K-p0072/annotation-full-page.txt) · [逐字形坐标与字体](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2020_10K-p0072/chars.json) · [原始绘制操作](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2020_10K-p0072/raw-operators.txt)

### 08. CORNING_2021_10K：物理页 65

**页面类型：** 合并利润表。**标注标识：** `financebench_id_02981`，该问题第 1 条证据。

**失败表现：** 召回率 `133/166 = 0.801205`；全文 F1 `2×133/(277+166) = 0.600451`，均低于 0.95。当前解析和独立参考均为 277 词项，标注为 166 词项；按独立数量参考，本页数量比例为 100%，通过该独立检查。

**直接原因：** 净利润归属、每股收益和财务报表附注引用等较长短语被连写，导致标注词数相对完整解析显著减少。当前 F1 是这 14 条中最低的一条，但低分本身不能证明丢失了最多正文：这里的主要可见差异是同一组真实文字采用了不同的词边界。

**词频影响：** 缺失 32 种词项、合计 33 次；额外 77 种词项、合计 144 次。主要缺失为 `netincomeattributabletocorningincorporated` × 2、`amortizationofpurchasedintangibles` × 1、`andnote` × 1、`costofsales` × 1、`developmentandengineeringexpenses` × 1；主要额外为 `income` × 11、`to` × 8、`of` × 7、`net` × 6、`attributable` × 4、`common` × 4。

**原 PDF 对照示例：**

| 标注中的连写词项 | 原 PDF 字形文本（仅替换空白显示符号） | 对应字形空白依据 |
| --- | --- | --- |
| `netincomeattributabletocorningincorporated` | `net⍽income⍽attributable⍽to⍽corning⍽incorporated` | U+00A0；字形及位置已保存 |
| `theaccompanyingnotesareanintegralpartoftheseconsolidatedfinancialstatements` | `the⍽accompanying⍽notes⍽are⍽an⍽integral⍽part⍽of⍽these⍽consolidated⍽financial⍽statements` | U+00A0；字形及位置已保存 |
| `totheconsolidatedfinancialstatementsforadditionalinformation` | `to⍽the⍽consolidated⍽financial⍽statements⍽for⍽additional⍽information` | U+00A0；字形及位置已保存 |
| `earningspercommonshareattributabletocorningincorporated` | `earnings⍽per⍽common⍽share⍽attributable⍽to⍽corning⍽incorporated` | U+00A0；字形及位置已保存 |

**字符与重绘检查：** 当前输出未发现 NUL 或 Unicode 替代字符；原内容流未提供可用于恢复的 ActualText。0.01 pt 容差下疑似重复为 0 个。

**数量与 F1 的兼容性：** 当前独立参考为 R=277，数量要求 A≥250；标注 G=166。即使标注词项全部匹配，在该数量范围内理论 F1 上限也只有 `0.798077`，低于 0.95。需核对官方冻结词数和标注词边界；这不是对官方合同有误的判定。

**建议处理：** 核对官方冻结全文的词间分隔规则。可独立改善可读性和行结构，但不要把真实多词标签拼成标注中的单词，也不要为减少额外项删除正文。

**完整缺失词项及频次（证据与全文相同）：**

```text
netincomeattributabletocorningincorporated × 2； amortizationofpurchasedintangibles × 1； andnote × 1； costofsales
× 1； developmentandengineeringexpenses × 1； earningspercommonshare × 1；
earningspercommonshareattributabletocorningincorporated × 1； equityinearnings × 1； exceptpershareamounts × 1；
excessconsiderationpaidforredemptionofpreferredstock × 1； generalandadministrativeexpenses × 1； grossmargin × 1；
incomebeforeincometaxes × 1； inmillions × 1； interestexpense × 1； interestincome × 1；
netincomeavailabletocommonshareholders × 1； netsales × 1； ofaffiliatedcompanies × 1； operatingexpenses × 1；
operatingincome × 1； otherincome × 1； provisionforincometaxes × 1；
reconciliationofnetincomeattributabletocorningincorporatedversusnetincomeavailabletocommon × 1； refertonote × 1；
relatedgain × 1； seriesaconvertiblepreferredstockdividend × 1； tableofcontents × 1；
theaccompanyingnotesareanintegralpartoftheseconsolidatedfinancialstatements × 1；
totheconsolidatedfinancialstatementsforadditionalinformation × 1； translatedearningscontractgain × 1；
yearendeddecember × 1
```

**完整额外词项及频次（相对证据与全文相同）：**

```text
income × 11； to × 8； of × 7； net × 6； attributable × 4； common × 4； corning × 4； earnings × 4； incorporated × 4；
and × 3； expenses × 3； for × 3； per × 3； share × 3； available × 2； consolidated × 2； financial × 2； gain × 2； in
× 2； interest × 2； note × 2； operating × 2； preferred × 2； sales × 2； statements × 2； stock × 2； taxes × 2； the
× 2； a × 1； accompanying × 1； additional × 1； administrative × 1； affiliated × 1； amortization × 1； amounts × 1；
an × 1； are × 1； before × 1； companies × 1； consideration × 1； contents × 1； contract × 1； convertible × 1； cost
× 1； december × 1； development × 1； dividend × 1； ended × 1； engineering × 1； equity × 1； except × 1； excess ×
1； expense × 1； general × 1； gross × 1； information × 1； intangibles × 1； integral × 1； margin × 1； millions ×
1； notes × 1； other × 1； paid × 1； part × 1； provision × 1； purchased × 1； reconciliation × 1； redemption × 1；
refer × 1； related × 1； series × 1； shareholders × 1； table × 1； these × 1； translated × 1； versus × 1； year × 1
```

证据文件：[原始页图](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2021_10K-p0065/original.png) · [最终解析正文](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2021_10K-p0065/selected-fixed.txt) · [证据标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2021_10K-p0065/annotation-evidence.txt) · [全文标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2021_10K-p0065/annotation-full-page.txt) · [逐字形坐标与字体](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2021_10K-p0065/chars.json) · [原始绘制操作](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CORNING_2021_10K-p0065/raw-operators.txt)

### 09. CVSHEALTH_2018_10K：物理页 302

**页面类型：** 合并经营报表。**标注标识：** `financebench_id_05915`，该问题第 1 条证据。

**失败表现：** 召回率 `179/218 = 0.821101`；全文 F1 `2×179/(322+218) = 0.662963`，均低于 0.95。当前解析和独立参考均为 322 词项，标注为 218 词项；按独立数量参考，本页数量比例为 100%，通过该独立检查。

**直接原因：** 标题、收益项目、终止经营损益及股东归属短语含有真实不换行空格，标注则将其连写。`netincome`、`attributabletocvshealth`、`lossfromdiscontinuedoperationsattributabletocvshealth` 等词项的组成文字在解析页中存在，但不会与连写标注作为同一个词项匹配。

**词频影响：** 缺失 31 种词项、合计 39 次；额外 58 种词项、合计 143 次。主要缺失为 `netincome` × 4、`attributabletocvshealth` × 3、`fromcontinuingoperationsattributabletocvshealth` × 2、`lossfromdiscontinuedoperationsattributabletocvshealth` × 2、`pershare` × 2；主要额外为 `income` × 9、`to` × 9、`attributable` × 8、`cvs` × 7、`health` × 7、`operations` × 7。

**原 PDF 对照示例：**

| 标注中的连写词项 | 原 PDF 字形文本（仅替换空白显示符号） | 对应字形空白依据 |
| --- | --- | --- |
| `netincome` | `net⍽income` | U+00A0；字形及位置已保存 |
| `attributabletocvshealth` | `attributable⍽to⍽cvs⍽health` | U+00A0；字形及位置已保存 |
| `lossfromdiscontinuedoperationsattributabletocvshealth` | `loss⍽from⍽discontinued⍽operations⍽attributable⍽to⍽cvs⍽health` | U+00A0；字形及位置已保存 |
| `fromcontinuingoperationsattributabletocvshealth` | `from⍽continuing⍽operations⍽attributable⍽to⍽cvs⍽health` | U+00A0；字形及位置已保存 |

**字符与重绘检查：** 当前输出未发现 NUL 或 Unicode 替代字符；原内容流未提供可用于恢复的 ActualText。0.01 pt 容差下疑似重复为 0 个。

**数量与 F1 的兼容性：** 当前独立参考为 R=322，数量要求 A≥290；标注 G=218。即使标注词项全部匹配，在该数量范围内理论 F1 上限也只有 `0.858268`，低于 0.95。需核对官方冻结词数和标注词边界；这不是对官方合同有误的判定。

**建议处理：** 核对官方冻结全文的词间分隔规则。可独立改善可读性和行结构，但不要把真实多词标签拼成标注中的单词，也不要为减少额外项删除正文。

**完整缺失词项及频次（证据与全文相同）：**

```text
netincome × 4； attributabletocvshealth × 3； fromcontinuingoperationsattributabletocvshealth × 2；
lossfromdiscontinuedoperationsattributabletocvshealth × 2； pershare × 2； basicearnings × 1； benefitcosts × 1；
consolidatedstatementsofoperations × 1； costofproductssold × 1； dilutedearnings × 1； dividendsdeclaredpershare ×
1； fortheyearsendeddecember × 1； fromcontinuingoperations × 1； goodwillimpairments × 1；
incomebeforeincometaxprovision × 1； incometaxprovision × 1； interestexpense × 1；
lossattributabletononcontrollinginterests × 1； lossfromdiscontinuedoperations × 1；
lossonearlyextinguishmentofdebt × 1； netinvestmentincome × 1； netoftax × 1； operatingcosts × 1；
operatingexpenses × 1； operatingincome × 1； otherexpense × 1；
seeaccompanyingnotestoconsolidatedfinancialstatements × 1； totaloperatingcosts × 1； totalrevenues × 1；
weightedaveragebasicsharesoutstanding × 1； weightedaveragedilutedsharesoutstanding × 1
```

**完整额外词项及频次（相对证据与全文相同）：**

```text
income × 9； to × 9； attributable × 8； cvs × 7； health × 7； operations × 7； from × 6； net × 6； loss × 5； of × 4；
operating × 4； continuing × 3； costs × 3； discontinued × 3； per × 3； share × 3； tax × 3； average × 2； basic × 2；
consolidated × 2； diluted × 2； earnings × 2； expense × 2； outstanding × 2； provision × 2； shares × 2； statements
× 2； total × 2； weighted × 2； accompanying × 1； before × 1； benefit × 1； cost × 1； debt × 1； december × 1；
declared × 1； dividends × 1； early × 1； ended × 1； expenses × 1； extinguishment × 1； financial × 1； for × 1；
goodwill × 1； impairments × 1； interest × 1； interests × 1； investment × 1； noncontrolling × 1； notes × 1； on ×
1； other × 1； products × 1； revenues × 1； see × 1； sold × 1； the × 1； years × 1
```

证据文件：[原始页图](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CVSHEALTH_2018_10K-p0302/original.png) · [最终解析正文](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CVSHEALTH_2018_10K-p0302/selected-fixed.txt) · [证据标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CVSHEALTH_2018_10K-p0302/annotation-evidence.txt) · [全文标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CVSHEALTH_2018_10K-p0302/annotation-full-page.txt) · [逐字形坐标与字体](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CVSHEALTH_2018_10K-p0302/chars.json) · [原始绘制操作](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CVSHEALTH_2018_10K-p0302/raw-operators.txt)

### 10. CVSHEALTH_2018_10K：物理页 304

**页面类型：** 合并资产负债表。**标注标识：** `financebench_id_05915`，该问题第 2 条证据。

**失败表现：** 召回率 `182/238 = 0.764706`；全文 F1 `2×182/(339+238) = 0.630849`，均低于 0.95。当前解析和独立参考均为 339 词项，标注为 238 词项；按独立数量参考，本页数量比例为 100%，通过该独立检查。

**直接原因：** 长期债务、股份数量和股东权益说明的词边界差异较密集。`termdebt` 缺失 3 次，`otherlong`、`parvalue`、`sharesauthorized`、`sharesissuedand`、`sharesatdecember` 等各出现多次。对应的 shares、total、liabilities、term 等额外词来自真实标签与说明，不能整体删除。

**词频影响：** 缺失 49 种词项、合计 56 次；额外 71 种词项、合计 157 次。主要缺失为 `termdebt` × 3、`otherlong` × 2、`parvalue` × 2、`sharesatdecember` × 2、`sharesauthorized` × 2；主要额外为 `and` × 8、`shares` × 8、`liabilities` × 7、`total` × 7、`assets` × 6、`at` × 6。

**原 PDF 对照示例：**

| 标注中的连写词项 | 原 PDF 字形文本（仅替换空白显示符号） | 对应字形空白依据 |
| --- | --- | --- |
| `termdebt` | `term⍽debt` | U+00A0；字形及位置已保存 |
| `sharesatdecember` | `shares⍽at⍽december` | U+00A0；字形及位置已保存 |
| `sharesauthorized` | `shares⍽authorized` | U+00A0；字形及位置已保存 |
| `sharesissuedand` | `shares⍽issued⍽and` | U+00A0；字形及位置已保存 |

**字符与重绘检查：** 当前输出未发现 NUL 或 Unicode 替代字符；原内容流未提供可用于恢复的 ActualText。0.01 pt 容差下疑似重复为 0 个。

**数量与 F1 的兼容性：** 当前独立参考为 R=339，数量要求 A≥306；标注 G=238。即使标注词项全部匹配，在该数量范围内理论 F1 上限也只有 `0.875000`，低于 0.95。需核对官方冻结词数和标注词边界；这不是对官方合同有误的判定。

**建议处理：** 核对官方冻结全文的词间分隔规则。可独立改善可读性和行结构，但不要把真实多词标签拼成标注中的单词，也不要为减少额外项删除正文。

**完整缺失词项及频次（证据与全文相同）：**

```text
termdebt × 3； otherlong × 2； parvalue × 2； sharesatdecember × 2； sharesauthorized × 2； sharesissuedand × 2；
accountspayable × 1； accountsreceivable × 1； accruedexpenses × 1； accumulatedothercomprehensiveincome × 1；
andcapital × 1； atcost × 1； atdecember × 1； cashandcashequivalents × 1； commitmentsandcontingencies × 1；
commonstock × 1； consolidatedbalancesheets × 1； currentportionoflong × 1； cvshealthshareholdersequity × 1；
deferredincometaxes × 1； healthcarecostspayable × 1； intangibleassets × 1； noncontrollinginterests × 1；
noneissuedoroutstanding × 1； otherassets × 1； othercurrentassets × 1； otherinsuranceliabilities × 1；
pharmacyclaimsanddiscountspayable × 1； policyholdersfunds × 1； preferredstock × 1； propertyandequipment × 1；
retainedearnings × 1； seeaccompanyingnotestoconsolidatedfinancialstatements × 1； separateaccountsassets × 1；
separateaccountsliabilities × 1； shareholdersequity × 1； sharesoutstandingat × 1； sharesoutstandingatdecember ×
1； terminsuranceliabilities × 1； terminvestments × 1； termliabilities × 1； totalassets × 1； totalcurrentassets ×
1； totalcurrentliabilities × 1； totalcvshealthshareholdersequity × 1； totalliabilities × 1；
totalliabilitiesandshareholdersequity × 1； totalshareholdersequity × 1； treasurystock × 1
```

**完整额外词项及频次（相对证据与全文相同）：**

```text
and × 8； shares × 8； liabilities × 7； total × 7； assets × 6； at × 6； other × 6； term × 6； equity × 5；
shareholders × 5； accounts × 4； current × 4； december × 4； debt × 3； health × 3； issued × 3； long × 3；
outstanding × 3； payable × 3； stock × 3； authorized × 2； cash × 2； consolidated × 2； cvs × 2； income × 2；
insurance × 2； par × 2； separate × 2； value × 2； accompanying × 1； accrued × 1； accumulated × 1； balance × 1；
capital × 1； care × 1； claims × 1； commitments × 1； common × 1； comprehensive × 1； contingencies × 1； cost × 1；
costs × 1； deferred × 1； discounts × 1； earnings × 1； equipment × 1； equivalents × 1； expenses × 1； financial ×
1； funds × 1； intangible × 1； interests × 1； investments × 1； noncontrolling × 1； none × 1； notes × 1； of × 1；
or × 1； pharmacy × 1； policyholders × 1； portion × 1； preferred × 1； property × 1； receivable × 1； retained × 1；
see × 1； sheets × 1； statements × 1； taxes × 1； to × 1； treasury × 1
```

证据文件：[原始页图](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CVSHEALTH_2018_10K-p0304/original.png) · [最终解析正文](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CVSHEALTH_2018_10K-p0304/selected-fixed.txt) · [证据标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CVSHEALTH_2018_10K-p0304/annotation-evidence.txt) · [全文标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CVSHEALTH_2018_10K-p0304/annotation-full-page.txt) · [逐字形坐标与字体](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CVSHEALTH_2018_10K-p0304/chars.json) · [原始绘制操作](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/CVSHEALTH_2018_10K-p0304/raw-operators.txt)

### 11. MGMRESORTS_2018_10K：物理页 57

**页面类型：** 合并资产负债表。**标注标识：** `financebench_id_04171`，该问题第 1 条证据。

**失败表现：** 召回率 `279/295 = 0.945763`；全文 F1 `2×279/(331+295) = 0.891374`，均低于 0.95。当前解析和独立参考均为 331 词项，标注为 295 词项；按独立数量参考，本页数量比例为 100%，通过该独立检查。

**直接原因：** 标题、分组标签和页脚在字体映射/默认提取中表现为词间换行，标注把这些相邻单词连成一个词项。真实页面中的公司名、报表名、资产分类和页脚仍是多个单词。当前证据召回接近但仍低于 0.95；把词间换行换成空格可改善阅读格式，却不会改变本轮按字母串分词得到的词频。

**词频影响：** 缺失 16 种词项、合计 16 次；额外 43 种词项、合计 52 次。主要缺失为 `commitmentsandcontingencies` × 1、`consolidatedbalancesheets` × 1、`currentassets` × 1、`currentliabilities` × 1、`deferredincometaxes` × 1；主要额外为 `and` × 4、`assets` × 2、`consolidated` × 2、`current` × 2、`liabilities` × 2、`other` × 2。

**原 PDF 对照示例：**

| 标注中的连写词项 | 原 PDF 字形文本（仅替换空白显示符号） | 对应字形空白依据 |
| --- | --- | --- |
| `theaccompanyingnotesareanintegralpartoftheseconsolidatedfinancialstatements` | `the↵accompanying↵notes↵are↵an↵integral↵part↵of↵these↵consolidated↵financial↵statements` | U+000A；字形及位置已保存 |
| `redeemablenoncontrollinginterests` | `redeemable↵noncontrolling↵interests` | U+000A；字形及位置已保存 |
| `commitmentsandcontingencies` | `commitments↵and↵contingencies` | U+000A；字形及位置已保存 |
| `liabilitiesandstockholders` | `liabilities↵and↵stockholders` | U+000A；字形及位置已保存 |

**字符与重绘检查：** 当前输出未发现 NUL 或 Unicode 替代字符；原内容流未提供可用于恢复的 ActualText。0.01 pt 容差下疑似重复为 0 个。

**数量与 F1 的兼容性：** 在当前独立数量范围内，理论 F1 上限为 `0.994941`，数量条件本身未排除达到 0.95 的可能；但这不证明存在符合真实 PDF 的无损修复方法，不能据此拼接真实单词。

**建议处理：** 核对官方冻结全文的词间分隔规则。可独立改善可读性和行结构，但不要把真实多词标签拼成标注中的单词，也不要为减少额外项删除正文。

**完整缺失词项及频次（证据与全文相同）：**

```text
commitmentsandcontingencies × 1； consolidatedbalancesheets × 1； currentassets × 1； currentliabilities × 1；
deferredincometaxes × 1； exceptsharedata × 1； inthousands × 1； liabilitiesandstockholders × 1；
mgmresortsinternationalandsubsidiaries × 1； otherassets × 1； otherlong × 1； propertyandequipment × 1；
redeemablenoncontrollinginterests × 1； termdebt × 1； termobligations × 1；
theaccompanyingnotesareanintegralpartoftheseconsolidatedfinancialstatements × 1
```

**完整额外词项及频次（相对证据与全文相同）：**

```text
and × 4； assets × 2； consolidated × 2； current × 2； liabilities × 2； other × 2； term × 2； accompanying × 1； an ×
1； are × 1； balance × 1； commitments × 1； contingencies × 1； data × 1； debt × 1； deferred × 1； equipment × 1；
except × 1； financial × 1； in × 1； income × 1； integral × 1； interests × 1； international × 1； long × 1； mgm ×
1； noncontrolling × 1； notes × 1； obligations × 1； of × 1； part × 1； property × 1； redeemable × 1； resorts × 1；
share × 1； sheets × 1； statements × 1； stockholders × 1； subsidiaries × 1； taxes × 1； the × 1； these × 1；
thousands × 1
```

证据文件：[原始页图](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2018_10K-p0057/original.png) · [最终解析正文](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2018_10K-p0057/selected-fixed.txt) · [证据标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2018_10K-p0057/annotation-evidence.txt) · [全文标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2018_10K-p0057/annotation-full-page.txt) · [逐字形坐标与字体](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2018_10K-p0057/chars.json) · [原始绘制操作](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2018_10K-p0057/raw-operators.txt)

### 12. MGMRESORTS_2020_10K：物理页 65

**页面类型：** 合并经营报表。**标注标识：** `financebench_id_03849`，该问题第 1 条证据。

**失败表现：** 召回率 `326/344 = 0.947674`；全文 F1 `2×326/(380+344) = 0.900552`，均低于 0.95。当前解析和独立参考均为 380 词项，标注为 344 词项；按独立数量参考，本页数量比例为 100%，通过该独立检查。

**直接原因：** 该页此前确有真实解析问题：INTERNATIONAL 断词，SUBSIDIARIES 与下一行 CONSOLIDATED 粘连，以及局部短词断行。这些问题已通过字体不换行空格字宽与实际基线修复。当前剩余差异主要是 Food and beverage、Reimbursed costs 等真实多词标签在标注中连写，不应把已修复的标题缺陷继续列为当前失败原因。

**词频影响：** 缺失 15 种词项、合计 18 次；额外 40 种词项、合计 54 次。主要缺失为 `foodandbeverage` × 2、`reimbursedcosts` × 2、`retailandother` × 2、`corporateexpense` × 1、`depreciationandamortization` × 1；主要额外为 `and` × 7、`beverage` × 2、`costs` × 2、`expense` × 2、`food` × 2、`other` × 2。

**原 PDF 对照示例：**

| 标注中的连写词项 | 原 PDF 字形文本（仅替换空白显示符号） | 对应字形空白依据 |
| --- | --- | --- |
| `foodandbeverage` | `food⍽and⍽beverage` | U+00A0；字形及位置已保存 |
| `reimbursedcosts` | `reimbursed⍽costs` | U+00A0；字形及位置已保存 |
| `retailandother` | `retail⍽and⍽other` | U+00A0；字形及位置已保存 |
| `operatingitemsfromunconsolidatedaffiliates` | `operating⍽items⍽from⍽unconsolidated⍽affiliates` | U+00A0；字形及位置已保存 |

**字符与重绘检查：** 当前输出未发现 NUL 或 Unicode 替代字符；原内容流未提供可用于恢复的 ActualText。0.01 pt 容差下疑似重复为 0 个。

**已修复的解析问题与当前剩余问题：** 此前召回 `0.938953`、F1 `0.888583`，本轮均提高。INTERNATIONAL 断词及 SUBSIDIARIES/CONSOLIDATED 跨行粘连已修复；当前不能再用这些旧缺陷解释余下分数。剩余差异应对照表格标签的真实分隔和标注连写核验。

**数量与 F1 的兼容性：** 在当前独立数量范围内，理论 F1 上限为 `1.000000`，数量条件本身未排除达到 0.95 的可能；但这不证明存在符合真实 PDF 的无损修复方法，不能据此拼接真实单词。

**建议处理：** 核对官方冻结全文的词间分隔规则。可独立改善可读性和行结构，但不要把真实多词标签拼成标注中的单词，也不要为减少额外项删除正文。

**完整缺失词项及频次（证据与全文相同）：**

```text
foodandbeverage × 2； reimbursedcosts × 2； retailandother × 2； corporateexpense × 1； depreciationandamortization
× 1； forincometaxes × 1； gainonreittransactions × 1； generalandadministrative × 1； interestexpense × 1；
lossattributabletononcontrollinginterests × 1； netofamountscapitalized × 1；
operatingitemsfromunconsolidatedaffiliates × 1； preopeningandstart × 1； propertytransactions × 1； upexpenses × 1
```

**完整额外词项及频次（相对证据与全文相同）：**

```text
and × 7； beverage × 2； costs × 2； expense × 2； food × 2； other × 2； reimbursed × 2； retail × 2； transactions ×
2； administrative × 1； affiliates × 1； amortization × 1； amounts × 1； attributable × 1； capitalized × 1；
corporate × 1； depreciation × 1； expenses × 1； for × 1； from × 1； gain × 1； general × 1； income × 1； interest ×
1； interests × 1； items × 1； loss × 1； net × 1； noncontrolling × 1； of × 1； on × 1； operating × 1； preopening ×
1； property × 1； reit × 1； start × 1； taxes × 1； to × 1； unconsolidated × 1； up × 1
```

证据文件：[原始页图](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2020_10K-p0065/original.png) · [最终解析正文](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2020_10K-p0065/selected-fixed.txt) · [证据标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2020_10K-p0065/annotation-evidence.txt) · [全文标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2020_10K-p0065/annotation-full-page.txt) · [逐字形坐标与字体](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2020_10K-p0065/chars.json) · [原始绘制操作](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2020_10K-p0065/raw-operators.txt)

### 13. MGMRESORTS_2020_10K：物理页 67

**页面类型：** 合并现金流量表。**标注标识：** `financebench_id_03849`，该问题第 2 条证据。

**失败表现：** 召回率 `384/451 = 0.851441`；全文 F1 `2×384/(667+451) = 0.686941`，均低于 0.95。当前解析和独立参考均为 667 词项，标注为 451 词项；按独立数量参考，本页数量比例为 100%，通过该独立检查。

**直接原因：** 该页此前同样存在标题断词、跨行粘连及局部短词边界错误，现已修复。剩余现金流长行名和项目说明在标注中大量连写，例如 net cash provided by、used in、distributions from unconsolidated affiliates。长标签较多，使全文 F1 的下降比召回率更明显，不能通过删除 cash、of、from 等真实词降低额外项。

**词频影响：** 缺失 59 种词项、合计 67 次；额外 131 种词项、合计 283 次。主要缺失为 `usedin` × 4、`netcashprovidedby` × 3、`distributionsfromunconsolidatedaffiliates` × 2、`netofcashacquired` × 2、`operatingactivities` × 2；主要额外为 `of` × 21、`and` × 12、`net` × 12、`in` × 9、`from` × 8、`cash` × 6。

**原 PDF 对照示例：**

| 标注中的连写词项 | 原 PDF 字形文本（仅替换空白显示符号） | 对应字形空白依据 |
| --- | --- | --- |
| `usedin` | `used⍽in` | U+00A0；字形及位置已保存 |
| `netcashprovidedby` | `net⍽cash⍽provided⍽by` | U+00A0；字形及位置已保存 |
| `distributionsfromunconsolidatedaffiliates` | `distributions⍽from⍽unconsolidated⍽affiliates` | U+00A0；字形及位置已保存 |
| `operatingactivities` | `operating␠activities` | U+0020；字形及位置已保存 |

**字符与重绘检查：** 当前输出未发现 NUL 或 Unicode 替代字符；原内容流未提供可用于恢复的 ActualText。0.01 pt 容差下疑似重复为 0 个。

**已修复的解析问题与当前剩余问题：** 此前召回 `0.844789`、F1 `0.679750`，本轮均提高。INTERNATIONAL 断词及 SUBSIDIARIES/CONSOLIDATED 跨行粘连已修复；当前不能再用这些旧缺陷解释余下分数。剩余差异应对照表格标签的真实分隔和标注连写核验。

**数量与 F1 的兼容性：** 当前独立参考为 R=667，数量要求 A≥601；标注 G=451。即使标注词项全部匹配，在该数量范围内理论 F1 上限也只有 `0.857414`，低于 0.95。需核对官方冻结词数和标注词边界；这不是对官方合同有误的判定。

**建议处理：** 核对官方冻结全文的词间分隔规则。可独立改善可读性和行结构，但不要把真实多词标签拼成标注中的单词，也不要为减少额外项删除正文。

**完整缺失词项及频次（证据与全文相同）：**

```text
usedin × 4； netcashprovidedby × 3； distributionsfromunconsolidatedaffiliates × 2； netofcashacquired × 2；
operatingactivities × 2； accountspayableandaccruedliabilities × 1； accountsreceivable × 1；
acquisitionofempirecitycasino × 1； acquisitionofnorthfield × 1； adjustmentstoreconcilenetincome × 1；
amortizationofdebtdiscounts × 1； basedcompensation × 1； beginningofperiod × 1； capitalexpenditures × 1；
changeinoperatingassetsandliabilities × 1； daysorless × 1； debtissuancecosts × 1； deferredincometaxes × 1；
depreciationandamortization × 1； dispositionsofpropertyandequipment × 1；
distributionstononcontrollinginterestowners × 1； dividendspaidtocommonshareholders × 1； endofperiod × 1；
financingactivities × 1； fromunconsolidatedaffiliates × 1； gainonreittransactions × 1；
incometaxesreceivableandpayable × 1； interestpaid × 1； investingactivities × 1； investmentinbellagiobreitventure
× 1； investmentinmgpbreitventure × 1； investmentsinunconsolidatedaffiliates × 1； issuanceoflong × 1；
issuanceofmgmgrowthpropertiesclassashares × 1； lossonearlyretirementofdebt × 1；
mgpbreitventureassumptionofbridgeloanfacility × 1； netborrowings × 1； netincome × 1； netincreasefortheperiod ×
1； netofamountscapitalized × 1； netofconstructionpayable × 1； noncashleaseexpense × 1；
notereceivablerelatedtosaleofcircuscircuslasvegasandadjacentland × 1； premiumsandissuancecosts × 1；
prepaidexpensesandother × 1； proceedsfrombellagiotransaction × 1； proceedsfromissuanceofbridgeloanfacility × 1；
proceedsfrommandalaybayandmgmgrandlasvegastransaction × 1；
proceedsfromsaleofbusinessunitsandinvestmentinunconsolidatedaffiliate × 1；
proceedsfromsaleofcircuscircuslasvegasandadjacentland × 1； propertytransactions × 1； provisionforcreditlosses ×
1； purchasesofcommonstock × 1； refundsreceived × 1； retirementofseniornotes × 1； stateandforeignincometaxespaid
× 1； termdebt × 1； tonetcashprovidedby × 1； underbankcreditfacilitiesmaturitiesof × 1
```

**完整额外词项及频次（相对证据与全文相同）：**

```text
of × 21； and × 12； net × 12； in × 9； from × 8； cash × 6； income × 5； issuance × 5； proceeds × 5； to × 5；
unconsolidated × 5； activities × 4； affiliates × 4； by × 4； circus × 4； debt × 4； provided × 4； used × 4； breit
× 3； distributions × 3； investment × 3； las × 3； operating × 3； paid × 3； payable × 3； period × 3； receivable ×
3； sale × 3； taxes × 3； vegas × 3； venture × 3； accounts × 2； acquired × 2； acquisition × 2； adjacent × 2；
amortization × 2； bellagio × 2； bridge × 2； common × 2； costs × 2； credit × 2； facility × 2； for × 2； interest ×
2； land × 2； liabilities × 2； loan × 2； mgm × 2； mgp × 2； on × 2； property × 2； retirement × 2； transaction × 2；
transactions × 2； a × 1； accrued × 1； adjustments × 1； affiliate × 1； amounts × 1； assets × 1； assumption × 1；
bank × 1； based × 1； bay × 1； beginning × 1； borrowings × 1； business × 1； capital × 1； capitalized × 1； casino
× 1； change × 1； city × 1； class × 1； compensation × 1； construction × 1； days × 1； deferred × 1； depreciation ×
1； discounts × 1； dispositions × 1； dividends × 1； early × 1； empire × 1； end × 1； equipment × 1； expenditures ×
1； expense × 1； expenses × 1； facilities × 1； financing × 1； foreign × 1； gain × 1； grand × 1； growth × 1；
increase × 1； investing × 1； investments × 1； lease × 1； less × 1； long × 1； loss × 1； losses × 1； mandalay × 1；
maturities × 1； noncash × 1； noncontrolling × 1； northfield × 1； note × 1； notes × 1； or × 1； other × 1； owners
× 1； premiums × 1； prepaid × 1； properties × 1； provision × 1； purchases × 1； received × 1； reconcile × 1；
refunds × 1； reit × 1； related × 1； senior × 1； shareholders × 1； shares × 1； state × 1； stock × 1； term × 1；
the × 1； under × 1； units × 1
```

证据文件：[原始页图](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2020_10K-p0067/original.png) · [最终解析正文](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2020_10K-p0067/selected-fixed.txt) · [证据标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2020_10K-p0067/annotation-evidence.txt) · [全文标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2020_10K-p0067/annotation-full-page.txt) · [逐字形坐标与字体](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2020_10K-p0067/chars.json) · [原始绘制操作](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/MGMRESORTS_2020_10K-p0067/raw-operators.txt)

### 14. WALMART_2019_10K：物理页 48

**页面类型：** 合并利润表。**标注标识：** `financebench_id_04784`，该问题第 1 条证据。

**失败表现：** 召回率 `175/189 = 0.925926`；全文 F1 `2×175/(242+189) = 0.812065`，均低于 0.95。当前解析和独立参考均为 242 词项，标注为 189 词项；按独立数量参考，本页数量比例为 100%，通过该独立检查。

**直接原因：** 标题、表格分组和加粗行名的词间空白在提取中表现为换行，标注则连写；许多普通正文行保留正常空格。这种局部混合边界导致大部分金额仍匹配，但公司名、净利润归属及每股收益等标签不匹配。不能把整页所有空白删除来处理少数标签。

**词频影响：** 缺失 14 种词项、合计 14 次；额外 31 种词项、合计 67 次。主要缺失为 `averagecommonsharesoutstanding` × 1、`basicnetincomepercommonshareattributabletowalmart` × 1、`consolidatednetincome` × 1、`consolidatednetincomeattributabletononcontrollinginterest` × 1、`consolidatednetincomeattributabletowalmart` × 1；主要额外为 `income` × 10、`net` × 6、`common` × 5、`attributable` × 4、`consolidated` × 4、`per` × 4。

**原 PDF 对照示例：**

| 标注中的连写词项 | 原 PDF 字形文本（仅替换空白显示符号） | 对应字形空白依据 |
| --- | --- | --- |
| `consolidatednetincomeattributabletononcontrollinginterest` | `consolidated↵net↵income↵attributable↵to↵noncontrolling↵interest` | U+000A；字形及位置已保存 |
| `dilutednetincomepercommonshareattributabletowalmart` | `diluted↵net↵income↵per↵common↵share↵attributable↵to↵walmart` | U+000A；字形及位置已保存 |
| `basicnetincomepercommonshareattributabletowalmart` | `basic↵net↵income↵per↵common↵share↵attributable↵to↵walmart` | U+000A；字形及位置已保存 |
| `consolidatednetincomeattributabletowalmart` | `consolidated↵net↵income↵attributable↵to↵walmart` | U+000A；字形及位置已保存 |

**字符与重绘检查：** 当前输出未发现 NUL 或 Unicode 替代字符；原内容流未提供可用于恢复的 ActualText。0.01 pt 容差下疑似重复为 0 个。

**数量与 F1 的兼容性：** 当前独立参考为 R=242，数量要求 A≥218；标注 G=189。即使标注词项全部匹配，在该数量范围内理论 F1 上限也只有 `0.928747`，低于 0.95。需核对官方冻结词数和标注词边界；这不是对官方合同有误的判定。

**建议处理：** 核对官方冻结全文的词间分隔规则。可独立改善可读性和行结构，但不要把真实多词标签拼成标注中的单词，也不要为减少额外项删除正文。

**完整缺失词项及频次（证据与全文相同）：**

```text
averagecommonsharesoutstanding × 1； basicnetincomepercommonshareattributabletowalmart × 1； consolidatednetincome
× 1； consolidatednetincomeattributabletononcontrollinginterest × 1； consolidatednetincomeattributabletowalmart ×
1； consolidatedstatementsofincome × 1； costsandexpenses × 1； dilutednetincomepercommonshareattributabletowalmart
× 1； dividendsdeclaredpercommonshare × 1； fiscalyearsendedjanuary × 1； incomebeforeincometaxes × 1；
netincomepercommonshare × 1； operatingincome × 1； walmartinc × 1
```

**完整额外词项及频次（相对证据与全文相同）：**

```text
income × 10； net × 6； common × 5； attributable × 4； consolidated × 4； per × 4； share × 4； to × 4； walmart × 4；
and × 1； average × 1； basic × 1； before × 1； costs × 1； declared × 1； diluted × 1； dividends × 1； ended × 1；
expenses × 1； fiscal × 1； inc × 1； interest × 1； january × 1； noncontrolling × 1； of × 1； operating × 1；
outstanding × 1； shares × 1； statements × 1； taxes × 1； years × 1
```

证据文件：[原始页图](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/WALMART_2019_10K-p0048/original.png) · [最终解析正文](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/WALMART_2019_10K-p0048/selected-fixed.txt) · [证据标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/WALMART_2019_10K-p0048/annotation-evidence.txt) · [全文标注](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/WALMART_2019_10K-p0048/annotation-full-page.txt) · [逐字形坐标与字体](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/WALMART_2019_10K-p0048/chars.json) · [原始绘制操作](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/inspection/WALMART_2019_10K-p0048/raw-operators.txt)

## 5. 总体判断及后续处理

1. **已有证据支持的解析缺陷已经单独区分。** 两张 MGM 2020 页此前的标题断词、跨行粘连与局部断词已修复，指标确实提高；剩余差异不能继续归因于这些旧问题。

2. **当前主要可见差异是词边界，而非已证明的字符缺失或无关正文混入。** 14 页当前评分词频均与独立 Poppler 一致，且 PDF 字形、字体和坐标样例能对应到连写标注的组成文字。多引擎一致只提供交叉验证，不等于官方验收通过。

3. **12 条存在独立数量参考与标注词数的兼容性疑点。** 对其中各页，允许词数范围内的理论 F1 上限低于 0.95。其余 2 条没有被这个数量上限排除，但仍需要真实内容依据，不能直接合词刷分。

4. **需要核验的是参考的词边界约定。** 下一步应取得比赛官方冻结页词数/全文参考及其分词说明，检查是否对不换行空格、字体映射换行、表格行名和页脚采用了统一处理。现在不自行更改评分公式、清洗标注、删除真实空格或向正文添加证据词项。

5. **后续修改仍须全量评估。** 所有生产修复只依赖原 PDF 的 ToUnicode、ActualText、编码、字宽、坐标和绘制状态；修改后继续重算全部 189 条，而不能只检验本报告中的 14 条。

## 6. 可复核数据与本报告校验

本报告直接由保存的最终输出重新计算每页词数、交集、缺失与额外频次。已核验 14 条原始证据文本未被改写、当前结果与独立参考词频相同，且所有公式复算与最终评估记录一致。本次仅生成分析文档，没有修改解析代码、评分阈值或重跑解析。

主要数据：[FinanceBench 原始公开标注](E:/project/powercontext-master/.artifacts/pdf-financebench-long-pages/reference/financebench_open_source.jsonl) · [最终全部指标](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/evaluation.json) · [全部189条前后分数及词频](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/all-189-before-after.json) · [189条参考差异与理论上限](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/annotation-reference-audit.json) · [PDF内部字形证据](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/pdf-internal-evidence.json) · [字符及Source完整性](E:/project/powercontext-master/.artifacts/pdf-annotation-root-causes/invariants.json)

隐藏组、官方冻结参考及比赛正式子集未在本报告中验证；本报告中的“失败”始终指当前公开数据上的本地自测未达标。
