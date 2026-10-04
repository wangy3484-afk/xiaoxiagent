# 运营策略 Agent

面向拉新增长、用户留存、活动运营和内容运营的证据型运营决策支持系统。产品规格与实施进度位于 `openspec/changes/build-operations-strategy-agent/`。

外部模型、搜索、安全抓取及离线替身的配置方式见 [外部提供商配置与替换指南](docs/providers.md)。
运营场景“解析—澄清—确认”的接口与状态转换见 [运营简报流程 API](docs/brief-workflow-api.md)。
案例研究中的证据等级、时效和适配评分口径见 [证据等级与案例适配评分说明](docs/evidence-scoring.md)。
任务状态、稳定错误码、搜索限流和 Worker 中断恢复见 [报告任务运维与排障](docs/task-operations.md)。
报告标题、Logo、页眉和模板结构约束见 [报告模板与品牌配置](docs/report-branding.md)。
生产环境备份、恢复和演练步骤见 [生产备份与恢复](docs/production-backup-restore.md)。
生产健康检查、资源限制和告警处理见 [生产健康监控与告警](docs/production-monitoring.md)。
生产部署、密钥轮换、数据保留和镜像回滚见 [生产部署与变更手册](docs/production-operations.md)。
OpenSpec 场景与自动测试的对应关系见 [验收测试映射](docs/openspec-scenario-tests.yaml)。

## 推荐开发环境

- Windows 11：Docker Desktop + WSL 2，并切换到 **Linux containers**。
- Linux：Docker Engine 与 Docker Compose v2。
- Git。
- 仅在需要脱离容器调试时安装 Python 3.12/3.13 与 Node.js 22。

Celery Worker 不支持作为原生 Windows 生产进程运行；Windows 开发必须使用 Compose 中的 Linux Worker 容器。

## 首次启动

```powershell
git clone https://github.com/wangy3484-afk/xiaoxiagent.git
cd xiaoxiagent
Copy-Item .env.example .env
docker compose config --quiet
docker compose up -d --build
docker compose run --rm api python -m alembic upgrade head
docker compose ps
```

`docker compose ps` 应显示 `postgres`、`redis`、`api`、`worker`、`web` 五个服务均为 `healthy`。

- Web：http://localhost:4200
- API 健康检查：http://localhost:8000/health
- PostgreSQL：`localhost:5432`
- Redis：`localhost:6379`

`4200` 是默认 Web 主机端口，可在 `.env` 中通过 `OPS_AGENT_WEB_PORT` 修改；容器内使用 `8080`。

## 常用命令

```powershell
# 查看状态和日志
docker compose ps
docker compose logs -f api worker web

# 重建并启动
docker compose up -d --build

# 数据库升级/降级检查
docker compose run --rm api python -m alembic upgrade head
docker compose run --rm api python -m alembic downgrade base
docker compose run --rm api python -m alembic upgrade head

# 后端与前端检查见下方原生开发命令；生产镜像不包含测试工具。

# 数据保留清理（只处理过期、未锁定日志和临时文件）
docker compose run --rm api python -m ops_agent.persistence.retention

# 停止服务；默认保留数据库、Redis 和报告卷
docker compose down

# 仅在明确需要清空全部本地开发数据时使用
docker compose down --volumes
```

## 原生后端开发

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python -m pip install -e . --no-deps
.venv\Scripts\python -m ruff check backend
.venv\Scripts\python -m mypy backend/src backend/tests
.venv\Scripts\python -m pytest
```

真实 PostgreSQL checkpoint 恢复测试需要先启动 `postgres` 容器：

```powershell
docker compose up -d postgres
$env:OPS_AGENT_TEST_POSTGRES_ADMIN_URL = "postgresql://ops_agent:ops_agent@localhost:5432/postgres"
.venv\Scripts\python -m pytest backend/tests/persistence/test_checkpoints.py -vv
```

## 原生前端开发

```powershell
cd frontend
npm ci
npm run lint
npm run test
npm run build
npm run dev -- --host 127.0.0.1 --port 4200
```

## 常见问题

- `docker` 命令不可用：启动 Docker Desktop，确认 `docker version` 与 `docker compose version` 均能返回服务端信息。
- Docker Hub 超时：在 Docker Desktop 中配置公司允许的 registry mirror，再重新执行 `docker compose up -d --build`；不要把个人镜像凭据提交到仓库。
- 端口不可用：修改 `.env` 中的 `OPS_AGENT_WEB_PORT`，或先检查目标端口是否被其他进程/Windows 保留范围占用。
- Worker 不健康：运行 `docker compose logs worker`，确认 Redis 健康且 Worker 运行在 Linux 容器中。
- 修改 `.env` 后配置未生效：运行 `docker compose up -d --force-recreate`。

`.env`、API Key、会话密钥和真实业务数据不得提交到 Git。
