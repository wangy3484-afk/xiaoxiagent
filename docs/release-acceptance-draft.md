# 首版发布验收记录（未放行）

检查日期：2026-10-06。候选分支：`codex/openspec-acceptance`。结论：**暂不放行正式上线**；14.3 真实模型与搜索联合预发布测试已通过，14.5 两名运营专家盲评尚未完成，因此 14.6 保持未完成。

| 检查项 | 结果 | 证据 |
| --- | --- | --- |
| OpenSpec 严格校验 | 通过 | `openspec validate build-operations-strategy-agent --strict` |
| 后端测试、lint、类型检查 | 通过 | 本地复跑 `python -m pytest -q`、`python -m ruff check backend/src backend/tests scripts`、`python -m mypy backend/src backend/tests scripts`；其中 5 个显式条件测试因缺少对应触发条件而跳过。 |
| 前端构建、单元与浏览器测试 | 通过 | 本地复跑 `npm run lint`、`npm run build`、`npm run test`（12 项）、`npm run test:e2e`（7 项）；另有 GitHub Actions [run 37210657702](https://github.com/wangy3484-afk/xiaoxiagent/actions/runs/37210657702)。 |
| 离线端到端及 OpenSpec 场景映射 | 通过 | 同一 CI 的 `report-journey` 成功；[14.1 记录](acceptance-offline-journey-14-1.md) |
| 十二黄金场景自动门槛 | 通过 | 同一 CI 的后端集成测试；[14.2 记录](acceptance-golden-14-2.md) |
| 安全与恢复 | 通过 | [14.4 记录](acceptance-security-recovery-14-4.md) |
| 本地容器 smoke | 通过 | 隔离预发布 Compose 的 Proxy、Web、API、Worker、Monitor、PostgreSQL、Redis 全部 healthy；迁移任务退出码 0；HTTPS `/proxy-healthz`、`/health` 与 `/` 均返回 200。 |
| 真实搜索适配器 | 单项通过 | 使用环境中已有的 Tavily 测试密钥运行 `test_tavily_live_smoke_when_explicit_test_key_is_available`，结果通过；不等于四类报告联合验收。 |
| 真实模型与搜索联合预发布 | 通过 | DeepSeek `deepseek-flash` 与 Tavily 四场景真实联调均完成报告、原文打开、报告和证据权限检查，并记录耗时、模型成本估算及搜索次数；[14.3 记录](acceptance-live-14-3.md) |
| 运营专家七维盲评 | 待完成 | 需要真实模型生成的黄金报告和至少两名运营评审者的独立结构化评分；不能用脚本化模型审查替代。 |

下一步：将真实报告匿名交给至少两名运营专家独立盲评七个专业维度，记录结构化评分、阻断项、返工负责人和上线结论。只有阻断项关闭后，才复跑发布检查并更新本记录为正式放行结论。测试密钥已用于预发布环境；由于它曾出现在聊天记录中，应在供应商控制台轮换。
