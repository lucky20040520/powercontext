# 雾谷镇夜话：守夜人老钟

Dify Chatflow × PowerContext 的互动角色应用。玩家承诺修灯、送酒或透露怕黑等偏好，老钟在后续同一会话里会据此回应。不同会话使用不同档案，不宣称跨新会话记忆。

## 复现入口

主导入文件：**`dify-app.yml`**。

主运行文档：**[docs/运行说明.md](docs/运行说明.md)**。本次使用 Dify 云端完成真实三轮验证，无需 Docker。声明环境是 Windows、Python 3.14.5、固定提交的 PowerContext 和 Dify 云端；DSL 格式 0.7.0。

1. 按运行说明运行 `scripts/setup_demo.ps1`，安装固定版本到 D 盘；已有兼容环境可跳过。
2. 运行 `scripts/start_demo.ps1` 启动独立服务与受限网关。
3. 启动 Cloudflare 临时隧道，使 Dify 云端能连接本机网关。
4. 在 Dify 导入 `dify-app.yml`，配置可用模型、`POWERCONTEXT_URL` 和 Secret 类型的 `POWERCONTEXT_TOKEN`。
5. 打开预览，按三轮样例体验。模型凭据或可用额度须由运行者配置，仓库不包含密钥。

## 真实验证样例

新会话中依次输入：

1. 老钟，我保证明天修好东门的风灯，记号是“青铜灯芯”。
2. 今晚雾真大，你守夜冷不冷？
3. 修灯的事我这两天忙忘了。当时说好的记号是什么？

2026-10-30 实测：三轮均成功，第三轮回答包含“青铜灯芯”。第三轮输入没有泄露该答案。9 个 Dify 节点均成功，PowerContext 响应也包含第一轮的承诺。叙事细节是模型创作；验收关注实际存储并读回的记号。

## 文件用途

| 文件 | 用途 |
|---|---|
| `dify-app.yml` | 主 DSL，环境变量中的本地地址与空密钥须配置 |
| `dify-cloud.yml`、根目录中文 YAML、`workflows/` 下 YAML | 同一 DSL 的兼容副本，内容一致，任选一个导入 |
| `scripts/setup_demo.ps1` | 固定源码提交安装，工具、缓存、Python 和临时目录均放在 D 盘 |
| `scripts/start_demo.ps1`、`scripts/gateway.py` | 鉴权服务与仅开放三个接口的网关 |
| `scripts/capture_context.py` | 按真实 scope_id 导出 PowerContext 请求体和响应，不记录密钥 |
| `docs/运行说明.md` | 环境、依赖、部署、样例、限制与故障定位 |
| `docs/云端运行与真实验证.md` | 本次验证过程与主运行说明的同内容副本 |
| `docs/evidence/` | 真实对话截图、节点执行状态及 PowerContext 响应 |
| `docs/validate_dsl.py` | 可从当前目录独立运行的结构与代码校验 |
| `docs/方案设计.md` | 初始创意背景，具体实现以当前 DSL 与运行说明为准 |
| 其余旧初始化脚本、旧验证记录 | 历史材料，不用于当前云端部署路线；HTTP 模拟不能替代 Dify 端到端证据 |

## 技术实际作用

Dify 负责输入、HTTP 调用、解析、LLM 回复、事件提取、写记忆及输出的核心编排。PowerContext 实际保存和召回玩家事件；LLM 内置聊天记忆关闭，历史从读记忆节点注入。未使用 seekdb；Dify + PowerContext 满足本作品的技术选型。

已修复连线结构、请求头、JSON 请求体、严格数值类型导致的 422、特殊字符序列化和整句词法查询导致的漏召回。检索按本游戏主题生成关键词，最多返回六条 memory，仍有规则覆盖和长对话召回限制。

临时隧道会随本机离线而失效。评审可按说明自行启动；长期在线体验需要持久部署。真实验证不等同于测评平台的评分结果。