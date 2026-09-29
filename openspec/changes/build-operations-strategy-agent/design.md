# Design

## Context

当前项目为全新项目，仅存在 OpenSpec 规划文件，没有可复用的应用代码或基础设施。动机见 [proposal.md](./proposal.md)，外部可观察行为见 `specs/` 下五项能力规格。

系统需要处理持续数分钟的联网检索与模型推理任务，并允许用户在运营简报确认处暂停和恢复。公开网页属于不可信输入；报告中的事实、策略和指标必须能够追溯到用户输入、证据或明确标记的专业推断。系统不接入内部用户明细，也不执行任何外部运营投放。

首版部署目标是一台可访问公网的 Linux 云服务器，通过 Docker Compose 运行。开发环境可以在 Windows 主机上使用 Linux 容器，避免依赖原生 Windows 后台任务支持。

## Goals / Non-Goals

**Goals:**

- 通过有状态、可恢复的工作流实现运营简报确认、案例研究、专项策略生成和质量修订。
- 用结构化数据模型约束模型输出，并把每个事实主张关联到证据记录。
- 将拉新增长、用户留存、活动运营和内容运营实现为可独立演进的专业方法模块。
- 将长耗时生成任务与 Web 请求解耦，提供可靠的状态查询、失败重试和版本保存。
- 提供适合单机生产部署的安全、可观测和可回滚架构，同时保留横向扩展空间。
- 建立可重复执行的专业质量评估与人工验收基准。

**Non-Goals:**

- 首版不建设自主多 Agent 协商系统；采用单个受控图中的职责节点。
- 首版不建设企业私有知识库、向量数据库或内部数据连接器。
- 首版不接入广告、CRM、内容发布或营销自动化平台。
- 首版不支持多人实时协作、复杂组织权限或企业 SSO。
- 首版不使用 Kubernetes；单机 Docker Compose 满足初始规模。
- 首版不承诺无人审核即可直接执行报告中的运营动作。

## Decisions

### 1. 采用前后端分离的单仓库架构

系统由以下运行单元组成：

```text
+------------------+       +---------------------+
| Browser / Web UI | ----> | Reverse Proxy / TLS |
+------------------+       +----------+----------+
                                  |
                     +------------+------------+
                     |                         |
                     v                         v
              +-------------+           +-------------+
              | React Web   |           | FastAPI API |
              +-------------+           +------+------+
                                                  |
                             +--------------------+-------------------+
                             |                    |                   |
                             v                    v                   v
                       +-----------+        +-----------+       +-----------+
                       | PostgreSQL|        | Redis     | ----> | Worker    |
                       +-----------+        +-----------+       +-----+-----+
                                                                       |
                                             +-------------------------+------------------+
                                             |                         |                  |
                                             v                         v                  v
                                       +-----------+             +-----------+      +----------+
                                       | LLM API   |             | Search API|      | Web Fetch|
                                       +-----------+             +-----------+      +----------+
```

- 前端采用 React + TypeScript，负责场景录入、简报确认、任务进度、报告阅读和导出。
- 后端采用 FastAPI，负责身份认证、资源授权、业务 API、任务创建和报告读取。
- 后台 Worker 负责运行 LangGraph、生成导出文件和更新任务状态。
- 共享领域模型和 API 契约以 OpenAPI 与生成类型保持一致，避免前后端字段漂移。

选择该结构是因为生成任务耗时且依赖外部服务，不能占用同步 HTTP 请求。相比把页面、API 和 Agent 全部放入单进程，拆分 API 与 Worker 更容易限制资源、恢复失败任务并独立扩容。相比微服务，模块化单体减少首版部署和一致性成本。

### 2. 使用 LangGraph 编排受控状态机，LangChain 提供模型与工具适配

每份报告对应一个 `job_id`，同时作为 LangGraph 的 `thread_id`。核心图状态使用 Pydantic 模型定义，只保存结构化数据和资源标识，不把不断增长的完整提示词历史作为业务状态。

```text
parse_intake --> classify_scene --> check_completeness
                                         |
                       missing ----------+---------- complete
                          |                              |
                          v                              v
                 request_clarification          confirm_brief
                          |                              |
                          +---------- resume -----------+
                                                         |
                                                         v
research_plan --> search_sources --> fetch_and_verify --> build_evidence
                                                              |
                                                              v
diagnose --> select_playbooks --> design_strategy --> build_action_plan
                                                              |
                                                              v
draft_report --> deterministic_checks --> professional_review
                        ^                         |
                        |                         +-- pass --> finalize
                        |                         |
                        +------ repair route <----+-- fail
                                                  |
                                                  +-- unresolved --> limited_draft
```

关键设计：

