"""Batch acceptance of all golden scenarios against generated report artifacts."""

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from ops_agent.domain.report import OperationsReport
from ops_agent.domain.research import EvidenceCoverageResult
from ops_agent.evaluation.golden import GoldenEvaluationResult, evaluate_golden_report
from ops_agent.evaluation.schema import GoldenScenarioSet


@dataclass(frozen=True, slots=True)
class GoldenBatchResult:
    results: tuple[GoldenEvaluationResult, ...]
    missing_scenario_ids: tuple[str, ...]
    unexpected_scenario_ids: tuple[str, ...]
    duplicate_report_ids: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return (
            not self.missing_scenario_ids
            and not self.unexpected_scenario_ids
            and not self.duplicate_report_ids
            and all(result.passed for result in self.results)
        )


def evaluate_golden_batch(
    scenarios: GoldenScenarioSet,
    artifact_directory: Path,
) -> GoldenBatchResult:
    """Evaluate one generated report and coverage record per golden scenario.

    Each ``<scenario_id>.json`` file contains ``report`` and ``coverage``
    objects exported from one actual graph run. Missing, extra, malformed, or
    duplicate scenario artifacts fail the batch instead of being skipped.
    """
    expected = {scenario.scenario_id: scenario for scenario in scenarios.scenarios}
    actual = {path.stem: path for path in artifact_directory.glob("*.json")}
    missing = tuple(sorted(expected.keys() - actual.keys()))
    unexpected = tuple(sorted(actual.keys() - expected.keys()))
    results: list[GoldenEvaluationResult] = []

    for scenario_id in sorted(expected.keys() & actual.keys()):
        try:
            payload = json.loads(actual[scenario_id].read_text(encoding="utf-8"))
            report = OperationsReport.model_validate(payload["report"])
            coverage = EvidenceCoverageResult.model_validate(payload["coverage"])
        except (OSError, ValueError, KeyError, TypeError, ValidationError) as exc:
            results.append(
                GoldenEvaluationResult(
                    scenario_id=scenario_id,
                    report_id="invalid-artifact",
                    passed=False,
                    failures=(f"invalid_artifact:{type(exc).__name__}",),
                )
            )
            continue
        results.append(evaluate_golden_report(expected[scenario_id], report, coverage))

    report_ids = [
        result.report_id
        for result in results
        if result.report_id != "invalid-artifact"
    ]
    duplicates = tuple(
        sorted({report_id for report_id in report_ids if report_ids.count(report_id) > 1})
    )
    return GoldenBatchResult(
        results=tuple(results),
        missing_scenario_ids=missing,
        unexpected_scenario_ids=unexpected,
        duplicate_report_ids=duplicates,
    )
