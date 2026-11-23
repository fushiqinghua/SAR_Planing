"""Command-line entry point for the A^SAR reproduction."""

import argparse
import json
from pathlib import Path
import subprocess
import sys


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(
        prog="python -m asar_repro.cli",
        description="A^SAR reproduction: offline particle planning and evidence reports.",
    )
    commands = parser.add_subparsers(dest="command")
    plan = commands.add_parser("plan", help="plan from the portable particle bundle")
    plan.add_argument("--manifest", type=Path, default=root / "data/processed/manifest.json")
    plan.add_argument("--scenario", default="lake_ontario")
    plan.add_argument("--epsilon", type=float, default=1.10)
    plan.add_argument("--heuristic", choices=("zero", "mass_lb", "paper_greedy"), default="paper_greedy")
    report = commands.add_parser("report", help="regenerate the evidence reports and summary CSV")
    report.add_argument("--results", type=Path, default=root / "outputs/metrics")
    opts = parser.parse_args()
    if opts.command == "plan":
        from .planner_adapter import plan_from_bundle

        result = plan_from_bundle(
            opts.manifest, opts.scenario, epsilon=opts.epsilon, heuristic=opts.heuristic
        )
        print(json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2))
    elif opts.command == "report":
        subprocess.run(
            [
                sys.executable,
                str(root / "scripts/build_report.py"),
                "--results",
                str(opts.results.resolve()),
            ],
            check=True,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
