"""Validation tests for the built-in professional playbook bundle."""

from fastapi.testclient import TestClient
from ops_agent.domain.intake import OperationsScene
from ops_agent.main import app
from ops_agent.playbooks import load_default_registry


def test_all_four_scene_playbooks_satisfy_the_shared_schema() -> None:
    registry = load_default_registry()

    assert set(registry.by_scene) == set(OperationsScene)
    assert registry.core.scene == "core"
    for scene, playbook in registry.by_scene.items():
        assert playbook.scene is scene
        assert playbook.playbook_version == "1.0.0"
        assert playbook.clarifying_questions
        assert playbook.diagnostic_dimensions
        assert playbook.strategy_sections
        assert playbook.required_metrics
        assert playbook.quality_rules


def test_scene_playbooks_contain_distinct_professional_decisions() -> None:
    registry = load_default_registry()
    expected_metric_ids = {
        OperationsScene.ACQUISITION: "customer_acquisition_cost",
        OperationsScene.RETENTION: "cohort_retention_rate",
        OperationsScene.CAMPAIGN: "campaign_incremental_goal",
        OperationsScene.CONTENT: "content_assisted_conversion",
    }
    expected_strategy_ids = {
        OperationsScene.ACQUISITION: "acquisition_channel_portfolio",
        OperationsScene.RETENTION: "retention_activation",
        OperationsScene.CAMPAIGN: "campaign_mechanism",
        OperationsScene.CONTENT: "content_operating_system",
    }

    for scene, metric_id in expected_metric_ids.items():
        playbook = registry.for_scene(scene)
        assert metric_id in {item.id for item in playbook.required_metrics}
        assert expected_strategy_ids[scene] in {item.id for item in playbook.strategy_sections}


def test_application_startup_validates_and_exposes_playbooks() -> None:
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert set(app.state.playbooks.by_scene) == set(OperationsScene)
