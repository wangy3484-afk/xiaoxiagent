"""HTTP workflow tests for parse, revise, confirm, and privacy guidance."""

import pytest
from ops_agent.domain.intake import BriefField, OperationsBrief, OperationsScene
from ops_agent.providers import DeterministicModelProvider

from api.support import api_test_context, register_and_login


def _model() -> DeterministicModelProvider:
    return DeterministicModelProvider(
        {
            "parse_intake": {
                "operation_goal": {
                    "value": "提升次月留存",
                    "source_excerpt": "目标是提升次月留存",
                },
                "target_users": {
                    "value": "新注册用户",
                    "source_excerpt": "目标用户是新注册用户",
                },
            },
            "classify_scene": {
                "primary_scene": "retention",
                "rationale": ["核心目标是提升次月留存"],
                "confidence": 0.9,
            },
        }
    )


def _revised_brief() -> OperationsBrief:
    return OperationsBrief(
        current_problem=BriefField[str].from_correction(
            "首周关键行为完成率低", "首周关键行为完成率低"
        ),
        operation_goal=BriefField[str].from_correction(
            "提升次月留存", "提升次月留存"
        ),
        target_users=BriefField[str].from_correction("新注册用户", "新注册用户"),
        business_stage=BriefField[str].from_correction("增长期", "增长期"),
        execution_period=BriefField[str].from_correction("未来90天", "未来90天"),
        budget_and_resources=BriefField[str].from_correction("2名运营", "2名运营"),
        current_baseline=BriefField[str].from_correction("次月留存15%", "次月留存15%"),
    )


@pytest.mark.asyncio
async def test_parse_revise_confirm_happy_path_and_data_boundary() -> None:
    async with api_test_context(model_provider=_model()) as context:
        await register_and_login(context.client)
        parsed = await context.client.post(
            "/api/v1/briefs/parse",
            json={"scenario": "目标是提升次月留存，目标用户是新注册用户"},
            headers={"Idempotency-Key": "parse-brief-1"},
        )
        assert parsed.status_code == 201
        parsed_body = parsed.json()
        assert parsed_body["status"] == "draft"
        assert parsed_body["revision_number"] == 1
        assert "个人身份信息" in parsed_body["data_boundary"]["prohibited"]
        assert "current_baseline" in parsed_body["required_gaps"]

        revised = await context.client.patch(
            f"/api/v1/briefs/{parsed_body['id']}",
            json={
                "expected_revision_number": 1,
                "brief": _revised_brief().model_dump(mode="json"),
                "classification": parsed_body["classification"],
            },
        )
        assert revised.status_code == 200
        assert revised.json()["revision_number"] == 2

        confirmed = await context.client.post(
            f"/api/v1/briefs/{parsed_body['id']}/confirm",
            json={"expected_revision_number": 2},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["status"] == "confirmed"
        assert confirmed.json()["ready_for_research"] is True
        assert confirmed.json()["brief"]["current_problem"]["value"] == (
            "首周关键行为完成率低"
        )

        invalid = await context.client.patch(
            f"/api/v1/briefs/{parsed_body['id']}",
            json={
                "expected_revision_number": 2,
                "brief": _revised_brief().model_dump(mode="json"),
                "classification": parsed_body["classification"],
            },
        )
        assert invalid.status_code == 409
        assert invalid.json()["detail"]["code"] == "BRIEF_ALREADY_CONFIRMED"


@pytest.mark.asyncio
async def test_stale_revision_update_returns_concurrency_conflict() -> None:
    async with api_test_context(model_provider=_model()) as context:
        await register_and_login(context.client)
        parsed = await context.client.post(
            "/api/v1/briefs/parse",
            json={"scenario": "目标是提升次月留存，目标用户是新注册用户"},
            headers={"Idempotency-Key": "parse-brief-2"},
        )
        body = parsed.json()
        update_payload = {
            "expected_revision_number": 1,
            "brief": _revised_brief().model_dump(mode="json"),
            "classification": body["classification"],
        }

        first = await context.client.patch(
            f"/api/v1/briefs/{body['id']}", json=update_payload
        )
        stale = await context.client.patch(
            f"/api/v1/briefs/{body['id']}", json=update_payload
        )

        assert first.status_code == 200
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "BRIEF_REVISION_CONFLICT"


@pytest.mark.asyncio
async def test_parse_requires_model_configuration_and_authentication() -> None:
    async with api_test_context() as context:
        anonymous = await context.client.post(
            "/api/v1/briefs/parse",
            json={"scenario": "目标是提升留存"},
            headers={"Idempotency-Key": "parse-brief-3"},
        )
        assert anonymous.status_code == 401

        await register_and_login(context.client)
        unavailable = await context.client.post(
            "/api/v1/briefs/parse",
            json={"scenario": "目标是提升留存"},
            headers={"Idempotency-Key": "parse-brief-4"},
        )
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"]["code"] == "MODEL_PROVIDER_NOT_CONFIGURED"


def test_revised_brief_preserves_user_correction_provenance() -> None:
    brief = _revised_brief()
    assert brief.operation_goal.source.value == "user_correction"
    assert OperationsScene.RETENTION.value == "retention"
