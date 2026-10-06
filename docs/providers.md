# 外部提供商配置与替换指南

系统把外部能力限定在四个异步接口：`ModelProvider`、`SearchProvider`、`PageFetcher` 和 `ContentExtractor`。LangGraph 节点只接收 `ProviderSet`，不得直接导入 OpenAI、Tavily 或 HTTPX 适配器。这样可以在不修改业务节点的情况下替换供应商或使用离线测试替身。

## 默认生产组合

| 能力 | 默认实现 | 主要边界 |
| --- | --- | --- |
| 结构化模型 | OpenAI-compatible Chat Completions | Pydantic schema、总超时、最多两次模式修复、token 用量 |
| Web 搜索 | Tavily Search | 单次最多 20 条、语言过滤、分页窗口、URL 去重、超时 |
| 页面抓取 | 安全 HTTP 抓取器 | 仅 HTTP(S)、逐跳 DNS/SSRF 校验、HTML、大小/重定向/总时长限制 |
| 正文提取 | 确定性 HTML 提取器 | 正文降噪、canonical URL、SHA-256、发布日期或 unknown |

生产组合由 `ops_agent.providers.build_production_providers(settings)` 创建。业务代码不得自行读取环境变量或拼接供应商请求。

## 环境变量

```dotenv
OPS_AGENT_MODEL_PROVIDER=openai-compatible
OPS_AGENT_MODEL_NAME=gpt-4.1-mini
OPS_AGENT_MODEL_BASE_URL=https://api.openai.com/v1
OPS_AGENT_MODEL_API_KEY=replace-at-deploy-time
OPS_AGENT_MODEL_TIMEOUT_SECONDS=90
OPS_AGENT_MODEL_MAX_RETRIES=2
OPS_AGENT_MODEL_STRUCTURED_OUTPUT_MODE=json_schema
OPS_AGENT_MODEL_THINKING_MODE=provider_default

OPS_AGENT_SEARCH_PROVIDER=tavily
OPS_AGENT_SEARCH_BASE_URL=https://api.tavily.com
OPS_AGENT_SEARCH_API_KEY=replace-at-deploy-time
OPS_AGENT_SEARCH_TIMEOUT_SECONDS=20

OPS_AGENT_FETCH_TIMEOUT_SECONDS=15
OPS_AGENT_FETCH_MAX_BYTES=2000000
OPS_AGENT_FETCH_MAX_REDIRECTS=5
```

真实密钥只通过部署环境或密钥管理系统注入，不得写入 `.env.example`、代码、测试 fixture、日志或报告。`Settings.safe_for_logging()` 只提供脱敏配置。开发环境没有密钥时仍可启动基础服务，但创建生产提供商组合会快速失败。

### DeepSeek 预发布配置

DeepSeek 的 Chat Completions JSON Output 使用 `json_object`；本适配器在该模式下把 Pydantic JSON Schema 放入系统消息，并在响应后继续做本地 schema 校验与有界修复。保持默认 `json_schema` 不变，只有对不支持严格 JSON Schema 的供应商才切换模式。根据 [DeepSeek JSON Output 文档](https://api-docs.deepseek.com/guides/json_mode/)，可使用以下**不含密钥**的配置：

```dotenv
OPS_AGENT_MODEL_PROVIDER=openai-compatible
OPS_AGENT_MODEL_NAME=deepseek-flash
OPS_AGENT_MODEL_BASE_URL=https://api.deepseek.com
OPS_AGENT_MODEL_HEALTH_URL=https://api.deepseek.com/models
OPS_AGENT_MODEL_STRUCTURED_OUTPUT_MODE=json_object
OPS_AGENT_MODEL_THINKING_MODE=disabled
```

`OPS_AGENT_MODEL_API_KEY` 仍只通过未纳入 Git 的部署环境注入。可使用显式测试环境变量运行一次最小真实调用：

`OPS_AGENT_MODEL_THINKING_MODE=disabled` 是 DeepSeek 专用请求参数；在当前工作流每次结构化输出有固定 token 上限时，可避免默认思考内容耗尽上限。对其他供应商保持 `provider_default`，除非该供应商明确支持相同参数。

```powershell
.venv\Scripts\python -m pytest -q backend/tests/providers/test_openai_compatible_live.py
```

未设置 `OPS_AGENT_TEST_MODEL_API_KEY` 时该测试跳过。预发布四场景验收还必须使用真实搜索密钥、记录 token 与实际计费口径，并对每份报告人工核验来源；最小调用通过不等于报告验收完成。

## 在测试中替换

使用四个确定性替身组装同一个 `ProviderSet`：

```python
providers = ProviderSet(
    model=DeterministicModelProvider(scripted_outputs),
    search=DeterministicSearchProvider(scripted_results),
    fetcher=DeterministicPageFetcher(scripted_pages),
    extractor=DeterministicContentExtractor(scripted_content),
)
result = await workflow_node(state, providers)
```

业务节点签名保持不变；测试只替换组合根。替身不会访问公网，输出和请求 ID 可重复。契约测试位于 `backend/tests/providers/`。

## 替换模型或搜索供应商

1. 新适配器实现对应 Protocol，输入输出只能使用 `contracts.py` 中的中立模型。
2. 在适配器内部完成供应商字段映射、超时、认证和错误翻译；供应商响应不得泄漏到业务层。
3. 对同一适配器运行成功、零结果、限流/配额、认证、超时、非法响应和密钥脱敏测试。
4. 只在 `wiring.py` 的组合根切换实现；不得修改研究、诊断、策略或报告节点。
5. 如新增配置，更新 `Settings` 与 `.env.example`，但示例值不得包含真实密钥。

## 错误与日志

外部错误使用稳定错误码和五类分类：`transient`、`quota`、`authentication`、`content`、`provider`。只有明确可重试的瞬时错误才设置 `retryable=true`。调用方使用 `log_provider_error()` 记录白名单字段；禁止记录异常链、Authorization 头、完整网页、搜索响应或完整模型响应。

Tavily 的真实冒烟测试默认跳过。只有显式设置独立测试密钥后才运行：

```powershell
$env:OPS_AGENT_TEST_TAVILY_API_KEY = "temporary-test-key"
.venv\Scripts\python -m pytest backend/tests/providers/test_tavily.py -m integration
```

测试结束后立即清理该环境变量并按公司密钥策略轮换临时凭据。
