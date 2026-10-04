"""Case-mechanism migration tests."""

from ops_agent.domain.intake import BriefField, OperationsBrief, OperationsScene
from ops_agent.domain.report import StrategyOption, StrategyPriority
from ops_agent.domain.research import CaseMechanism, Claim, ClaimType, EvidenceVerificationStatus
from ops_agent.workflows.strategy import adapt_case_mechanisms_to_strategies


def _brief_with_limited_resources() -> OperationsBrief:
    return OperationsBrief(
        business_context=BriefField[str].from_user("社区团购冷启动小程序", "冷启动小程序"),
        operation_goal=BriefField[str].from_user("提升新客首单转化", "提升新客首单转化"),
        target_users=BriefField[str].from_user("新注册家庭用户", "新注册家庭用户"),
        business_stage=BriefField[str].from_user("冷启动阶段", "冷启动阶段"),
        budget_and_resources=BriefField[str].from_user(
            "1名运营，预算1000元，资源有限", "1名运营，预算1000元"
        ),
        existing_channels=BriefField[list[str]].from_user(["社群"], "社群"),
        constraints=BriefField[list[str]].from_user(["没有推荐系统"], "没有推荐系统"),
    )


def _case_mechanism() -> CaseMechanism:
    return CaseMechanism(
        case_id="case-taobao-first-order",
        company="淘宝",
        goal="提升新客首单转化",
        audience="新注册用户",
        touchpoints=["首页活动页", "优惠券中心"],
        mechanism="用首单任务和权益激励降低首次下单门槛。",
        incentive="首单优惠券",
        execution_conditions=["海量自然流量", "成熟优惠券系统"],
        observed_outcomes=[
            Claim(
                claim_id="claim-action",
                text="淘宝上线过新客首单任务",
                claim_type=ClaimType.FACT,
                evidence_ids=["ev-taobao"],
                reasoning="公开规则页面可验证活动动作。",
                verification_status=EvidenceVerificationStatus.VERIFIED,
            )
        ],
        evidence_ids=["ev-taobao"],
        transferable_elements=["首单任务", "权益激励"],
        non_transferable_elements=["头部平台自然流量", "成熟推荐系统"],
    )


def _direct_copy_strategy() -> StrategyOption:
    return StrategyOption(
        strategy_id="strategy-copy-taobao",
        scene=OperationsScene.ACQUISITION,
        title="复制淘宝新客首单玩法",
        target_segment="新注册家庭用户",
        strategy_logic="直接复用淘宝首单任务和优惠券机制。",
        evidence_ids=[],
        assumption_claim_ids=["hyp-1"],
        applicability_conditions=["需要活动落地页"],
        scene_differences=["当前为冷启动小程序"],
        adaptations=["直接复制淘宝完整玩法"],
        impact_path=["触达新客", "完成首单"],
        non_copyable_factors=["无"],
        risks=["优惠套利"],
        priority=StrategyPriority.MUST,
    )


def test_case_migration_scales_down_when_resources_do_not_match() -> None:
    adapted = adapt_case_mechanisms_to_strategies(
        [_direct_copy_strategy()],
        [_case_mechanism()],
        _brief_with_limited_resources(),
    )[0]

    assert adapted.evidence_ids == ["ev-taobao"]
    assert any("海量自然流量" in item for item in adapted.applicability_conditions)
    assert any("资源条件不匹配" in item for item in adapted.scene_differences)
    assert all("直接复制" not in item for item in adapted.adaptations)
    assert any("缩小为最小实验" in item for item in adapted.adaptations)
    assert any("头部平台自然流量" in item for item in adapted.non_copyable_factors)
    assert any("禁止直接复制" in item for item in adapted.risks)
    assert adapted.priority is StrategyPriority.SHOULD
