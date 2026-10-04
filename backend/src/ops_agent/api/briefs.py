"""Authenticated operations-brief parse, revision, and confirmation API."""

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel, Field

from ops_agent.api.dependencies import (
    CurrentSubject,
    DatabaseSession,
    RequestModelProvider,
)
from ops_agent.domain.intake import FieldStatus, OperationsBrief, SceneClassification
from ops_agent.persistence.idempotency import (
    IdempotencyConflict,
    IdempotencyInProgress,
    IdempotencyService,
)
from ops_agent.persistence.repositories import (
    BriefRepository,
    InvalidStateTransition,
    ResourceNotFound,
    VersionConflict,
)
from ops_agent.playbooks.loader import load_default_registry
from ops_agent.workflows.classification import check_completeness, classify_scene
from ops_agent.workflows.intake import parse_intake
from ops_agent.workflows.questions import prioritize_clarifying_questions

router = APIRouter(prefix="/api/v1/briefs", tags=["operations briefs"])


class InputDataBoundaryNotice(BaseModel):
    title: str
    prohibited: list[str]
    allowed_alternatives: list[str]


class BriefParseRequest(BaseModel):
    scenario: str = Field(min_length=1, max_length=20_000)


class BriefRevisionRequest(BaseModel):
    expected_revision_number: int = Field(ge=1)
    brief: OperationsBrief
    classification: SceneClassification


class BriefConfirmRequest(BaseModel):
    expected_revision_number: int = Field(ge=1)


class BriefWorkflowResponse(BaseModel):
    id: str
    revision_id: str
    revision_number: int
    status: str
    brief: OperationsBrief
    classification: SceneClassification
    ready_for_research: bool
    required_gaps: list[str]
    clarifying_questions: list[dict[str, object]]
    data_boundary: InputDataBoundaryNotice


INPUT_DATA_BOUNDARY = InputDataBoundaryNotice(
    title="请仅提交非敏感、汇总后的运营信息",
    prohibited=["个人身份信息", "客户或用户明细", "账号密码与密钥", "公司机密数据"],
    allowed_alternatives=["汇总指标", "数值区间", "匿名用户分群", "非敏感业务描述"],
)


@router.post(
    "/parse",
    response_model=BriefWorkflowResponse,
    status_code=status.HTTP_201_CREATED,
)
async def parse_brief(
    payload: BriefParseRequest,
    response: Response,
    session: DatabaseSession,
    subject: CurrentSubject,
    model: RequestModelProvider,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1, max_length=200),
    ],
) -> BriefWorkflowResponse:
    idempotency = IdempotencyService(session)
    try:
        reservation = await idempotency.reserve(
            subject,
            scope="POST:/api/v1/briefs/parse",
            key=idempotency_key,
            request_payload=payload.model_dump(mode="json"),
        )
    except IdempotencyConflict as exc:
        raise _conflict("IDEMPOTENCY_CONFLICT", "该幂等键已用于不同的场景输入。") from exc
    except IdempotencyInProgress as exc:
        raise _conflict(
            "IDEMPOTENCY_REQUEST_IN_PROGRESS", "相同场景正在解析，请稍后重试。"
        ) from exc
    if not reservation.is_new:
        response.headers["Idempotency-Replayed"] = "true"
        response.status_code = reservation.record.response_status or status.HTTP_201_CREATED
        return BriefWorkflowResponse.model_validate(reservation.response_payload)

    brief = await parse_intake(payload.scenario, model)
    classification = await classify_scene(brief, model)
    brief_row, revision = await BriefRepository(session).create(
        subject,
        brief_payload=brief.model_dump(mode="json"),
        classification_payload=classification.model_dump(mode="json"),
    )
    result = _workflow_response(
        brief_row.id,
        revision.id,
        revision.revision_number,
        brief_row.status,
        brief,
        classification,
    )
    await idempotency.complete(
        reservation,
        resource_type="operations_brief",
        resource_id=brief_row.id,
        response_status=status.HTTP_201_CREATED,
        response_payload=result.model_dump(mode="json"),
    )
    return result


@router.patch("/{brief_id}", response_model=BriefWorkflowResponse)
async def revise_brief(
    brief_id: str,
    payload: BriefRevisionRequest,
    session: DatabaseSession,
    subject: CurrentSubject,
) -> BriefWorkflowResponse:
    repository = BriefRepository(session)
    try:
        revision = await repository.add_revision(
            subject,
            brief_id,
            payload.expected_revision_number,
            payload.brief.model_dump(mode="json"),
            payload.classification.model_dump(mode="json"),
        )
    except ResourceNotFound as exc:
        raise _not_found() from exc
    except VersionConflict as exc:
        raise _conflict("BRIEF_REVISION_CONFLICT", "简报已被更新，请刷新后重新修改。") from exc
    except InvalidStateTransition as exc:
        raise _conflict("BRIEF_ALREADY_CONFIRMED", "已确认的简报不能继续修改。") from exc
    brief_row = await repository.get(subject, brief_id)
    if brief_row is None:
        raise _not_found()
    return _workflow_response(
        brief_id,
        revision.id,
        revision.revision_number,
        brief_row.status,
        payload.brief,
        payload.classification,
    )


@router.post("/{brief_id}/confirm", response_model=BriefWorkflowResponse)
async def confirm_brief(
    brief_id: str,
    payload: BriefConfirmRequest,
    session: DatabaseSession,
    subject: CurrentSubject,
) -> BriefWorkflowResponse:
    repository = BriefRepository(session)
    latest = await repository.get_latest_revision(subject, brief_id)
    if latest is None:
        raise _not_found()
    brief = OperationsBrief.model_validate(latest.brief_payload)
    classification = SceneClassification.model_validate(latest.classification_payload)
    for field_name in ("operation_goal", "target_users"):
        if getattr(brief, field_name).status is not FieldStatus.CONFIRMED:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "CRITICAL_BRIEF_GAP",
                    "message": "确认前必须明确运营目标和目标用户。",
                    "field": field_name,
                },
            )
    try:
        revision = await repository.confirm_revision(
            subject,
            brief_id,
            payload.expected_revision_number,
        )
    except ResourceNotFound as exc:
        raise _not_found() from exc
    except VersionConflict as exc:
        raise _conflict("BRIEF_REVISION_CONFLICT", "简报已被更新，请刷新后重新确认。") from exc
    except InvalidStateTransition as exc:
        raise _conflict("INVALID_BRIEF_STATE", "当前简报状态不能确认。") from exc
    brief_row = await repository.get(subject, brief_id)
    if brief_row is None:
        raise _not_found()
    return _workflow_response(
        brief_id,
        revision.id,
        revision.revision_number,
        brief_row.status,
        brief,
        classification,
    )


def _workflow_response(
    brief_id: str,
    revision_id: str,
    revision_number: int,
    brief_status: str,
    brief: OperationsBrief,
    classification: SceneClassification,
) -> BriefWorkflowResponse:
    completeness = check_completeness(brief, classification, load_default_registry())
    questions = prioritize_clarifying_questions(completeness)
    return BriefWorkflowResponse(
        id=brief_id,
        revision_id=revision_id,
        revision_number=revision_number,
        status=brief_status,
        brief=brief,
        classification=classification,
        ready_for_research=brief_status == "confirmed",
        required_gaps=[gap.field for gap in completeness.required_gaps],
        clarifying_questions=[
            question.model_dump(mode="json") for question in questions
        ],
        data_boundary=INPUT_DATA_BOUNDARY,
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "RESOURCE_NOT_FOUND", "message": "资源不存在或当前账号无权访问。"},
    )


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message},
    )
