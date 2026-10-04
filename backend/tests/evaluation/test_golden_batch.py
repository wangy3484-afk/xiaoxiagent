"""Golden batch gate requires all twelve generated artifacts."""

import json
from pathlib import Path

import pytest
from ops_agent.evaluation import evaluate_golden_batch, load_default_golden_scenarios
from ops_agent.evaluation.__main__ import main
from ops_agent.workflows.research import review_evidence_coverage
from workflows.test_deterministic_quality import _valid_report
from workflows.test_report_assembly import _evidence_bundle


@pytest.mark.asyncio
async def test_batch_reports_missing_scenarios_instead_of_silent_success(
    tmp_path: Path,
) -> None:
    report = await _valid_report()
    coverage = review_evidence_coverage(_evidence_bundle()[0])
    artifact = {
        "report": report.model_dump(mode="json"),
        "coverage": coverage.model_dump(mode="json"),
    }
    (tmp_path / "golden-acquisition-02.json").write_text(
        json.dumps(artifact, ensure_ascii=False), encoding="utf-8"
    )

    result = evaluate_golden_batch(load_default_golden_scenarios(), tmp_path)

    assert result.passed is False
    assert len(result.results) == 1
    assert result.results[0].passed is True
    assert len(result.missing_scenario_ids) == 11
    assert "golden-content-01" in result.missing_scenario_ids


@pytest.mark.asyncio
async def test_batch_rejects_reusing_one_report_for_two_scenarios(
    tmp_path: Path,
) -> None:
    report = await _valid_report()
    coverage = review_evidence_coverage(_evidence_bundle()[0])
    artifact = json.dumps(
        {
            "report": report.model_dump(mode="json"),
            "coverage": coverage.model_dump(mode="json"),
        },
        ensure_ascii=False,
    )
    for scenario_id in ("golden-acquisition-02", "golden-acquisition-03"):
        (tmp_path / f"{scenario_id}.json").write_text(artifact, encoding="utf-8")

    result = evaluate_golden_batch(load_default_golden_scenarios(), tmp_path)

    assert result.duplicate_report_ids == (report.report_id,)
    assert result.passed is False


def test_batch_rejects_malformed_and_unexpected_artifacts(tmp_path: Path) -> None:
    (tmp_path / "golden-content-03.json").write_text("{}", encoding="utf-8")
    (tmp_path / "not-a-golden-scenario.json").write_text("{}", encoding="utf-8")

    result = evaluate_golden_batch(load_default_golden_scenarios(), tmp_path)

    assert result.passed is False
    assert result.results[0].scenario_id == "golden-content-03"
    assert result.results[0].failures == ("invalid_artifact:KeyError",)
    assert result.unexpected_scenario_ids == ("not-a-golden-scenario",)


def test_batch_cli_exits_nonzero_and_lists_all_missing_scenarios(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main([str(tmp_path)])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert output["passed"] is False
    assert output["evaluated"] == 0
    assert len(output["missing_scenario_ids"]) == 12
