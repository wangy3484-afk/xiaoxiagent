# 生产部署与变更手册

适用范围：单机 Linux、Docker Compose v2 和 `compose.production.yaml`。负责人应在变更单中记录操作者、时间、镜像 digest、数据库迁移版本、备份位置、验证结果和回滚决定。生产环境不使用仓库中的测试密钥或自签证书。

## 首次部署与日常升级

1. 在主机外的受控密钥库生成数据库密码、长度不少于 32 字符的会话密钥、模型与搜索服务密钥。由密钥库生成仅部署账号可读的 `.env.production.local`（权限 `0600`），参考 `.env.production.example`。证书私钥只授予 Proxy 容器 UID/GID 101 读取。不要提交或打印这些值。
2. 指定不可变的版本标签并记录对应镜像 digest，令 `OPS_AGENT_IMAGE_TAG` 与 `OPS_AGENT_MIGRATION_IMAGE_TAG` 指向同一已验证版本。确认模型名称、兼容 API 地址、搜索服务地址、健康 URL、供应商配额和网络出口均符合 `docs/providers.md`；健康 URL 必须能凭当前模型密钥返回 2xx/3xx。先在预发布测试真实供应商连接。
3. 对现有部署先按 [备份手册](production-backup-restore.md) 生成并异地保存一致性备份；检查磁盘、TLS 证书有效期、PostgreSQL 主版本和上一版本镜像仍可取得。
4. 在仓库根目录检查配置并启动：

```bash
docker compose -p ops-strategy-agent-prod --env-file .env.production.local -f compose.production.yaml config --quiet
docker compose -p ops-strategy-agent-prod --env-file .env.production.local -f compose.production.yaml up -d --no-build --wait
docker compose -p ops-strategy-agent-prod --env-file .env.production.local -f compose.production.yaml ps -a
```

迁移任务应以 0 退出；其余服务应 healthy。检查 TLS、`/health`、登录、既有报告版本与 PDF/Markdown 下载，并在监控日志中确认没有持续的 `firing` 告警。对已发布镜像使用 `--no-build`；若自行构建，先在 CI 固定依赖、测试并记录镜像 digest，部署阶段不要隐式重建。不要执行 `down --volumes`。

## 密钥轮换与供应商配置

先在供应商控制台创建新密钥，确认其权限、额度和生效时间，再在密钥库中更新 `OPS_AGENT_MODEL_API_KEY` 或 `OPS_AGENT_SEARCH_API_KEY`；暂时保留旧密钥。重新生成仅部署账号可读的 env 文件，执行 `docker compose ... up -d --no-build --force-recreate api worker monitor`。检查服务健康、模型监控、一次预发布报告生成与供应商计量；成功后撤销旧密钥。失败时在旧密钥仍有效的窗口内恢复旧 env 并重建这些容器。轮换数据库密码需协调 PostgreSQL、应用连接和备份脚本，安排维护窗口；不可只改应用 env。

轮换 `OPS_AGENT_SESSION_SECRET` 会令现有登录会话失效，须提前通知用户并在维护窗口重建 API/Worker/Monitor。会话令牌只以摘要保存在数据库，不能通过修改 env 保持旧会话。将密钥暴露视为安全事件：先遏制、轮换，再按内部流程审计；日志和变更单不得包含密钥明文。供应商 base URL、模型名或搜索实现变更时，先按 [提供商契约](providers.md) 做超时、认证、限流、配额和输出结构测试，再在预发布跑四类场景，不能只凭健康探针判定可用。

## 数据保留

配置项 `OPS_AGENT_REPORT_RETENTION_DAYS`、`OPS_AGENT_SOURCE_SNAPSHOT_RETENTION_DAYS`、`OPS_AGENT_JOB_EVENT_RETENTION_DAYS`、`OPS_AGENT_TEMPORARY_ARTIFACT_RETENTION_DAYS` 必须与公司保留制度一致。当前自动清理只删除超过期限、未锁定的任务事件，并将到期、未锁定的临时导出记录标记为删除、删除其文件；**不自动删除历史报告、证据和原始来源快照**，因此前两项是策略值而非已实现的完整删除承诺。对正式报告和来源数据的到期删除需求，应先完成依赖关系、法律保留、备份副本和删除审计设计，不能直接清空卷。执行清理前先备份并记录删除计数：

```bash
docker compose -p ops-strategy-agent-prod --env-file .env.production.local -f compose.production.yaml exec -T api python -m ops_agent.persistence.retention
```

备份本身的加密、异地副本与生命周期独立于在线数据清理，按 [备份手册](production-backup-restore.md) 和公司制度管理。

## 镜像回滚

回滚前保存当前 env 文件、镜像 digest、迁移版本和最近备份，确认上一应用镜像与当前数据库 schema 兼容。将 `OPS_AGENT_IMAGE_TAG` 改为上一已验收版本；**保持 `OPS_AGENT_MIGRATION_IMAGE_TAG` 为当前迁移版本**，以免旧 Alembic 无法识别已经应用的新 revision。执行 `docker compose ... config --quiet` 和 `docker compose ... up -d --no-build --force-recreate --wait`。复核健康、既有报告只读访问、下载与新任务状态。如果 schema 不向后兼容，不允许只换镜像；使用新环境从备份恢复并经过数据一致性验证后再切流。不要在有新写入的生产数据库上盲目执行 Alembic downgrade。回滚完成后记录原因、影响范围和后续修复人。

预发布演练顺序：用隔离项目与端口准备一份含报告和导出文件的数据；记录报告 ID 与校验和；为当前镜像和上一镜像保留不同标签；轮换**测试**模型/搜索密钥并重建 API、Worker、Monitor；确认新值已注入且密钥未出现在日志；部署下一镜像，再按上述步骤回滚上一镜像；通过 HTTPS 登录读取原报告并核验导出文件、用户权限和版本号。详见 [备份恢复](production-backup-restore.md) 与 [监控告警](production-monitoring.md)。
