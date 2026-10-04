# 14.4 安全与恢复验收记录

执行日期：2026-10-04。环境：Windows 开发主机、隔离的本地 Docker Compose 项目与测试替身；未使用真实供应商密钥或生产数据。

| 验收项 | 执行证据 | 结果 |
| --- | --- | --- |
| 越权访问 | `backend/tests/api/test_authorization.py`、`backend/tests/api/test_report_exports.py` | 未登录请求被拒绝；跨用户报告和导出返回与不存在资源相同的响应。 |
| SSRF | `backend/tests/providers/test_http_fetcher.py` | 本机、内网、云元数据及重定向目标等攻击样例被拒绝。 |
| 网页提示注入 | `backend/tests/workflows/test_case_mechanism_extraction.py::test_page_prompt_injection_cannot_promote_unsupported_effect_to_fact` | 第三方网页中的指令不能因缺少真实支持引文而升格为已核验事实；系统提示明确将网页视作不可信数据。 |
| 重复任务 | `backend/tests/persistence/test_job_state.py` | 并发重复领取只有一次有效执行，终态不被迟到消息回退。 |
| Worker 中断与 checkpoint | `backend/tests/workflows/test_report_graph_recovery.py`、`backend/tests/persistence/test_checkpoints.py`，连接本地 PostgreSQL 运行 | 研究/质量阶段恢复及进程重启后的 checkpoint 恢复均通过。 |
| 备份与恢复 | `.tmp/backup-smoke-13-4` 的完成标记和 SHA-256 清单；隔离项目 `ops-strategy-agent-prod-restore-smoke` 运行 `ops_agent.persistence.backup_validation` | 恢复后的全部业务表计数与摘要、导出文件摘要与大小和备份清单一致；包含 1 个用户、1 份简报、1 份历史报告、1 条证据关联及 1 个导出文件。 |

上述离线安全测试运行结果为 `19 passed, 3 skipped`；跳过的 3 项是需 PostgreSQL 的集成用例，随后设置 `OPS_AGENT_TEST_POSTGRES_ADMIN_URL` 独立运行，结果为 `3 passed`。Ruff 和 MyPy 检查通过。该验收覆盖当前定义的攻击与恢复样例，不代表对任意未来网页提示注入的形式化安全保证；真实供应商端到端检查仍属于 14.3。
