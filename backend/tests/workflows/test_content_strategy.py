"""Content-operations strategy module tests."""

import pytest
from ops_agent.domain.intake import BriefField, OperationsBrief
from ops_agent.domain.report import Diagnosis, GoalRelationship, TargetBasis
from ops_agent.domain.research import (
    Claim,
    ClaimType,
    EvidenceBundle,
    EvidenceVerificationStatus,
)
from ops_agent.providers import DeterministicModelProvider
from ops_agent.workflows.strategy import build_content_strategy


def _brief_without_baseline() -> OperationsBrief:
    return OperationsBrief(
        business_context=BriefField[str].from_user("B2B SaaS 工具", "B2B SaaS 工具"),
        current_problem=BriefField[str].from_user(
            "内容发了不少但咨询和试用很少", "内容发了不少但咨询和试用很少"
        ),
        operation_goal=BriefField[str].from_user(
            "通过内容提升高质量咨询", "通过内容提升高质量咨询"
        ),
        target_users=BriefField[str].from_user("中小企业运营负责人", "中小企业运营负责人"),
        business_stage=BriefField[str].from_user("早期商业化", "早期商业化"),
        budget_and_resources=BriefField[str].from_user(
            "1名运营，每周可采访1个客户", "1名运营，每周可采访1个客户"
        ),
        existing_channels=BriefField[list[str]].from_user(
            ["公众号", "小红书", "官网"], "公众号、小红书、官网"
        ),
        current_baseline=BriefField[str].unknown(),
    )


def _diagnosis() -> Diagnosis:
    return Diagnosis(
        business_stage="早期商业化",
        target_users="中小企业运营负责人",
        goal_relationships=[
            GoalRelationship(
                business_goal="提升有效商机",
                operations_goal="通过内容提升高质量咨询",
                target_behavior="目标用户消费内容后预约产品咨询",
                metric_ids=["metric_assisted_consultation"],
            )
        ],
        behavior_path=["发现内容", "判断相关", "产生信任", "访问官网", "预约咨询"],
        core_problem="现有内容没有绑定明确受众任务和转化路径。",
        supporting_claim_ids=["hyp-content"],
        constraints=["1名运营", "每周可采访1个客户"],
        priority_rationale="先缩小主题矩阵并验证高质量互动，再扩大分发。",
        alternative_explanations=["主题过宽", "渠道语境不匹配", "转化动作过早"],
        data_needed=["有效阅读", "高质量互动", "内容辅助咨询"],
    )


def _evidence_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        claims=[
            Claim(
                claim_id="hyp-content",
                text="围绕运营负责人具体任务生产内容可能带来更高质量咨询。",
                claim_type=ClaimType.HYPOTHESIS,
                evidence_ids=[],
                reasoning="当前缺少内容消费到咨询的基线，需要验证。",
                verification_status=EvidenceVerificationStatus.UNVERIFIED,
            )
        ],
        evidence=[],
        links=[],
    )


