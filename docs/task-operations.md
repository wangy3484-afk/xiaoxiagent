# 报告任务状态、错误码与运维排障

本文面向开发和运维人员，用于判断报告任务当前处于什么状态、为什么失败，以及如何在不破坏 checkpoint 和历史报告的前提下恢复服务。

## 1. 关联标识

一次报告生成使用三类标识：

| 标识 | 来源 | 用途 |
| --- | --- | --- |
| `request_id` | API 接收合法 `X-Request-ID`，否则生成 UUID | 关联前端请求、任务创建与 Worker 日志 |
| `job_id` | 报告任务主键 | 查询状态、事件和报告输出；Celery 消息只携带该值 |
| `thread_id` | 与 `job_id` 相同 | 定位 LangGraph PostgreSQL checkpoint |

API 会在响应的 `X-Request-ID` 头中返回最终采用的标识。日志是单行 JSON，可按任一标识筛选，但不会记录密钥、Cookie、完整用户输入、完整网页正文或完整模型响应。

```powershell
docker compose logs api worker | Select-String '"job_id": "<JOB_ID>"'
docker compose logs api worker | Select-String '"request_id": "<REQUEST_ID>"'
```

## 2. 任务状态与阶段

| 状态 | 含义 | 是否终态 | 用户动作 |
| --- | --- | --- | --- |
| `queued` | 已写入数据库，等待 Worker | 否 | 正常等待；长时间不变时检查 Redis/Worker |
| `running` | Worker 已领取，图正在执行或可从 checkpoint 继续 | 否 | 查看 `stage`、事件和节点日志 |
| `retryable` | 瞬时外部错误已达到自动重试上限 | 否 | 外部服务恢复后，以新的幂等键重新生成 |
| `completed` | 报告版本已持久化 | 是 | 读取 `report_version_ids` |
| `failed` | 配置、认证、配额、内容安全或不可恢复错误 | 是 | 按错误码修复后重新生成 |
| `cancelled` | 任务被明确取消 | 是 | 如仍需要报告，创建新任务 |

主要阶段依次为 `queued`、`initializing`、`load_context`、`research`、`diagnosis`、`strategy`、`planning`、`assembly`、`quality`、`finalize`、`completed`。质量审查可能定向返回前序阶段，最多两轮；这不是任务回退异常。

查询任务和最近事件：

```powershell
$job = Invoke-RestMethod "http://localhost:8000/api/v1/jobs/<JOB_ID>" -WebSession $session
$events = Invoke-RestMethod "http://localhost:8000/api/v1/jobs/<JOB_ID>/events?limit=100" -WebSession $session
$job | ConvertTo-Json -Depth 6
$events | ConvertTo-Json -Depth 6
```

状态接口只返回可向用户展示的失败说明，不返回供应商原始响应或内部堆栈。

## 3. 稳定错误码

| 错误码 | 典型状态 | 含义与处理 |
| --- | --- | --- |
| `JOB_QUEUE_UNAVAILABLE` | `failed / queue_error` | Redis 或 Celery 发布失败；先恢复队列，再使用新的幂等键创建任务 |
| `PROVIDER_NOT_CONFIGURED` | `failed / configuration_error` | 模型或搜索密钥缺失；检查环境配置并重建容器 |
| `PROVIDER_RATE_LIMITED` | `retryable / retryable_error` | 搜索或模型被限流；等待窗口恢复并重新生成 |
| `PROVIDER_TIMEOUT` | `retryable / retryable_error` | 外部调用连续超时；检查网络和供应商状态 |
| `PROVIDER_QUOTA_EXHAUSTED` | `failed` | 配额耗尽；补充配额或切换配置后重新生成 |
| `PROVIDER_AUTHENTICATION_ERROR` | `failed` | 供应商凭据无效；轮换密钥并重启 API/Worker |
| `PROVIDER_RESPONSE_ERROR` | `retryable` 或 `failed` | 供应商响应异常；以事件中的状态判断是否可重试 |
| `PROVIDER_SCHEMA_ERROR` | `failed` | 模型在两次结构修复后仍不符合 schema；检查模型兼容性 |
| `UNSAFE_URL` | `failed` | 来源触发 SSRF/保留地址保护；不得绕过安全校验 |
| `CONTENT_REJECTED` | `failed` | 响应大小、类型或安全规则不允许处理 |
| `CONTENT_EXTRACTION_FAILED` | `failed` | 页面无法提取正文；更换公开来源 |

