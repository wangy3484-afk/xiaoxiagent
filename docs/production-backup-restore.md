# 生产备份与恢复

适用范围：单机 Linux + `compose.production.yaml` 部署。备份包含整个 PostgreSQL 数据库（业务表、Alembic 版本和 LangGraph checkpoint）以及报告导出文件卷。Redis 队列不在备份中；恢复后，应根据 PostgreSQL 中的任务状态检查未完成任务并按运维流程重试。

## 备份前

1. 在部署主机准备 `.env.production.local`，确保它与当前运行的 Compose 项目一致，且只允许运维人员读取。请勿把该文件或备份归档提交到 Git。
2. 确保 PostgreSQL、Redis 和应用服务健康，并确认磁盘有足够空间容纳数据库 dump 与完整导出文件卷。
3. 安排短暂停机窗口。脚本会停止 Proxy、Web、API 和 Worker，完成一致性备份后自动启动它们。数据库与 Redis 继续运行。

从仓库根目录执行：

```bash
bash scripts/backup-production.sh .env.production.local /srv/xiaoxiagent-backups/2026-10-04 ops-strategy-agent-prod
```

目标目录必须事先不存在。备份完成时包含：

- `postgres.dump`：PostgreSQL custom format 备份。
- `artifacts.tar`：报告导出文件及其元数据。
- `inventory.json`：每张业务表的行数与内容 SHA-256，以及每个有效导出文件的校验和和大小。
- `SHA256SUMS`：上述三个文件的整体校验和。
- `COMPLETE`：仅在备份全部成功时生成的完成标记。

备份脚本会逐个读取导出文件，校验其与数据库记录中的 SHA-256 和大小一致。若文件缺失或损坏，备份失败并保留未完成目录供排查。运行结束后检查应用服务健康，并将完整备份加密复制到主机外存储。备份包含账号、简报和报告等敏感信息，访问权限应只授予恢复负责人。

## 恢复到空环境

恢复目标必须使用空的 PostgreSQL 数据卷与空的报告文件卷，并使用与备份兼容的应用镜像和数据库主版本。不要对现有生产环境直接执行恢复脚本：它会拒绝非空数据库或文件卷。先准备新的 Compose 项目名、目标服务器和 TLS 证书，再执行：

```bash
bash scripts/restore-production.sh .env.production.local /srv/xiaoxiagent-backups/2026-10-04 ops-strategy-agent-prod-restore
```

恢复脚本先核验 `SHA256SUMS` 与完成标记，等待新 PostgreSQL 和 Redis 健康，再确认目标数据库及文件卷为空。导入数据库和文件后，它重新计算业务表内容摘要，逐个检查导出文件校验和，并与备份 `inventory.json` 做严格比较。仅在一致时才启动完整服务。脚本在已有数据上会拒绝再次恢复，避免覆盖已存在的报告。

恢复后的核对：

```bash
docker compose -p ops-strategy-agent-prod-restore --env-file .env.production.local -f compose.production.yaml ps -a
docker compose -p ops-strategy-agent-prod-restore --env-file .env.production.local -f compose.production.yaml exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT version_num FROM alembic_version"'
```

迁移容器应以退出码 0 结束，其余服务应为 healthy。使用有权限的测试账号读取历史报告和下载 PDF/Markdown，确认版本、证据链接与文件可访问。若核验失败，保留失败现场，使用新的空项目重试；不要在失败项目上运行清空卷命令。切换生产流量前，另外核对实际域名、TLS 证书、供应商密钥和防火墙配置。

## 演练与保留

至少定期将备份恢复到独立空环境，记录备份时间、镜像版本、数据库迁移版本、`SHA256SUMS` 校验结果、恢复耗时、各业务表行数、导出文件数量及下载结果。恢复演练只能使用隔离项目名和端口，不应影响当前生产数据。保留周期、异地副本和加密密钥按公司制度确定。
