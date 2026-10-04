"""Schema and coverage tests for the anonymous golden evaluation set."""

from collections import Counter

import pytest
from ops_agent.domain.intake import OperationsScene
from ops_agent.domain.quality import QualityDimension
from ops_agent.evaluation import (
    RequiredReportSection,
    load_default_golden_scenarios,
    load_default_human_review_rubric,
)
from ops_agent.evaluation.schema import GoldenScenarioSet
from pydantic import ValidationError


def test_golden_set_has_three_anonymous_cases_per_scene() -> None:
    golden_set = load_default_golden_scenarios()
    counts = Counter(scenario.scene for scenario in golden_set.scenarios)

    assert len(golden_set.scenarios) == 12
    assert counts == Counter({scene: 3 for scene in OperationsScene})
    assert len({scenario.scenario_id for scenario in golden_set.scenarios}) == 12


def test_every_case_declares_sections_blockers_and_seven_dimension_benchmark() -> None:
    golden_set = load_default_golden_scenarios()

    for scenario in golden_set.scenarios:
        assert set(scenario.required_sections) == set(RequiredReportSection)
        assert set(scenario.professional_review_benchmark) == set(QualityDimension)
        assert scenario.expected_blockers is not None
        assert scenario.anonymized_context
        assert scenario.input_text


def test_human_review_rubric_has_complete_weighted_seven_dimension_scale() -> None:
    rubric = load_default_human_review_rubric()

    assert rubric.scale_min == 1
    assert rubric.scale_max == 5
    assert len(rubric.dimensions) == 7
    assert {item.dimension for item in rubric.dimensions} == set(QualityDimension)
    assert sum(item.weight for item in rubric.dimensions) == 100
    assert all(item.score_1_anchor for item in rubric.dimensions)
    assert all(item.score_3_anchor for item in rubric.dimensions)
    assert all(item.score_5_anchor for item in rubric.dimensions)


def test_golden_schema_rejects_missing_scene_and_review_coverage() -> None:
    data = load_default_golden_scenarios().model_dump(mode="json")
    data["scenarios"] = data["scenarios"][:3]

    with pytest.raises(ValidationError, match="at least 12"):
        GoldenScenarioSet.model_validate(data)

    data = load_default_golden_scenarios().model_dump(mode="json")
    data["scenarios"][0]["professional_review_benchmark"].pop(
        QualityDimension.RISK_COVERAGE.value
    )
    with pytest.raises(ValidationError, match="all seven quality dimensions"):
        GoldenScenarioSet.model_validate(data)
