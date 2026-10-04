"""Command-line validation for built-in and proposed playbook YAML files."""

import argparse
from collections.abc import Sequence
from pathlib import Path

from ops_agent.playbooks.loader import load_default_registry, load_playbook_file
from ops_agent.playbooks.schema import Playbook


def validate_paths(paths: Sequence[Path]) -> list[Playbook]:
    """Validate proposed files with the exact schema used at application startup."""
    return [load_playbook_file(path) for path in paths]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate operations playbook YAML files.")
    parser.add_argument(
        "paths",
        metavar="PLAYBOOK",
        nargs="*",
        type=Path,
        help="Optional playbook files. Without paths, validate the built-in bundle.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths: list[Path] = args.paths
    if paths:
        playbooks = validate_paths(paths)
        for path, playbook in zip(paths, playbooks, strict=True):
            print(f"OK {path}: {playbook.scene} v{playbook.playbook_version}")
        return 0

    registry = load_default_registry()
    print(f"OK built-in core v{registry.core.playbook_version}")
    for scene, playbook in sorted(registry.by_scene.items(), key=lambda item: item[0].value):
        print(f"OK built-in {scene.value} v{playbook.playbook_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
