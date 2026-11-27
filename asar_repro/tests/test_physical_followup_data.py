"""Local tests for H1 input gates; integration is replaced by explicit fixtures.

These tests are delivered without execution.  No test invokes OpenDrift,
downloads forcing, searches paths, or requires the real raw B1 data packages.
"""

from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys

import numpy as np
import pytest

from asar_repro import physical_followup_data as data
from asar_repro.historical_drift import axes
from asar_repro.scenarios import config_digest


ROOT = Path(__file__).resolve().parents[1]


def test_registered_cases_preserve_base_geometry_uncertainty_and_horizon():
    baseline = json.loads((ROOT / "configs/stdc_final_assessment.json").read_text(encoding="utf-8"))
    expected_seeds = (1041, 1042, 2041, 2042)
    expected_shifts = (-3600, 3600, -7200, 7200)
    for case, seed, shift in zip(data.registered_cases(), expected_seeds, expected_shifts):
        original = baseline["scenes"][case["base_scene"]]["mission"]
        cfg = data.case_config(case)
        assert cfg["seed"] == seed
        assert (data._utc(cfg["incident_utc"]) - data._utc(original["incident_utc"])).total_seconds() == shift
        assert (data._utc(cfg["cst_utc"]) - data._utc(original["cst_utc"])).total_seconds() == shift
        for key in set(cfg) - {"seed", "incident_utc", "cst_utc"}:
            assert cfg[key] == original[key]
        native, target = axes(cfg)
        assert target[-1] == np.datetime64(data._utc(case["end_utc"]).replace(tzinfo=None), "ns")
        window = data._INPUTS[case["base_scene"]]["coverage_utc"]
        first, last = (np.datetime64(data._utc(t).replace(tzinfo=None), "ns") for t in window)
        assert first <= native[0] <= native[-1] <= last
    cases = data.registered_cases()
    cases[0]["seed"] = 7
    assert data.registered_cases()[0]["seed"] == 1041


@pytest.mark.parametrize("key,value", [
    ("seed", 41), ("seed", True), ("lkp_utc", "2025-08-26T14:45:00Z"),
    ("base_scene", "bay_of_fundy"), ("id", "replacement_seed"),
    ("cst_utc", "2025-08-26T16:45:00Z")])
def test_case_parameters_cannot_be_tuned_after_registration(key, value):
    case = data.registered_cases()[0]
    case[key] = value
    with pytest.raises(ValueError, match="frozen|Unknown"):
        data.case_config(case)


def test_case_rejects_undeclared_spatial_override():
    case = dict(data.registered_cases()[0], csp_lon_lat=[0, 0])
    with pytest.raises(ValueError, match="fields"):
        data.case_config(case)


@pytest.fixture
def forcing_root(tmp_path, monkeypatch):
    """Tiny byte fixtures exercise checksum gates, never real forcing readers."""
    def write(relative, content):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = content if isinstance(content, bytes) else json.dumps(content).encode()
        path.write_bytes(payload)
        return hashlib.sha256(payload).hexdigest()

    shared = dict(path="configs/stage7_scenarios.yaml", sha256=write("configs/stage7_scenarios.yaml", b"fixture mission"))
    fixed = {}
    for scene in ("lake_ontario", "arctic_ocean"):
        sources = {}
        for role in ("wind", "current"):
            relative = f"data/raw/historical/{scene}/{role}.bin"
            sources[role] = dict(local_files=[dict(local_path=relative, sha256=write(relative, role.encode()))])
        manifest = dict(scenarios=[dict(scenario=scene, forcing_kind="historical_real",
                                        pair_status="verified", **sources)])
        manifest_path, b2_path = f"data/manifests/{scene}.json", f"outputs/{scene}/forcing_audit.json"
        fixed[scene] = dict(manifest_path=manifest_path, manifest_sha256=write(manifest_path, manifest),
                            b2_path=b2_path, b2_sha256=write(b2_path, dict(status="passed")),
                            coverage_utc=deepcopy(data._INPUTS[scene]["coverage_utc"]))
    monkeypatch.setattr(data, "_STAGE7", shared)
    monkeypatch.setattr(data, "_INPUTS", fixed)
    return tmp_path


