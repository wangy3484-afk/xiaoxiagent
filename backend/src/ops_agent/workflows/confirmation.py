"""Human confirmation interrupt that freezes the final brief as a baseline."""

import json
from hashlib import sha256
from typing import Any, Literal, TypedDict, cast

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from pydantic import Field, model_validator

from ops_agent.domain.base import DomainModel
from ops_agent.domain.intake import OperationsBrief, SceneClassification


class ConfirmedBriefBaseline(DomainModel):
    brief: OperationsBrief
    classification: SceneClassification
    fingerprint_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class BriefConfirmationCommand(DomainModel):
    action: Literal["modify", "confirm"]
    brief: OperationsBrief | None = None
    classification: SceneClassification | None = None

    @model_validator(mode="after")
    def validate_action_payload(self) -> "BriefConfirmationCommand":
        if self.action == "modify" and self.brief is None and self.classification is None:
            raise ValueError("modify requires a brief or classification change")
        if self.action == "confirm" and (
            self.brief is not None or self.classification is not None
        ):
            raise ValueError("confirm cannot include unreviewed changes")
        return self


class BriefConfirmationState(TypedDict):
    brief: OperationsBrief
    classification: SceneClassification
    confirmed_baseline: ConfirmedBriefBaseline | None
    research_started: bool


def build_brief_confirmation_graph(
    *,
    checkpointer: Any | None = None,
) -> Any:
    """Compile a resumable review loop; production supplies PostgreSQL saver."""
    builder = StateGraph(BriefConfirmationState)
    builder.add_node("confirm_brief", _confirm_brief)
    builder.add_node("research", _research_probe)
    builder.add_edge(START, "confirm_brief")
    builder.add_edge("confirm_brief", "research")
    builder.add_edge("research", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def _confirm_brief(state: BriefConfirmationState) -> BriefConfirmationState:
    brief = state["brief"]
    classification = state["classification"]
    modification_count = 0
    while True:
        raw_command = cast(
            object,
            interrupt(
                {
                    "type": "brief_confirmation_required",
                    "brief": brief.model_dump(mode="json"),
                    "classification": classification.model_dump(mode="json"),
                }
            ),
        )
        command = BriefConfirmationCommand.model_validate(raw_command)
        if command.action == "confirm":
            baseline = _freeze_baseline(brief, classification)
            return {
                **state,
                "brief": brief,
                "classification": classification,
                "confirmed_baseline": baseline,
            }
        modification_count += 1
        if modification_count > 20:
            raise ValueError("brief exceeded the maximum confirmation modifications")
        if command.brief is not None:
            brief = command.brief
        if command.classification is not None:
            classification = command.classification


def freeze_confirmed_brief_baseline(
    brief: OperationsBrief,
    classification: SceneClassification,
) -> ConfirmedBriefBaseline:
    payload = {
        "brief": brief.model_dump(mode="json"),
        "classification": classification.model_dump(mode="json"),
    }
    fingerprint = sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ConfirmedBriefBaseline(
        brief=brief.model_copy(deep=True),
        classification=classification.model_copy(deep=True),
        fingerprint_sha256=fingerprint,
    )


_freeze_baseline = freeze_confirmed_brief_baseline


def _research_probe(state: BriefConfirmationState) -> BriefConfirmationState:
    if state["confirmed_baseline"] is None:
        raise ValueError("research cannot start without a confirmed brief baseline")
    return {**state, "research_started": True}
