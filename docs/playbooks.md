# Playbook 维护指南

Playbook 是运营方案 Agent 的专业方法配置，不是自由提示词。应用启动、测试和命令行工具都使用同一个 Pydantic schema 校验 YAML；不满足契约的变更不得进入运行环境。

## 文件与加载范围

- 内置公共核心：`backend/src/ops_agent/playbooks/data/core.yaml`
- 内置专项 Playbook：同目录下的 `acquisition.yaml`、`retention.yaml`、`campaign.yaml`、`content.yaml`
- 外部候选示例：`docs/examples/playbook.example.yaml`

启动加载器要求内置目录恰好包含一个公共核心，并完整覆盖拉新、留存、活动和内容四个场景。示例和评审中的候选文件应放在内置目录之外，避免未经评审就进入启动加载范围。

## 字段含义

| 字段 | 维护要求 |
|---|---|
| `schema_version` | 当前固定为 `1.0`，表示 YAML 结构契约版本。 |
| `playbook_version` | 使用 `主版本.次版本.修订版本`，表示专业方法内容版本。 |
| `scene` | 只能是 `core`、`acquisition`、`retention`、`campaign`、`content`。 |
| `required_input_fields` | 缺失时应阻止正式研究的输入字段。不得为了减少追问随意删除。 |
| `recommended_input_fields` | 能提高报告质量但允许明确标记未知的字段。不能与必填字段重复。 |
| `clarifying_questions` | 面向运营人员的专项追问，包含目标字段、优先级和为什么要问。 |
| `diagnostic_dimensions` | 诊断必须回答的问题和必须形成的输出，不是通用标题列表。 |
| `strategy_sections` | 场景特有的策略决策结构、必填内容与取舍规则。 |
| `required_metrics` | 必备结果、过程或风险指标，必须给出口径、公式和决策用途。 |
| `quality_rules` | 可阻断或警告的专业质量规则，必须包含检查方法和修复动作。 |

所有元素的 `id` 是跨版本稳定标识，用于测试、合并和冲突记录。只修改展示文案时不得更换 ID；删除或改变 ID 语义属于破坏性变更。

## 版本规则

- 主版本：字段语义、稳定 ID、关键决策框架或质量门槛发生不兼容变化。
- 次版本：向后兼容地新增问题、诊断维度、策略结构、指标或质量规则。
- 修订版本：不改变决策逻辑的表述修正、错别字修正或示例完善。
- `schema_version` 与 `playbook_version` 分开维护。改变 YAML 结构时先升级代码 schema，再迁移全部内置文件。

每次内容变更应在合并请求中说明：变更原因、受影响场景、预期改善、可能退化、对应黄金场景，以及是新增、替换还是删除规则。

## 运营专家评审流程

1. 提案人复制示例文件，在内置目录之外完成候选版本。
2. 至少一名熟悉该场景的运营专家检查专项深度，确认问题、诊断、策略和指标不是通用模板换标题。
3. 产品或方法负责人检查与公共核心、其他场景以及决策支持边界是否冲突。
4. 工程评审运行统一校验、合并冲突测试和全部后端检查。
5. 使用至少一个正常样例和一个应被阻断的样例进行报告评估；影响硬性规则时必须补充自动化测试。
6. 评审结论记录为通过、修改后通过或拒绝；通过后才能移动到内置数据目录并升级版本。

专家评审至少回答以下问题：

- 该 Playbook 是否产生该场景独有的关键决策，而非通用建议？
- 必填输入是否足以避免模型补造目标、用户、基线和资源？
- 指标能否验证策略的影响路径，是否包含风险护栏？
- 资源不足、证据不足和无基线时，规则是否会降低结论强度？
- 与辅助场景冲突时，主场景优先会牺牲什么，是否能够在报告中披露？

## 统一校验命令

校验应用启动时加载的全部内置 Playbook：

```powershell
.venv\Scripts\python -m ops_agent.playbooks.validate
```

校验一个或多个候选文件：

```powershell
.venv\Scripts\python -m ops_agent.playbooks.validate docs/examples/playbook.example.yaml
```

提交前还需运行：

```powershell
.venv\Scripts\python -m pytest backend/tests/playbooks
.venv\Scripts\python -m ruff check backend
.venv\Scripts\python -m mypy backend/src backend/tests
```

校验成功只证明结构合法，不代表专业内容已经通过运营专家评审。
