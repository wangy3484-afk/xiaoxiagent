# 14.1 离线全流程验收记录

执行日期：2026-10-04。GitHub Actions：[Offline report journey / run 37209566689](https://github.com/wangy3484-afk/xiaoxiagent/actions/runs/37209566689)，提交 `c4b11205121ba0b01f1f8b590e67aefeb9c8f500`，分支 `codex/openspec-acceptance`。`report-journey` 与 `web-journey` 两个 CI 作业均成功。

- 后端 `backend/tests/integration/test_full_journey.py` 使用确定性模型、搜索、抓取和正文提取替身，贯通登录、模糊场景、澄清/修改、确认、报告任务、研究、专项策略、质量修订、版本持久化、Markdown/PDF 导出和文件校验和。
- `backend/tests/integration/test_spec_scenario_mapping.py` 校验五份 OpenSpec 能力规格中的全部 57 个场景均映射至现有测试；对应关系见 [场景测试映射](openspec-scenario-tests.yaml)。
- 前端作业运行构建、Vitest 和 Playwright，覆盖浏览器录入、状态恢复、报告历史及导出等用户路径。

该 CI 使用离线测试供应商，不替代 14.3 的真实模型与真实搜索服务预发布测试。
