"""B5 input integrity, measurement isolation, explicit failure handling and saved evidence."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from asar_repro.oracle import enumerate_oracle
from asar_repro.scenarios import digest
from asar_repro.search_reporting import REQUIRED_FIELDS

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/benchmark_b5.py"
module_spec = importlib.util.spec_from_file_location("b5_benchmark_test_module", SCRIPT)
b5 = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(b5)


@pytest.fixture
def toy_input(tmp_path):
    cfg = dict(grid_rows_cols=[2, 2], cst_utc="2025-08-26T15:45:00Z", budget=3,
               step_s=1, particles=4, audit_q=.78, seed=42)
    archive = tmp_path / "particles.npz"
    times = b5.planning_times(cfg["cst_utc"], cfg["budget"], cfg["step_s"])
    np.savez_compressed(archive, cell_ids=np.tile(np.arange(4), (4, 1)),
                        trajectory_id=[12, 4, 72, 9], initial_weights=[.1, .2, .3, .4],
                        time_utc=times, config_hash="toy")
    meta = dict(status="passed", forcing_kind="historical_real", scenario="toy_fixture",
                experiment_label="test_fixture_only", shoreline_policy="allwater", config_hash="toy",
                provenance=dict(config=cfg, input_fingerprints=dict(manifest_sha256="test_only")),
                artifacts_sha256={"particles.npz": digest(archive)})
    meta_file = tmp_path / "metadata.json"
    b5.save_json(meta_file, meta)
    spec = dict(archive=str(archive), archive_sha256=digest(archive), metadata=str(meta_file),
                metadata_sha256=digest(meta_file), watchdog_grace_s=10, threads=1)
    b5.save_json(tmp_path / "config.json", spec)
    return spec, tmp_path


def test_loader_rejects_changed_archive_and_utc(toy_input):
    spec, output = toy_input
    graph, args, _ = b5.load_input(spec)
    assert args["motion"].cell_ids.shape == (4, 4) and args["start"] == 3
    path = Path(spec["archive"])
    with np.load(path, allow_pickle=False) as a:
        data = dict(a)
    data["time_utc"] = data["time_utc"] + np.timedelta64(1, "s")
    np.savez_compressed(path, **data)
    with pytest.raises(ValueError, match="SHA-256"):
        b5.load_input(spec)
    spec["archive_sha256"] = digest(path)
    meta = b5.read_json(spec["metadata"])
    meta["artifacts_sha256"]["particles.npz"] = digest(path)
    b5.save_json(spec["metadata"], meta)
    spec["metadata_sha256"] = digest(Path(spec["metadata"]))
    with pytest.raises(ValueError, match="UTC"):
        b5.load_input(spec)


@pytest.mark.parametrize("diagnostics", [None, "cprofile", "memory"])
def test_worker_replays_and_matches_oracle_without_drift(toy_input, diagnostics):
    spec, output = toy_input
    warm = b5.prepare_warm(spec, output)
    options = dict(heuristic="mass_lb", epsilon=1., max_seconds=30, max_expansions=2000, max_open=2000)
    row = b5.isolated_run(spec, output / "config.json", output, options, "profile", diagnostics)
    graph, args, _ = b5.load_input(spec)
    exact = enumerate_oracle(graph, **args)
    assert set(REQUIRED_FIELDS) <= row.keys()
    assert row["J"] == pytest.approx(exact.J) and row["path"] in [list(p) for p in exact.tied_paths]
    assert row["discrete_model_certified"] and row["independent_replay_error"] <= 1e-10
    assert row["peak_process_MiB"] > 0 and row["total_wall_s"] == row["planner_wall_s"] + warm["warm_start_s"]
    assert row["diagnostics"] == diagnostics and not row["opendrift_imported"]
    assert (row["search_allocation_peak_MiB"] is not None) == (diagnostics == "memory")
    if diagnostics == "cprofile":
        assert (output / "profile.prof").is_file() and (output / "profile_stats.json").is_file()


def test_timeout_preserves_pt_but_never_certificate(toy_input):
    spec, output = toy_input
    warm = b5.prepare_warm(spec, output)
    options = dict(heuristic="mass_lb", epsilon=1., max_seconds=0, max_expansions=2000, max_open=2000)
    row = b5.isolated_run(spec, output / "config.json", output, options, "timeout")
    assert row["path"] == warm["path"] and row["J"] == warm["J"]
    assert row["stop_reason"] == "max_seconds" and row["incumbent_source"] == "ParallelTrack"
    assert row["theoretical_bound_applicable"] and not row["discrete_model_certified"]


@pytest.mark.parametrize("failure", ["timeout", "crash"])
def test_parent_records_watchdog_or_crash_as_null(toy_input, monkeypatch, failure):
    spec, output = toy_input
    options = dict(heuristic="paper_greedy", epsilon=1., max_seconds=0, max_expansions=10, max_open=10)
    def fake_run(cmd, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        return subprocess.CompletedProcess(cmd, returncode=2, stdout="", stderr="test worker failed")
    monkeypatch.setattr(b5.subprocess, "run", fake_run)
    row = b5.isolated_run(spec, output / "config.json", output, options, "failure")
    assert all(row[k] is None for k in ("path", "J", "Pd_T", "M_T"))
    assert not row["discrete_model_certified"] and not row["found_feasible_path"]
    assert row["stop_reason"] == ("worker_watchdog" if failure == "timeout" else "worker_error")
    assert b5.read_json(output / "failure.json") == row


def test_saved_scan_coverage_status_and_frozen_input():
    folder = ROOT / "outputs/baseline_v1.1/b5"
    manifest = b5.read_json(folder / "scan_manifest.json")
    spec = manifest["config"]
    rows = b5.read_json(folder / "scan_runs.json")
    main = [r for r in rows if r["max_open"] == spec["max_open"]]
    expected = {(r["heuristic"], r["epsilon"], r["max_expansions"], r["max_seconds"]) for r in b5.run_options(spec)}
    assert len(main) == len(expected) == 36 and len(rows) == 38
    assert {(r["heuristic"], r["epsilon"], r["max_expansions"], r["max_seconds"]) for r in main} == expected
    assert digest(ROOT / spec["archive"]) == spec["archive_sha256"]
    assert digest(ROOT / spec["metadata"]) == spec["metadata_sha256"]
    assert sum(r["search_completed"] for r in main) == 10
    assert sum(r["stop_reason"] == "max_expansions" for r in main) == 26
    assert sum(r["stop_reason"] == "max_open" for r in rows) == 2
    assert not any(r["discrete_model_certified"] for r in rows)
    assert max(r["independent_replay_error"] for r in rows) <= 1e-10
    for row in rows:
        assert row["forcing_kind"] == "historical_real" and row["experiment_label"] == "historical_real_forcing_allwater"
        assert row["T"] == 49 and row["q"] == .78 and row["seed"] == 41
        if row["stop_reason"]:
            assert row["incumbent_source"] == "ParallelTrack" and row["J_over_PT"] == 1
        if row["heuristic"] == "paper_greedy" and row["epsilon"] == 1.04 and row["max_expansions"] >= 2000 and row["max_open"] == 20000:
            assert row["expanded"] == 1222 and row["search_completed"]
    summary = b5.read_json(folder / "summary.json")
    assert not summary["implementation_changed"]
    assert all(p["identical_path_score_counters"] for p in summary["before_after"])
