# 首版发布验收记录（未放行）

检查日期：2026-10-04。候选分支：`codex/openspec-acceptance`。结论：**暂不放行正式上线**；14.3 真实模型与搜索联合预发布测试、14.5 运营专家盲评尚未完成，因此 14.6 保持未完成。

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| OpenSpec 严格校验 | 通过 | `openspec validate build-operations-strategy-agent --strict` |
| 后端测试、lint、类型检查 | 通过 | `python -m pytest -q`、`python -m ruff check backend/src backend/tests`、`python -m mypy backend/src backend/tests` |
| 前端构建、单元与浏览器测试 | 通过 | GitHub Actions [run 37210657702](https://github.com/wangy3484-afk/xiaoxiagent/actions/runs/37210657702)，`web-journey` 成功 |
| 离线端到端及 OpenSpec 场景映射 | 通过 | 同一 CI 的 `report-journey` 成功；[14.1 记录](acceptance-offline-journey-14-1.md) |
| 十二黄金场景自动门槛 | 通过 | 同一 CI 的后端集成测试；[14.2 记录](acceptance-golden-14-2.md) |
| 安全与恢复 | 通过 | [14.4 记录](acceptance-security-recovery-14-4.md) |
| 本地容器 smoke | 通过 | 隔离预发布 Compose 的 Proxy、Web、API、Worker、Monitor、PostgreSQL、Redis 全部 healthy；迁移任务退出码 0；HTTPS `/proxy-healthz`、`/health` 与 `/` 均返回 200。 |
| 真实搜索适配器 | 单项通过 | 使用环境中已有的 Tavily 测试密钥运行 `test_tavily_live_smoke_when_explicit_test_key_is_available`，结果通过；不等于四类报告联合验收。 |
| 真实模型与搜索联合预发布 | 待完成 | 目前没有为本服务配置可用的 OpenAI-compatible 模型 API 凭证；不得把 Codex 会话凭证或代理内部凭证作为服务密钥。 |
| 运营专家七维盲评 | 待完成 | 需要真实模型生成的黄金报告和至少两名运营评审者的独立结构化评分；不能用脚本化模型审查替代。 |

下一步：在非 Git 跟踪的预发布环境文件中配置经授权的模型供应商密钥与 Base URL；运行四类场景真实模型/搜索联合 smoke，记录证据链接、权限、token/搜索调用成本和总耗时；再将真实报告匿名交给运营专家盲评。只有阻断项关闭后，才复跑发布检查并更新本记录为正式放行结论。