创建接口还可能返回 `IDEMPOTENCY_CONFLICT`、`IDEMPOTENCY_REQUEST_IN_PROGRESS`、`BRIEF_NOT_CONFIRMED`、`BRIEF_REVISION_UNCHANGED` 和 `RESOURCE_NOT_FOUND`。这些属于请求契约问题，不应通过重启 Worker 解决。

## 4. 搜索限流排障

现象：任务为 `retryable`，阶段为 `retryable_error`，错误码为 `PROVIDER_RATE_LIMITED`。

1. 用任务状态和事件接口确认错误码，避免仅依据前端提示判断。
2. 按 `job_id` 查看 Worker 日志，确认自动重试次数以及供应商 `request_id`；日志中不应出现搜索密钥或查询全文。
3. 检查供应商限流窗口、账号配额和并发配置。不要无限提高 Celery 重试次数。
4. 服务恢复后，基于原已确认简报使用新的幂等键创建任务；旧任务和事件保留用于审计。

可在离线测试环境复现同一状态转换：

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/test_job_execution.py -k search_rate_limit -vv
```

测试应显示 3 次调用（首次加两次有界重试），最终状态为 `retryable`，并生成 `provider_error` 事件。

## 5. Worker 中断与 checkpoint 恢复

现象：任务长时间停留在 `running`，Worker 日志在某个 `graph_node_started` 后中断，且没有对应的 `graph_node_completed`。

1. 运行 `docker compose ps`，确认 PostgreSQL、Redis 与 Worker 健康。
2. 按 `job_id` 检查最后一个节点事件。已经完成并落盘的节点不得手工回退状态或删除 checkpoint。
3. 执行 `docker compose restart worker`。同一 `job_id/thread_id` 会获取数据库锁并从 PostgreSQL checkpoint 恢复；若进程在首个 checkpoint 前终止，会从初始输入安全重放。
4. 再次查询任务与日志。恢复后已落盘节点不应重复，最终应进入 `completed`、`retryable` 或 `failed`。
5. 如果多个 Worker 同时收到同一消息，数据库锁只允许一个有效执行；终态不会被迟到消息回退。

真实 PostgreSQL 的强制中断验证：

```powershell
docker compose up -d postgres
$env:OPS_AGENT_TEST_POSTGRES_ADMIN_URL = "postgresql://ops_agent:ops_agent@localhost:5432/postgres?connect_timeout=5"
.venv\Scripts\python.exe -m pytest backend/tests/workflows/test_report_graph_recovery.py -m integration -vv
```

该验证分别在 `research` 和 `quality` 节点强制结束独立进程，再以同一 `thread_id` 启动新进程；两个场景都必须到达完成态，且每个已持久化节点计数为 1。

## 6. 常用健康检查

```powershell
docker compose ps
Invoke-RestMethod http://localhost:8000/health
docker compose exec -T redis redis-cli ping
docker compose exec -T postgres pg_isready -U ops_agent -d ops_agent
docker compose exec -T worker celery -A ops_agent.worker:celery_app inspect ping --timeout 5
```

禁止通过直接修改 `report_jobs.status`、删除 LangGraph schema 或覆盖 `report_versions` 来“修复”任务。若按上述流程仍无法恢复，应保存 `request_id`、`job_id`、最后事件、容器健康状态和脱敏日志，再进入代码级调查。
