"""Validate persisted B4 numerical evidence and CLI method selection."""

import csv
import json
from pathlib import Path
import subprocess
import sys

import pytest

from asar_repro.scenarios import digest
from asar_repro.search_reporting import REQUIRED_FIELDS

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/baseline_v1.1/b4"


def read(name):
    return json.loads((OUTPUT / name).read_text(encoding="utf-8"))


def test_saved_b4_schema_and_counterexample_evidence():
    audit, runs = read("audit.json"), read("toy_runs.json")
    assert audit["status"] == "passed" and len(runs) == audit["toy_run_count"] == 72
    assert audit["new_historical_forcing_planning_runs"] == 0
    for row in runs:
        assert set(REQUIRED_FIELDS) <= row.keys()
        assert row["forcing_kind"] == "toy"
        assert (
            row["algorithm"]
            == {"zero": "ASAR_zero", "mass_lb": "ASAR_mass_lb", "paper_greedy": "ASAR_paper"}[
                row["heuristic"]
            ]
        )
        if row["search_status"] == "budget_exceeded":
            assert not row["completed_for_certificate"] and not row["discrete_model_certified"]
        if row["discrete_model_certified"]:
            assert row["observed_within_epsilon"]
        if row["heuristic"] == "paper_greedy":
            assert not row["theoretical_bound_applicable"]
    witness = audit["witnesses"]["appendix_b"]
    assert witness["root_paper_greedy"] == pytest.approx(2.6170801771, abs=1e-10)
    assert witness["oracle_J"] == pytest.approx(2.5417333379, abs=1e-10)
    bad = [
        r
        for r in runs
        if r["scenario_id"] == "dynamic_suboptimal"
        and r["heuristic"] == "paper_greedy"
        and r["epsilon"] == 1
        and r["profile"] == "pruned"
    ]
    assert len(bad) == 1 and bad[0]["J_minus_oracle"] > 0.01
    assert not bad[0]["observed_within_epsilon"] and not bad[0]["discrete_model_certified"]
    with (OUTPUT / "toy_metrics.csv").open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == 72
    for row in csv_rows:
        if row["profile"] == "stopped_no_path":
            assert row["J"] == row["Pd_T"] == row["M_T"] == row["path"] == "null"


def test_legacy_source_hashes_and_completion_denominator(archived_source_check):
    audit, rows = read("audit.json"), read("legacy_runs.json")
    for source in audit["legacy_sources"]:
        assert digest(ROOT / source["path"]) == source["sha256"]
    for source, expected in audit["code_sha256"].items():
        archived_source_check(source, expected)
    assert len(rows) == 32
    stopped = [r for r in rows if r["result_class"] == "aborted_feasible_incumbent"]
    assert len(stopped) == 17
    assert all(
        r["stop_reason"] == "max_expansions" and r["incumbent_source"] == "ParallelTrack"
        for r in stopped
    )
    assert all(r["J_over_PT"] == 1 and not r["search_completed"] for r in stopped)
    assert all(
        r["forcing_kind"] == "constant_synthetic" and not r["discrete_model_certified"]
        for r in rows
    )
    assert audit["legacy_groups"][0]["completion_rate"] == 15 / 32
    assert audit["legacy_max_replay_error"] == 0


def test_benchmark_cli_reports_selected_method(tmp_path):
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/audit_search_results.py"),
            "--heuristic",
            "mass_lb",
            "--output-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    rows = json.loads((tmp_path / "toy_runs.json").read_text(encoding="utf-8"))
    assert len(rows) == 24 and {r["algorithm"] for r in rows} == {"ASAR_mass_lb"}
    assert {r["heuristic"] for r in rows} == {"mass_lb"}
