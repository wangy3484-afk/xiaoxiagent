"""Load and validate packaged golden scenarios and human-review rubric."""

from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from ops_agent.domain.base import DomainModel
from ops_agent.evaluation.schema import (
    GoldenScenarioSet,
    HumanReviewRubric,
    HumanReviewSubmission,
)


def _parse_yaml[EvaluationModel: DomainModel](
    raw: str,
    source: str,
    model: type[EvaluationModel],
) -> EvaluationModel:
    try:
        payload: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"evaluation data {source} must contain a YAML mapping")
    return model.model_validate(payload)


def load_golden_scenario_file(path: Path) -> GoldenScenarioSet:
    """Validate one golden-scenario set from the filesystem."""
    return _parse_yaml(path.read_text(encoding="utf-8"), str(path), GoldenScenarioSet)


def load_human_review_rubric_file(path: Path) -> HumanReviewRubric:
    """Validate one human-review rubric from the filesystem."""
    return _parse_yaml(path.read_text(encoding="utf-8"), str(path), HumanReviewRubric)


def load_human_review_submission_file(path: Path) -> HumanReviewSubmission:
    """Validate one completed human-review submission from the filesystem."""
    return _parse_yaml(path.read_text(encoding="utf-8"), str(path), HumanReviewSubmission)


def load_default_golden_scenarios() -> GoldenScenarioSet:
    """Load the packaged twelve-case anonymous golden set."""
    resource = files("ops_agent.evaluation").joinpath("data/golden_scenarios.yaml")
    return _parse_yaml(resource.read_text(encoding="utf-8"), resource.name, GoldenScenarioSet)


def load_default_human_review_rubric() -> HumanReviewRubric:
    """Load the packaged seven-dimension scoring rubric."""
    resource = files("ops_agent.evaluation").joinpath("data/human_review_rubric.yaml")
    return _parse_yaml(resource.read_text(encoding="utf-8"), resource.name, HumanReviewRubric)
