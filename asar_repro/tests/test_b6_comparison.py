"""B6 independent replay, artifact provenance, state distinctions and output protection."""

from copy import deepcopy
import csv
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import compare_b6 as b6
from asar_repro.search_reporting import REQUIRED_FIELDS

OUTPUT = ROOT / "outputs/baseline_v1.1/lake_ontario_real"


@pytest.fixture
def experiment():
    spec = b6.read_json(ROOT / "configs/b6_comparison.json")
    graph, args, meta = b6.load_input(spec)
    cfg = meta["provenance"]["config"]
    times = b6.planning_times(cfg["cst_utc"], cfg["budget"], cfg["step_s"])
    return spec, graph, args, times, b6.read_json(OUTPUT / "runs.json")


def test_each_real_route_replays_and_stop_source_is_exact(experiment):
    spec, graph, args, times, rows = experiment
    assert len(rows) == 7 and rows[0]["algorithm"] == "ParallelTrack"
    assert rows[0]["search_status"] == "completed" and not rows[0]["search_completed"]
    assert rows[0]["expanded"] is None
    assert sum(r["search_completed"] for r in rows) == 2
    assert sum(r["search_status"] == "budget_exceeded" for r in rows) == 4
    assert not any(r["discrete_model_certified"] for r in rows)
    for row in rows:
        assert set(REQUIRED_FIELDS) <= row.keys()
        ledger, score = b6.replay(deepcopy(row), graph, args, times, spec["archive_sha256"])
        assert len(ledger) == 50 and ledger[0]["J_t"] == ledger[0]["delta_Pd"] == 0
        assert row["J"] == pytest.approx(score.J, abs=1e-10)
        assert row["forcing_kind"] == "historical_real" and row["T"] == 49 and row["q"] == .78
        if row["search_status"] == "budget_exceeded":
            assert row["incumbent_source"] == "ParallelTrack" and row["path"] == rows[0]["path"]
            assert row["J"] == rows[0]["J"] and row["stop_reason"] == "max_expansions"
        if row["heuristic"] == "mass_lb":
            assert row["theoretical_bound_applicable"] and not row["completed_for_certificate"]
        if row["heuristic"] == "paper_greedy":
            assert not row["theoretical_bound_applicable"]
        if row["heuristic"] is not None:
            assert "." not in row["run_id"]  # Decimal epsilon must not become a filename suffix.
            assert (OUTPUT / "b6_workers" / (row["run_id"] + ".json")).is_file()


@pytest.mark.parametrize("key,value", [("particle_archive_sha256","wrong"),("T",48),("q",.5),("time_utc_sha256","wrong")])
def test_replay_rejects_different_input_contract(experiment, key, value):
    spec, graph, args, times, rows = experiment
    row=deepcopy(rows[0]); row[key]=value
    with pytest.raises(ValueError, match="identity|mismatch"):
        b6.replay(row, graph, args, times, spec["archive_sha256"])


@pytest.mark.parametrize("corruption", ["illegal_path", "J", "Pd_T", "M_T"])
def test_replay_rejects_illegal_or_misreported_route(experiment, corruption):
    spec, graph, args, times, rows = experiment
    row=deepcopy(rows[1])
    if corruption == "illegal_path":
        row["path"][1]=row["path"][0]
    else:
        row[corruption] += .01
    with pytest.raises(ValueError):
        b6.replay(row, graph, args, times, spec["archive_sha256"])


def test_saved_step_ledger_and_real_synthetic_separation(experiment):
    _, _, _, _, rows=experiment
    with (OUTPUT / "step_metrics.csv").open(encoding="utf-8",newline="") as f:
        ledger=list(csv.DictReader(f))
    assert len(ledger)==350
    for row in rows:
        steps=[s for s in ledger if s["run_id"]==row["run_id"]]
        assert [int(s["vertex"]) for s in steps]==row["path"]
        assert all(s["utc"].endswith("Z") for s in steps)
        assert float(steps[0]["J_t"])==float(steps[0]["delta_Pd"])==0
        for s in steps:
            assert sum(float(s[k]) for k in ("searchable","land","outside","inactive","unknown"))==pytest.approx(float(s["M_t"]),abs=1e-12)
        assert sum(float(s["M_t"]) for s in steps[1:])==pytest.approx(row["J"],abs=1e-10)
        assert float(steps[-1]["Pd_t"])==row["Pd_T"]
    environment=b6.read_json(OUTPUT / "environment_comparison.json")
    assert {"historical_real","constant_synthetic"} <= environment.keys()
    assert environment["historical_real"]["wind_site_event_stats"]["count"]==8
    with (OUTPUT / "metrics.csv").open(encoding="utf-8",newline="") as f:
        metrics=list(csv.DictReader(f))
    assert len(metrics)==7 and {r["forcing_kind"] for r in metrics}=={"historical_real"}


def test_manifest_proves_frozen_outputs_untouched():
    manifest=b6.read_json(OUTPUT / "run_manifest.json")
    assert manifest["status"]=="passed" and manifest["protected_after_unchanged"]
    assert len(manifest["verified_raw_sources"])==10
    for name, expected in manifest["protected_before_sha256"].items():
        assert b6.digest(ROOT / name)==expected
    for name, expected in manifest["artifacts_sha256"].items():
        assert b6.digest(OUTPUT / name)==expected
    for name, expected in manifest["code_sha256"].items():
        assert b6.digest(ROOT / name)==expected


def test_output_guard_preserves_old_results(tmp_path):
    with pytest.raises(ValueError,match="protected"):
        b6.check_output(ROOT / "outputs/stage7/lake_ontario")
    with pytest.raises(FileExistsError,match="fresh"):
        b6.check_output(OUTPUT)
    p=tmp_path/"paths.png"
    p.write_bytes(b"user figure")
    with pytest.raises(FileExistsError):
        b6.check_output(tmp_path)
    assert p.read_bytes()==b"user figure"
