"""The documented example uses the same validator as built-in playbooks."""

from pathlib import Path

from ops_agent.domain.intake import OperationsScene
from ops_agent.playbooks.validate import main, validate_paths

PROJECT_ROOT = Path(__file__).parents[3]
EXAMPLE_PATH = PROJECT_ROOT / "docs" / "examples" / "playbook.example.yaml"


def test_example_playbook_passes_shared_schema() -> None:
    playbooks = validate_paths([EXAMPLE_PATH])

    assert len(playbooks) == 1
    assert playbooks[0].scene is OperationsScene.ACQUISITION
    assert playbooks[0].playbook_version == "1.1.0"


def test_validation_command_accepts_example() -> None:
    assert main([str(EXAMPLE_PATH)]) == 0
