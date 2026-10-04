"""Load and validate the built-in playbook bundle."""

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from ops_agent.domain.intake import OperationsScene
from ops_agent.playbooks.schema import Playbook


@dataclass(frozen=True)
class PlaybookRegistry:
    """Validated common core and exactly one playbook per supported scene."""

    core: Playbook
    by_scene: dict[OperationsScene, Playbook]

    def for_scene(self, scene: OperationsScene) -> Playbook:
        return self.by_scene[scene]


def _parse_yaml(raw: str, source: str) -> Playbook:
    try:
        payload: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"playbook {source} must contain a YAML mapping")
    return Playbook.model_validate(payload)


def load_playbook_file(path: Path) -> Playbook:
    """Validate one filesystem playbook, used by tooling and tests."""
    return _parse_yaml(path.read_text(encoding="utf-8"), str(path))


def load_default_registry() -> PlaybookRegistry:
    """Validate the packaged core plus all four professional playbooks."""
    data_dir = files("ops_agent.playbooks").joinpath("data")
    loaded: list[Playbook] = []
    for item in sorted(data_dir.iterdir(), key=lambda entry: entry.name):
        if item.name.endswith(".yaml"):
            loaded.append(_parse_yaml(item.read_text(encoding="utf-8"), item.name))

    core_items = [item for item in loaded if item.scene == "core"]
    if len(core_items) != 1:
        raise ValueError("the built-in bundle must contain exactly one core playbook")
    by_scene: dict[OperationsScene, Playbook] = {}
    for playbook in loaded:
        if not isinstance(playbook.scene, OperationsScene):
            continue
        if playbook.scene in by_scene:
            raise ValueError(f"duplicate playbook for scene {playbook.scene}")
        by_scene[playbook.scene] = playbook
    missing = set(OperationsScene) - set(by_scene)
    if missing:
        raise ValueError(f"missing playbooks for scenes: {sorted(missing)}")
    return PlaybookRegistry(core=core_items[0], by_scene=by_scene)