def test_inventory_is_read_only_and_checks_each_native_file(forcing_root, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Checksum inspection must not load or integrate forcing")
    monkeypatch.setattr(data, "_load_bundle", forbidden)
    monkeypatch.setattr(data, "_generate", forbidden)
    before = {p.relative_to(forcing_root): p.read_bytes() for p in forcing_root.rglob("*") if p.is_file()}
    report = data.forcing_inventory(forcing_root)
    after = {p.relative_to(forcing_root): p.read_bytes() for p in forcing_root.rglob("*") if p.is_file()}
    assert before == after
    assert report["status"] == "ready" and report["errors"] == []
    assert report["network_downloads"] is False
    assert report["raw_forcing_tracked_in_git"] is False
    assert all(len(scene["sources"]) == 2 for scene in report["scenes"].values())
    assert all(row["status"] == "verified" for scene in report["scenes"].values() for row in scene["sources"])


def test_inventory_reports_all_missing_and_mismatched_files(forcing_root):
    (forcing_root / "data/raw/historical/lake_ontario/wind.bin").write_bytes(b"changed")
    (forcing_root / "data/raw/historical/arctic_ocean/current.bin").unlink()
    report = data.forcing_inventory(forcing_root)
    assert report["status"] == "blocked"
    assert any("hash_mismatch" in error and "lake_ontario/wind.bin" in error for error in report["errors"])
    assert any("missing" in error and "arctic_ocean/current.bin" in error for error in report["errors"])
    assert "not tracked in Git" in report["recovery"]
    assert "No download" in report["recovery"]


def test_missing_package_blocks_before_generation_and_retains_failure(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Missing data must block before generation")
    monkeypatch.setattr(data, "_generate", forbidden)
    destination = tmp_path / "attempt"
    case = data.registered_cases()[0]
    with pytest.raises(data.InputBlockedError, match="not tracked in Git"):
        data.prepare_case(tmp_path / "empty_root", case, destination)
    assert (destination / "input_validation.json").exists()
    assert (destination / "request.json").exists()
    assert (destination / "prepare.log").exists()
    failure = json.loads((destination / "failure.json").read_text())
    assert failure["status"] == "blocked" and failure["overwrite_allowed"] is False
    assert not (destination / "particles.npz").exists()
    assert not (destination / "manifest.json").exists()
    with pytest.raises(FileExistsError, match="overwrite"):
        data.prepare_case(tmp_path, case, destination)


def test_even_an_empty_existing_destination_is_not_overwritten(tmp_path):
    destination = tmp_path / "empty"
    destination.mkdir()
    with pytest.raises(FileExistsError):
        data.prepare_case(tmp_path, data.registered_cases()[0], destination)
    assert list(destination.iterdir()) == []


def fixture_generation(root, case, cfg, inventory, sources):
    """Located stationary particles plus one unsearchable particle; no model."""
    native, target = axes(cfg)
    count, frames = cfg["particles"], cfg["budget"] + 1
    rows, cols = cfg["grid_rows_cols"]
    size, center = rows * cols, (rows // 2) * cols + cols // 2
    special = {name: size + i for i, name in enumerate(("land", "outside", "inactive", "unknown"))}
    cells = np.full((frames, count), center, dtype=np.int32)
    cells[:, 0] = special["outside"]
    lon = np.full((frames, count), cfg["csp_lon_lat"][0])
    lat = np.full((frames, count), cfg["csp_lon_lat"][1])
    lon[:, 0] = np.nan
    weights = np.full(count, 1 / count)
    fingerprint = dict(schema=1, config=cfg, input_fingerprints=dict(case_spec=case), versions={})
    arrays = dict(
        config_hash=np.array(config_digest(fingerprint)), trajectory_id=np.arange(count),
        time_utc=target, cell_ids=cells, initial_weights=weights, lon=lon, lat=lat,
        status=np.zeros_like(cells), land_binary_mask=np.zeros_like(cells), raw_time_utc=native,
        raw_lon=np.full((len(native), count), cfg["csp_lon_lat"][0]),
        raw_lat=np.full((len(native), count), cfg["csp_lon_lat"][1]),
        raw_status=np.zeros((len(native), count)), raw_land_binary_mask=np.zeros((len(native), count)),
        flags_json=np.array(json.dumps({0: "active"})), special_bins_json=np.array(json.dumps(special)))
    ledger = [dict(max_error=0.0, prior_searchable=1 - 1 / count, prior_outside=1 / count,
                   prior_land=0.0, prior_inactive=0.0, prior_unknown=0.0) for _ in target]
    print("fixture stdout marker")
    print("fixture stderr marker", file=sys.stderr)
    return arrays, dict(provenance=fingerprint, model=dict(fixture=True), opendrift_runs=0), ledger, dict(fixture=True)


@pytest.fixture
def prepared_case(tmp_path, monkeypatch):
    inventory = dict(status="ready", scenes={scene: dict(status="ready", errors=[]) for scene in data._MISSIONS})
    monkeypatch.setattr(data, "forcing_inventory", lambda root: inventory)
    monkeypatch.setattr(data, "_source_fingerprints", lambda root: {"fixture.py": "fixture"})
    monkeypatch.setattr(data, "_generate", fixture_generation)
    case = data.registered_cases()[0]
    destination = tmp_path / case["id"]
    manifest = data.prepare_case(tmp_path, case, destination)
    return tmp_path, case, destination, manifest


def test_prepare_and_load_preserve_shared_clock_identity_and_special_mass(prepared_case):
    root, case, destination, returned = prepared_case
    manifest_path = destination / "manifest.json"
    assert returned["manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert "manifest_sha256" not in json.loads(manifest_path.read_text())
    log = (destination / "prepare.log").read_text()
    assert "fixture stdout marker" in log and "fixture stderr marker" in log
    problem, graph, discrete, info = data.load_prepared_case(root, case, destination, "heading_square")
    assert info["independence_level"] == "same_forcing_shifted_window_new_seed"
    assert info["manifest_sha256"] == returned["manifest_sha256"]
    assert problem.start == discrete["start"] == graph.vertex(8, 8)
    assert discrete["budget"] == problem.tick_count == 49
    assert problem.q == discrete["q"] == 0.78
    assert problem.speed_m_s == 20.0
    assert problem.initial_weights.sum() == pytest.approx(1.0)
    assert np.array_equal(problem.initial_weights, discrete["p"])
    assert np.array_equal(problem.trajectory_ids, discrete["motion"].trajectory_ids)
    assert not problem.searchable[:, 0].any()
    assert info["special_mass_by_step"] == [pytest.approx(0.002)] * 50
    assert info["masked_nonfinite_unsearchable_positions"] == 50
    assert info["raw_forcing_reaudited"] is False
    axis = data.load_prepared_case(root, case, destination, "axis_square")[0]
    assert np.array_equal(problem.positions_xy, axis.positions_xy)
    assert np.array_equal(problem.times_s, axis.times_s)


def test_successful_archive_cannot_be_overwritten(prepared_case):
    root, case, destination, returned = prepared_case
    before = (destination / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        data.prepare_case(root, case, destination)
    assert (destination / "manifest.json").read_bytes() == before


def test_loader_never_invokes_forcing_or_integration(prepared_case, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Prepared archive loading must not access forcing or integrate")
    root, case, destination, _ = prepared_case
    monkeypatch.setattr(data, "_load_bundle", forbidden)
    monkeypatch.setattr(data, "_generate", forbidden)
    monkeypatch.setattr(data, "forcing_inventory", forbidden)
    data.load_prepared_case(root, case, destination, "heading_square")


def test_entirely_outside_but_conserved_archive_remains_an_h1_case():
    case = data.registered_cases()[0]
    cfg = data.case_config(case)
    arrays = fixture_generation(None, case, cfg, {}, {})[0]
    outside = cfg["grid_rows_cols"][0] * cfg["grid_rows_cols"][1] + 1
    arrays["cell_ids"][:] = outside
    arrays["lon"][:] = np.nan
    problem, graph, discrete, info = data._physical_inputs(arrays, cfg, "heading_square")
    assert not problem.searchable.any()
    assert problem.initial_weights.sum() == pytest.approx(1.0)
    assert info["special_mass_by_step"] == [pytest.approx(1.0)] * 50
    assert np.all(discrete["motion"].cell_ids == graph.size + 1)


def test_retained_library_log_stream_forwards_to_current_case(tmp_path, monkeypatch):
    stream = io.StringIO()
    old_path, current_path = tmp_path / "old.log", tmp_path / "current.log"
    with old_path.open("w", encoding="utf-8") as old_log:
        retained = data._Tee(stream, old_log, "stderr")
        retained.write("first case\n")
    frozen = old_path.read_bytes()
    with current_path.open("w", encoding="utf-8") as current_log:
        current = data._Tee(stream, current_log, "stderr")
        monkeypatch.setattr(sys, "stderr", current)
        retained.write("second case retained handler\n")
        retained.flush()
    assert old_path.read_bytes() == frozen
    assert current_path.read_text() == "second case retained handler\n"


@pytest.mark.parametrize("name", ["particles.npz", "metadata.json", "input_validation.json", "prepare.log"])
def test_loader_rejects_any_changed_deliverable(prepared_case, name):
    root, case, destination, _ = prepared_case
    with (destination / name).open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(ValueError, match="checksum mismatch"):
        data.load_prepared_case(root, case, destination, "heading_square")


def test_loader_rejects_another_registered_case(prepared_case):
    root, _, destination, _ = prepared_case
    with pytest.raises(ValueError, match="registered H1 task"):
        data.load_prepared_case(root, data.registered_cases()[1], destination, "heading_square")


@pytest.mark.parametrize("damage", ["clock", "weight", "negative_cell", "mapping", "duplicate_id", "native_clock"])
def test_physical_inputs_reject_corrupt_archive_semantics(damage):
    case = data.registered_cases()[0]
    cfg = data.case_config(case)
    arrays = fixture_generation(None, case, cfg, {}, {})[0]
    if damage == "clock":
        arrays["time_utc"][1] += np.timedelta64(1, "ns")
    elif damage == "native_clock":
        arrays["raw_time_utc"][-1] -= np.timedelta64(1, "s")
    elif damage == "weight":
        arrays["initial_weights"][0] = 0.0
    elif damage == "negative_cell":
        arrays["cell_ids"][0, 1] = -1
    elif damage == "mapping":
        arrays["cell_ids"][0, 1] += 1
    else:
        arrays["trajectory_id"][1] = arrays["trajectory_id"][0]
    with pytest.raises(ValueError):
        data._physical_inputs(arrays, cfg, "heading_square")


def test_integration_error_retains_logs_and_blocks_all_loading(tmp_path, monkeypatch):
    case = data.registered_cases()[0]
    monkeypatch.setattr(data, "forcing_inventory", lambda root: dict(
        status="ready", scenes={case["base_scene"]: dict(status="ready", errors=[])}))
    monkeypatch.setattr(data, "_source_fingerprints", lambda root: {})
    def failing(*args):
        print("before model failure")
        print("error detail", file=sys.stderr)
        raise RuntimeError("declared fixture failure")
    monkeypatch.setattr(data, "_generate", failing)
    destination = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="declared fixture failure"):
        data.prepare_case(tmp_path, case, destination)
    log = (destination / "prepare.log").read_text()
    assert "before model failure" in log and "error detail" in log
    assert "declared fixture failure" in log
    assert (destination / "failure.json").exists()
    assert not (destination / "manifest.json").exists()
    with pytest.raises(data.InputBlockedError, match="recorded failure"):
        data.load_prepared_case(tmp_path, case, destination, "heading_square")
