# 生产健康监控与告警

`compose.production.yaml` 为 Proxy、Web、API、Worker、PostgreSQL、Redis 和监控进程配置健康检查、内存/CPU/进程数限制以及重启策略。一次性迁移任务只运行到成功退出。Worker 并发限制为 2，避免单机上大量子进程挤占数据库和代理资源。Worker 同时连接内部网络与可出站网络，供其访问外部模型、搜索和公开网页。

监控进程定期检查 Redis、Celery Worker、`report-jobs` 队列积压和模型健康端点。模型端点由 `OPS_AGENT_MODEL_HEALTH_URL` 指定；若提供商没有兼容的只读健康端点，需要配置由同一网络可达的供应商探针。探针使用配置的 Bearer Key，但日志不会输出 Key、URL 或响应正文。未配置该 URL 时只检查其他三项。默认每 15 秒检查一次，连续失败 2 次产生告警；恢复后产生一次解除告警。

告警以 JSON 行写到 `monitor` 容器标准输出，事件名为 `ops_health_alert`，字段包括 `component`、`state`（`firing`/`resolved`）、`detail` 和时间。生产日志采集器应将 `state=firing` 转为值班通知，并将 `resolved` 与对应事件关联。查看近期事件：

```bash
docker compose -p ops-strategy-agent-prod --env-file .env.production.local -f compose.production.yaml logs --since 1h monitor
```

`OPS_AGENT_MONITOR_QUEUE_BACKLOG_THRESHOLD` 是队列积压条数阈值，默认 20。按实际报告生成时长和可接受等待时间调整。Redis 不可达时，Worker 与队列状态暂记为未知，只报告 Redis 故障；连接恢复后重新检查，避免错误解除先前的 Worker 告警。模型检查只判断端点是否可达且返回 2xx/3xx，不替代四类真实报告的端到端验收。

故障处理顺序：先查看 `docker compose ps -a` 和 `monitor` 日志，再检查相应服务日志。Worker 故障时核对 Redis 与队列积压；Redis 故障恢复后确认 Worker 已重新连接；模型告警时检查供应商状态、账号配额与出站网络。告警解除后，依据 PostgreSQL 中的任务状态检查运行中、失败和可重试任务，不能只看 Celery 消息。已有正式报告和版本应保持可读。