- 简报确认使用 LangGraph interrupt/checkpoint 机制暂停，用户确认后从原线程恢复。
- 联网检索按研究查询并行展开，但设置查询数、页面数、单页大小和总耗时上限。
- 节点失败分为瞬时错误、模型可修正错误、用户可修正缺口和不可恢复错误，并采用不同路由。
- 质量修订最多执行两轮；仍存在阻断项时输出“方向性草案”或失败说明，不无限循环。
- PostgreSQL checkpointer 保存图状态，以便 Worker 重启后恢复未完成任务。

选择 LangGraph 而不是单次 LangChain Agent，是因为流程存在人工确认、明确分支、长任务恢复和质量回退。LangGraph 官方将 checkpoint 用于跨交互持久化，并提供生产用 PostgreSQL saver；interrupt 能在保存状态后等待外部输入。参考：[LangGraph checkpointing](https://reference.langchain.com/python/langgraph/checkpoints)、[LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)。

### 3. 所有关键模型输出必须通过结构化契约

以下核心对象使用 Pydantic 定义，并在进入下一节点前验证：

- `OperationsBrief`：结构化运营简报及字段来源。
- `SceneClassification`：主要/辅助场景、理由和不确定性。
- `ResearchPlan`：检索主题、查询、期望证据和停止条件。
- `EvidenceRecord`：来源元数据、支持主张、证据等级和适配因素。
- `CaseMechanism`：目标、人群、触点、机制、激励、条件和结果。
- `Diagnosis`：目标树、关键行为路径、核心问题和约束。
- `StrategyOption`：策略逻辑、证据、适用条件、调整和风险。
- `ActionItem`、`MetricDefinition`、`ExperimentPlan`：执行与验证闭环。
- `QualityReview`：七维审查结果、阻断项和修订目标。
- `OperationsReport`：完整报告的结构化源数据。

优先使用模型提供商的原生结构化输出；不支持时使用工具调用策略。验证失败最多重试两次，仍失败则将节点标记为失败并保留可诊断错误。LangChain 官方支持用 Pydantic、dataclass、TypedDict 或 JSON Schema 获得经过校验的结构化响应，并提供模式错误重试机制：[Structured output](https://docs.langchain.com/oss/python/langchain/structured-output)。

最终 HTML、Markdown 和 PDF 均由 `OperationsReport` 通过确定性模板渲染，不直接把模型生成的自由 Markdown 当作正式报告，从而保证章节、标签、表格和引用格式一致。

### 4. 专业方法采用“公共核心 + 四个场景 playbook”

公共核心定义所有报告必须具备的诊断、证据、策略迁移、行动计划、指标、实验和风险内容。四个 playbook 分别定义拉新增长、用户留存、活动运营和内容运营的：

- 必填与建议输入字段。
- 专项澄清问题。
- 诊断维度和禁止遗漏项。
- 策略结构与执行计划结构。
- 必须提供的指标与实验类型。
- 场景特有的质量检查规则。

Playbook 以版本化 YAML 文件保存，并通过 Pydantic 在启动和测试阶段验证。运行时根据主要场景加载一个主 playbook，再加载零个或多个辅助 playbook；冲突时以主场景目标为准，并记录取舍。

相比把方法论全部写入一个巨型系统提示词，版本化 playbook 更便于评审、测试和持续改进。相比首版引入可视化规则平台，仓库内 YAML 更简单、可审计，也能通过代码评审控制专业内容变更。

### 5. 研究层采用提供商适配器和证据优先的数据流

定义 `SearchProvider`、`PageFetcher`、`ContentExtractor` 和 `ModelProvider` 接口。首版每类只实现一个生产适配器和一个测试替身，具体供应商通过环境配置选择，业务图不依赖供应商响应格式。

研究过程遵循：

1. 根据运营简报和 playbook 生成研究计划。
2. 搜索用户点名企业和结构相似企业。
3. 抓取原始页面；仅有搜索摘要且原文无法确认的内容不能成为已核验事实。
4. 规范化 URL、去重、提取标题、来源、日期、正文片段和访问时间。
5. 按官方/原始、可信第三方、一般二手材料划分证据等级。
6. 按目标、用户、阶段、模式、渠道、资源和时间背景计算适配维度。
7. 抽取案例机制，并创建 `claim_id -> evidence_id[]` 映射。

数据库只长期保存来源元数据、支持主张所需的有限片段、内容摘要和校验哈希，不保存无必要的完整网页副本。报告中的数字性或因果性主张必须有关联证据；无法核验的内容降级为假设或排除。

首版不引入向量数据库。当前任务以一次性网络研究为主，PostgreSQL 的结构化查询和全文检索足够；当后续出现经过人工维护的大规模内部案例库时，再评估 `pgvector`，避免为尚不存在的知识库增加同步和召回复杂度。

### 6. 质量控制采用确定性规则与独立模型审查组合

质量节点分两层：

- 确定性检查：必填章节、字段完整性、引用可解析性、事实主张引用率、行动项字段、指标口径、资源约束和禁止自动执行等硬规则。
- 专业审查：使用独立提示上下文检查证据是否支持主张、案例是否被错误迁移、目标与资源是否冲突、指标是否能验证策略、是否存在虚假精确。

审查节点只输出 `QualityReview`，不直接改写报告。路由器根据问题类型把修订任务发送给研究、诊断、策略、计划或报告节点，防止“评论者同时当作者”导致问题被掩盖。每次修订保留审查记录。

正式完成必须没有阻断项。证据或输入客观不足时，系统保存并交付带限制说明的方向性草案，不用语言润色伪装成完整结论。

上线前建立至少 12 个匿名黄金场景，每类运营场景不少于 3 个，由有经验的运营人员按相同七维标准评审。自动评估关注结构与证据，人工评审负责判断专业深度和业务可用性。

### 7. 使用 Celery + Redis 执行长任务，PostgreSQL 是业务状态真相源

FastAPI 创建报告任务后写入 PostgreSQL，再向 Redis 队列发送只包含 `job_id` 的 Celery 任务。Worker 根据 `job_id` 加载状态并运行 LangGraph。Celery 的结果后端不作为业务真相源；任务阶段、失败原因、重试次数和最终状态全部写入 PostgreSQL。

关键约束：

- 同一 `job_id` 使用数据库锁或幂等键避免重复执行。
- Worker 只对瞬时网络错误进行有界重试；模型校验错误由图节点处理。
- 外部调用设置连接、读取和总时限，并记录供应商请求标识。
- UI 首版通过轮询状态接口获取进度；服务端推送可在并发量增长后增加。
- Celery Worker 在 Linux 容器运行；不把原生 Windows 作为受支持的生产执行环境。

选择 Celery 是因为它提供独立 Worker、消息代理、重试和扩展能力，适合把长任务从 Web 进程剥离；官方文档将其定位为通过 broker 向 Worker 分发任务的任务队列：[Celery getting started](https://docs.celeryq.dev/en/stable/getting-started/)。相比 FastAPI 进程内后台任务，该方案能在 API 重启后继续处理或重新调度任务。

### 8. 业务数据与图状态统一使用 PostgreSQL，文件使用存储适配器

主要业务实体：

- `users`、`sessions`
- `operations_briefs`、`brief_revisions`
- `report_jobs`、`job_events`
- `evidence_records`、`claims`、`claim_evidence_links`
- `report_versions`、`quality_reviews`
- `export_files`

业务表使用 SQLAlchemy 访问、Alembic 管理迁移。报告版本不可覆盖；重新生成创建新版本，并记录来源简报版本、playbook 版本、模型配置和生成时间。LangGraph checkpoint 使用独立表或 schema，避免业务查询依赖框架内部格式。

导出文件通过 `ArtifactStorage` 接口保存。单机首版使用挂载数据卷；生产配置可切换到 S3 兼容对象存储而不改变业务 API。数据库记录文件校验和、格式、大小、创建时间和授权主体。

### 9. 首版采用同源会话认证和资源级授权

首版提供本地账号登录，密码使用现代密码哈希算法保存；浏览器使用 `Secure`、`HttpOnly`、`SameSite` Cookie 持有服务端会话。所有 brief、job、evidence、report 和 export 查询均在仓储层强制加入用户授权条件，不依赖前端隐藏。

公网抓取执行以下控制：

- 仅允许 HTTP/HTTPS，阻止本机、内网、云元数据和保留地址，重定向后重新校验目标。
- 限制响应大小、内容类型、重定向次数和下载时间。
- 将网页内容明确标记为不可信数据，禁止网页文本改变系统指令或调用工具。
- 不向搜索或模型提供密码、会话、服务器环境变量和其他密钥。
- 日志默认不记录完整用户输入、网页正文或模型响应，仅记录必要标识和脱敏摘要。

相比首版直接集成企业 SSO，本地会话认证能够完成规格要求且减少外部依赖；认证模块保持适配边界，为后续 OIDC/SSO 留出替换空间。

### 10. API 以资源和状态转换为中心

建议的主要接口：

- `POST /api/v1/briefs/parse`：解析自然语言场景。
- `PATCH /api/v1/briefs/{id}`：补充或修正简报。
- `POST /api/v1/briefs/{id}/confirm`：确认需求基线并恢复图。
- `POST /api/v1/reports`：基于已确认简报创建报告任务。
- `GET /api/v1/jobs/{id}`：查询阶段、进度和失败信息。
- `GET /api/v1/reports`：查看有权限的历史报告。
- `GET /api/v1/reports/{id}/versions/{version}`：读取结构化报告。
- `POST /api/v1/reports/{id}/regenerate`：基于新简报版本重新生成。
- `POST /api/v1/reports/{id}/exports`：创建 PDF 或 Markdown 导出。
- `GET /api/v1/exports/{id}`：在授权检查后下载文件。

创建类接口接受幂等键。API 错误统一返回稳定的错误码、用户可理解消息和追踪标识；不得把模型提示词、密钥或内部堆栈返回前端。

### 11. 使用 Docker Compose 完成首版生产部署

生产 Compose 包含 `proxy`、`web`、`api`、`worker`、`postgres` 和 `redis`。数据库迁移作为独立一次性任务在应用启动前运行。每个容器设置健康检查、资源限制、重启策略和只读文件系统（需要写入的挂载目录除外）。

反向代理负责 HTTPS、请求大小限制和安全响应头。密钥通过部署环境注入，不进入镜像或仓库。依赖版本写入锁文件，镜像按不可变版本标签发布。FastAPI 官方建议从 Python 基础镜像构建自己的应用镜像，并由 Docker、Compose 或编排平台处理启动、重启和部署：[FastAPI in Containers](https://fastapi.tiangolo.com/deployment/docker/)。

最低可观测性包括：

- 贯穿 API、队列、LangGraph 和外部调用的 `request_id`、`job_id`、`thread_id`。
- 节点开始/完成/失败事件、耗时、重试次数和错误分类。
- 模型调用次数、token 用量、搜索次数、抓取成功率、报告总时长和单报告估算成本。
- 健康检查、数据库连接、队列积压和 Worker 存活监控。
- 日志脱敏与保留期限配置。

## Risks / Trade-offs

- **公开网页质量不稳定或来源被删除** -> 保存证据元数据、有限支持片段、访问时间和校验哈希；报告明确证据等级与失效状态。
- **网页提示注入影响模型行为** -> 抓取内容与系统指令隔离，网页仅作为带来源的数据字段进入受约束节点，工具权限不由网页内容决定。
- **模型仍可能生成无依据主张** -> 使用结构化输出、主张到证据映射、确定性引用检查和独立质量阻断。
- **四类运营场景导致专业深度被摊薄** -> 共享公共核心但使用独立 playbook 和黄金场景验收；未达到专项门槛的场景不标记为正式完成。
- **联网研究带来较高延迟和成本** -> 有界并行、查询与页面预算、内容去重、可配置模型分层和相同来源缓存。
- **Celery 与 LangGraph 都保存执行状态，增加一致性复杂度** -> Celery 只负责调度，PostgreSQL 业务状态与 LangGraph checkpoint 才是恢复依据；所有任务通过幂等 `job_id` 执行。
- **单机部署存在容量和单点限制** -> 定期备份并保持无状态 API/Worker；后续可把数据库、Redis 和对象存储迁出，再横向扩容容器。
- **PDF 中文排版可能受字体和表格影响** -> 镜像内固定开源中文字体，建立包含长表格、分页和引用附录的视觉回归样例。
- **专业质量难以完全自动度量** -> 自动规则负责可验证底线，黄金场景和运营专家抽检负责专业判断，二者结果分别记录。

## Migration Plan

1. 建立前端、API、Worker 和共享配置的项目骨架，锁定依赖并配置本地 Docker Compose。
2. 创建业务数据库迁移、LangGraph checkpoint schema、会话认证和资源授权边界。
3. 实现提供商接口与测试替身，先在离线测试中验证所有结构化契约。
4. 实现运营简报确认和 LangGraph 暂停/恢复，再逐步加入研究、专项策略和质量回退节点。
5. 实现 Web 状态流、报告版本、引用展示及 Markdown/PDF 导出。
6. 使用至少 12 个匿名黄金场景完成自动检查和运营专家验收。
7. 部署预发布环境，验证外部服务限流、失败恢复、备份恢复、权限隔离和成本上限。
8. 小范围开放生产访问，观察成功率、报告耗时、阻断原因和人工质量评分后再扩大使用。

回滚策略：保留上一版本镜像和 Compose 配置；数据库迁移优先采用向后兼容的新增字段/表方案。发生严重问题时关闭新报告创建，允许读取已有报告，停止 Worker 后回滚镜像。无法安全恢复的运行中任务标记为可重试，已交付报告版本不删除或覆盖。

## Open Questions

- 生产环境使用哪一家大模型与搜索服务由部署时的可用账号、成本和合规要求决定；适配器接口和测试任务不因此改变。
- 报告视觉品牌、Logo 和固定页眉页脚可以在通用模板完成后配置，不影响报告数据结构。
- 报告、证据和日志的最终保留期限需要在生产上线前结合公司制度确定；实现中提供可配置保留策略。
