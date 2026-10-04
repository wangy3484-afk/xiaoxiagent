"""Run the complete golden-scenario gate on generated report artifacts."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from ops_agent.evaluation import evaluate_golden_batch, load_default_golden_scenarios


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_directory", type=Path)
    args = parser.parse_args(argv)
    artifact_directory: Path = args.artifact_directory
    if not artifact_directory.is_dir():
        parser.error(f"artifact directory does not exist: {artifact_directory}")

    result = evaluate_golden_batch(
        load_default_golden_scenarios(), artifact_directory
    )
    print(
        json.dumps(
            {
                "passed": result.passed,
                "evaluated": len(result.results),
                "missing_scenario_ids": result.missing_scenario_ids,
                "unexpected_scenario_ids": result.unexpected_scenario_ids,
                "duplicate_report_ids": result.duplicate_report_ids,
                "results": [asdict(item) for item in result.results],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
