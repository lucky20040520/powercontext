# 本地知识库：端侧向量化 × seekdb 混合检索

> PowerContext 2026 竞赛 · seekdb × 阶跃星辰赛道 · 端侧 AI 推理性能优化与 seekdb 混合检索
> 基线分支：`2026-competition-ecosystem`
> 作品：一个在浏览器本地完成文档向量化、用 seekdb 嵌入式数据库做向量 + 全文混合检索的迷你知识库 Web 应用

## 作品一句话

在浏览器里跑开源 embedding 模型（Transformers.js + ONNX Runtime Web），文档与查询向量全部在你自己的设备上计算；向量、原文与元数据写入 seekdb 嵌入式数据库，由 seekdb 引擎内完成向量 + 全文混合检索（RRF 融合）；WebGPU 可用时优先使用，不可用时自动降级 WASM 并在界面明确提示。

## 文件用途与导入顺序

| 顺序 | 文件 | 用途 |
|---|---|---|
| 0 | `docs/方案设计.md` | 背景：架构、量化方案、seekdb 结构、验收对照（评审可先读） |
| 1 | `scripts/prepare_models.py` | 下载并校验 ONNX embedding 模型（fp32/fp16/int8 三档 × 2 模型），产出 `models/` 与 `docs/模型清单.json` |
| 2 | `server/` | seekdb 嵌入式后端：`npm install`（见 `.npmrc`）→ `npm start` 启动 `http://127.0.0.1:3000` |
| 3 | `app/` | 前端源码（Vite + @huggingface/transformers）；`npm install` → `npm run build` 产出 `app/dist/` |
| 4 | `docs/运行说明.md` | 从零复现：模型准备 → 启动后端 → 打开应用 → 导入语料 → 混合检索 → 评测（评审主文档） |
| 5 | `docs/技术说明.md` | 一页技术说明：模型与量化、端侧运行与降级、seekdb 使用、性能与质量实测 |
| 6 | `docs/验证记录.md`、`docs/测试日志.md`、`data/eval-log-final.json` | 运行证据：完整 12 组评测原始数据（WebGPU/WASM × fp32/fp16/int8 × 中英文模型） |

## 目录结构

```
stepfun/
├── README.md                    # 本文件
├── app/                         # 前端（Vite + Transformers.js）
│   ├── index.html               # 四段 UI：模型配置 / 导入语料 / 混合检索 / 评测
│   ├── vite.config.js           # base './'、dev proxy、build 后拷贝 ort wasm 到 dist/wasm
│   └── src/
│       ├── config.js            # 模型 / 精度注册表（fp32/fp16/int8 文件映射）
│       ├── embed.js             # Transformers.js 封装：WebGPU 优先 + WASM 降级 + 加载/预热计时
│       ├── api.js               # 后端 REST 客户端
│       ├── chunk.js             # 文本分块（段落/句读边界 + 重叠）
│       ├── eval.js              # 评测器：Recall@K / nDCG@K + 分阶段计时 + 热查询中位数
│       └── main.js              # 装配：会话状态、导入、检索、评测矩阵、导出
├── server/                      # seekdb 嵌入式后端（Node + Express）
│   ├── server.js                # 建库建集合、批量 add + refresh_index、hybrid/vector 检索、静态服务
│   ├── spike-seekdb.js          # 冒烟脚本（可复跑，自建独立数据目录）
│   ├── smoke-rest.js            # REST 链路冒烟（可复跑）
│   └── .npmrc                   # legacy-peer-deps=true（seekdb 可选 peer 发布缺陷规避）
├── models/                      # （脚本生成，不入库）fp32/fp16/int8 × bge-small-zh-v1.5、all-MiniLM-L6-v2
├── data/
│   ├── corpus/                  # 示例语料（中文 72 篇、英文 24 篇）
│   ├── eval/                    # 评测集（docs + queries，带相关标注）
│   └── eval-log-final.json      # 12 组评测原始数据（含逐查询明细）
├── docs/
│   ├── 方案设计.md               # 设计定稿
│   ├── 技术说明.md               # 一页技术说明（评审核心）
│   ├── 运行说明.md               # 复现步骤（评审主文档）
│   ├── 验证记录.md               # 实测结论与证据
│   ├── 测试日志.md               # 分阶段原始数据 + 复现方法
│   ├── 模型清单.json / 模型清单.md # 模型来源、版本、SHA-256、体积、压缩比
└── scripts/
    └── prepare_models.py         # 模型下载与校验（hf-mirror 兼容，HF_ENDPOINT 可覆盖）
```

## 快速开始（详见 docs/运行说明.md）

```bash
# 1. 模型：下载 fp32/fp16/int8 三档 × 2 个模型（约 320 MB）
python scripts/prepare_models.py            # 默认走 hf-mirror.com；可 HF_ENDPOINT=https://huggingface.co 覆盖

# 2. 后端：seekdb 嵌入式（首次 npm install 会下载原生绑定）
cd server && npm install && npm start       # 监听 http://127.0.0.1:3000

# 3. 前端（已提供构建产物，改代码后需重新构建）
cd app && npm install && npm run build

# 4. 打开 http://127.0.0.1:3000/
#    - 顶部徽章显示当前推理后端（WEBGPU / WASM）与 seekdb 引擎版本
#    - 加载模型 → 导入示例语料（或粘贴/上传文本）→ 输入查询混合检索
#    - 评测面板可跑单组或 12 组全矩阵（fp32/fp16/int8 × WebGPU/WASM × 中英文），并导出 JSON
```

## 技术结合

- **端侧推理**：`@huggingface/transformers`（Transformers.js）在浏览器本地执行 embedding 推理，模型为 BAAI `bge-small-zh-v1.5`（中文 512 维）与 `all-MiniLM-L6-v2`（英文 384 维）的 Xenova ONNX 转换版；`navigator.gpu.requestAdapter()` 检测 WebGPU，不可用时 `env.backends.onnx.wasm.wasmPaths` 自动降级 WASM。
- **模型量化**：采用官方 ONNX 变体——FP16（`model_fp16.onnx`）与 INT8（`model_quantized.onnx`，Q8 动态量化），压缩比实测 fp16≈1.997×、int8≈3.94×；检索质量用 Recall@K / nDCG@K 在自建评测集上实测对比。
- **seekdb**：嵌入式部署（原生绑定 js-bindings），database `kb`，collection `docs`（HNSW cosine 向量索引 + IK 中文全文索引）；向量由浏览器算好显式传入（`embeddingFunction: null`），`hybridSearch({ query: { whereDocument: {$contains} }, knn: { queryEmbeddings } })` 在引擎内完成全文 + 向量 + RRF 融合；写入后调用 `refresh_index()` 使新文档可检索。
- **运行证据**：`data/eval-log-final.json` 为 12 组真实浏览器评测的完整原始数据（逐查询 Recall/nDCG、分阶段毫秒计时、中位数），覆盖 WebGPU 与强制 WASM 两条路径。

## 提交与评测说明

- 开发分支：`2026-competition-ecosystem`
- 提测：仓库 `https://github.com/lucky20040520/powercontext`，分支 `2026-competition-ecosystem`，commit 以最新推送为准
- 说明：模型文件（`models/`，约 320 MB）不入 git，评审时运行 `scripts/prepare_models.py` 生成（脚本含来源 URL 与 SHA-256 校验清单 `docs/模型清单.json`）