def _model() -> DeterministicModelProvider:
    return DeterministicModelProvider(
        {
            "design_content_strategy": {
                "plan_id": "content-plan-1",
                "has_reliable_baseline": True,
                "positioning": {
                    "positioning_id": "pos-ops-playbook",
                    "audience_job": "帮助运营负责人把分散增长问题拆成可执行动作",
                    "value_promise": "用真实场景和模板降低运营决策成本",
                    "business_behavior": "预约产品咨询或申请试用",
                    "editorial_boundary": ["不写泛泛行业新闻", "不写与运营决策无关热点"],
                },
                "audiences": [
                    {
                        "audience_id": "aud-ops-lead",
                        "description": "中小企业运营负责人",
                        "job_to_be_done": "在资源有限时找到能验证增长问题的方法",
                        "intent_signals": ["搜索运营方案", "收藏工具模板", "评论询问落地步骤"],
                        "conversion_need": "看到可复用流程后愿意咨询工具如何支持",
                    }
                ],
                "theme_matrix": [
                    {
                        "theme_id": "theme-growth-diagnosis",
                        "audience_id": "aud-ops-lead",
                        "name": "增长问题诊断",
                        "audience_problem": "不知道拉新、留存或转化问题优先处理哪一个",
                        "content_task": "用案例拆解问题判断路径和指标口径",
                        "formats": ["长文拆解", "清单模板", "短视频"],
                        "supply_owner_role": "运营负责人采访客户后供稿",
                        "cadence": "每周1篇长文和2条短内容",
                        "quality_standard": "必须包含场景、判断依据、可执行步骤和指标",
                    },
                    {
                        "theme_id": "theme-template",
                        "audience_id": "aud-ops-lead",
                        "name": "运营模板实操",
                        "audience_problem": "有方向但缺少可直接改造的运营方案模板",
                        "content_task": "提供可复用模板并说明适用条件",
                        "formats": ["模板下载", "案例图解"],
                        "supply_owner_role": "产品经理和运营共同维护",
                        "cadence": "每两周1个模板",
                        "quality_standard": "必须说明适用边界和下一步动作",
                    },
                ],
                "supply_plans": [
                    {
                        "supply_id": "supply-customer-interview",
                        "theme_id": "theme-growth-diagnosis",
                        "source_role": "运营",
                        "source_material": "每周1个客户运营问题访谈",
                        "capacity": "每周最多产出1篇深度稿",
                        "review_gate": "发布前检查案例是否匿名、步骤是否可执行",
                        "bottleneck": "客户访谈数量有限",
                    }
                ],
                "production_cadence": [
                    {
                        "cadence_id": "cadence-growth",
                        "theme_id": "theme-growth-diagnosis",
                        "frequency": "每周1篇长文和2条短内容",
                        "workflow_steps": ["选题", "访谈", "写作", "审核", "分发"],
                        "owner_role": "内容运营",
                        "acceptance_criteria": ["内容转化率提升30%"],
                    }
                ],
                "distribution_plans": [
                    {
                        "distribution_id": "dist-wechat",
                        "theme_id": "theme-growth-diagnosis",
                        "channel": "公众号",
                        "user_intent": "用户愿意阅读完整方法和收藏模板",
                        "native_format": "长文拆解加表格模板",
                        "distribution_action": "标题聚焦具体运营场景并引导收藏",
                        "interaction_design": "文末设置问题诊断清单留言",
                        "return_path": "引导访问官网查看完整模板",
                        "conversion_action": "预约一次运营方案诊断咨询",
                    },
                    {
                        "distribution_id": "dist-xiaohongshu",
                        "theme_id": "theme-template",
                        "channel": "小红书",
                        "user_intent": "用户快速判断模板是否能解决当前问题",
                        "native_format": "图文卡片和评论区答疑",
                        "distribution_action": "用场景标题和前后对比图降低理解成本",
                        "interaction_design": "评论区收集行业和目标补充",
                        "return_path": "私信或主页链接回到官网模板页",
                        "conversion_action": "申请模板并留下咨询线索",
                    },
                ],
                "conversion_paths": [
                    {
                        "path_id": "path-consultation",
                        "audience_id": "aud-ops-lead",
                        "from_content_signal": "收藏模板、评论询问落地步骤或点击官网",
                        "next_step": "进入官网模板页并选择运营问题类型",
                        "business_behavior": "预约产品咨询或申请试用",
                        "measurement_metric_id": "metric_assisted_consultation",
                    }
                ],
                "metrics": [
                    {
                        "metric_id": "metric_assisted_consultation",
                        "name": "内容辅助咨询率",
                        "formula": "消费目标内容后预约咨询用户数 / 符合条件内容用户数",
                        "observation_window": "内容消费后14天",
                        "decision_rule": "咨询率提升30%则扩大主题",
                        "target_basis": "provided_baseline",
                        "is_target_hypothesis": False,
                    }
                ],
                "validation_plans": [
                    {
                        "validation_id": "validation-theme",
                        "linked_theme_ids": ["theme-growth-diagnosis"],
                        "hypothesis": "增长问题诊断主题能带来更高质量咨询",
                        "method": "连续4周固定主题和渠道，比较有效阅读、互动和咨询线索。",
                        "primary_metric_id": "metric_assisted_consultation",
                        "success_criteria": ["咨询率提升30%"],
                        "expected_outcome_basis": "provided_baseline",
                        "is_success_target_hypothesis": False,
                    }
                ],
                "strategy_options": [
                    {
                        "strategy_id": "strategy-content-diagnosis",
                        "scene": "content",
                        "title": "运营问题诊断型内容系统",
                        "target_segment": "中小企业运营负责人",
                        "strategy_logic": "用具体任务内容建立信任，再引导低摩擦咨询。",
                        "evidence_ids": [],
                        "assumption_claim_ids": ["hyp-content"],
                        "applicability_conditions": ["每周至少1个客户访谈素材"],
                        "scene_differences": ["当前团队内容产能有限"],
                        "adaptations": ["保留两个主题，先验证一个主渠道"],
                        "impact_path": ["解决具体问题", "形成信任", "引导官网咨询"],
                        "non_copyable_factors": ["头部平台内容流量池"],
                        "risks": ["供给不足导致断更", "渠道语境不匹配"],
                        "priority": "must",
                    }
                ],
                "limitations": ["模型草案假设已有内容转化基线"],
            }
        }
    )


@pytest.mark.asyncio
async def test_content_strategy_golden_sample_is_not_template_title_swap() -> None:
    plan = await build_content_strategy(
        _brief_without_baseline(),
        _diagnosis(),
        _evidence_bundle(),
        _model(),
    )

    assert plan.positioning.audience_job
    assert plan.audiences[0].job_to_be_done
    assert len(plan.theme_matrix) >= 2
    assert plan.theme_matrix[0].audience_problem != plan.theme_matrix[0].name
    assert plan.theme_matrix[0].content_task
    assert plan.theme_matrix[0].supply_owner_role
    assert plan.supply_plans[0].capacity
    assert plan.production_cadence[0].workflow_steps == [
        "选题",
        "访谈",
        "写作",
        "审核",
        "分发",
    ]
    assert plan.distribution_plans[0].user_intent
    assert plan.distribution_plans[0].native_format
    assert plan.distribution_plans[0].return_path
    assert plan.conversion_paths[0].business_behavior
    assert plan.has_reliable_baseline is False
    assert all(
        metric.target_basis is TargetBasis.TO_BE_VALIDATED
        and metric.is_target_hypothesis
        for metric in plan.metrics
    )
    assert all(
        validation.expected_outcome_basis is TargetBasis.TO_BE_VALIDATED
        and validation.is_success_target_hypothesis
        for validation in plan.validation_plans
    )
    criteria_text = " ".join(
        criterion
        for cadence in plan.production_cadence
        for criterion in cadence.acceptance_criteria
    )
    criteria_text += " " + " ".join(
        criterion
        for validation in plan.validation_plans
        for criterion in validation.success_criteria
    )
    assert "提升30%" not in criteria_text
    assert "基线记录" in criteria_text
