"""Keep every OpenSpec scenario traceable to an executable acceptance test."""

import ast
import re
from pathlib import Path

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[3]
CHANGE = ROOT / "openspec/changes/build-operations-strategy-agent"
MAPPING = ROOT / "docs/openspec-scenario-tests.yaml"
SCENARIO_LINE = re.compile(r"^#### Scenario: (.+)$", re.MULTILINE)


def test_every_spec_scenario_has_a_valid_test_mapping_or_explicit_gap() -> None:
    mapping = yaml.safe_load(MAPPING.read_text(encoding="utf-8"))
    spec_files = sorted((CHANGE / "specs").glob("*/spec.md"))
    assert len(spec_files) == 5
    assert set(mapping) == {path.parent.name for path in spec_files}

    mapped_count = 0
    for spec_file in spec_files:
        scenario_names = SCENARIO_LINE.findall(spec_file.read_text(encoding="utf-8"))
        scenario_mapping = mapping[spec_file.parent.name]
        assert set(scenario_mapping) == set(scenario_names)
        assert len(scenario_names) == len(set(scenario_names))
        for scenario_name, test_id in scenario_mapping.items():
            assert test_id != "TODO", scenario_name
            path_text, separator, function_name = test_id.partition("::")
            assert separator, scenario_name
            test_path = ROOT / path_text
            assert test_path.is_file(), scenario_name
            if test_path.suffix == ".tsx":
                assert f'it("{function_name}"' in test_path.read_text(
                    encoding="utf-8"
                ), scenario_name
                mapped_count += 1
                continue
            functions = {
                node.name
                for node in ast.parse(test_path.read_text(encoding="utf-8")).body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            assert function_name in functions, scenario_name
            mapped_count += 1
    assert mapped_count >= 50
