"""B3 checks for indelible ID weights and fail-closed archive reuse."""

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from asar_repro.grid import GridGraph
from asar_repro.gridding import ParticleGrid
from asar_repro.historical_drift import axes, audit_mass, classify, compare_replay
from asar_repro.opendrift_adapter import Frames
from asar_repro.scenarios import config_digest, digest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_historical_drift as runner


CFG = dict(
    incident_utc="2025-08-26T14:45:00Z",
    cst_utc="2025-08-26T15:45:00Z",
    budget=49,
    step_s=9.26,
    integration_s=30,
    output_s=30,
    seed=41,
)


def test_archived_axes_include_predrift_and_exact_search_end():
    raw, target = axes(CFG)
    assert len(raw) == 137 and len(target) == 50
    assert raw[0] == np.datetime64("2025-08-26T14:45")
    assert raw[-1] == np.datetime64("2025-08-26T15:53")
    assert target[0] == np.datetime64("2025-08-26T15:45")
    assert target[-1] == np.datetime64("2025-08-26T15:52:33.740")
    assert (np.diff(raw) == np.timedelta64(30, "s")).all()
    assert (np.diff(target) == np.timedelta64(9260, "ms")).all()


def test_four_special_bins_preserve_weights_and_terminal_cause():
    ids = np.array([8, 2, 5, 7, 11, 1])
    times = axes(CFG)[1][:3]
    # columns 1 and 4: dry and outside forcing. Column 2: model inactive.
    # Column 3: active but forcing value missing. Column 5: inside the forcing
    # domain at t=0 and outside the search grid afterwards.
    lon = np.array(
        [
            [0, 0.0001, 0, 0.0003, 0.0004, 0],
            [0, np.nan, np.nan, 0.0003, np.nan, 0.01],
            [0, np.nan, np.nan, 0.0003, np.nan, 0.01],
        ]
    )
    status = np.array([[0, 1, 2, 0, 1, 0], [0, 1, 2, 0, 1, 0], [0, 1, 2, 0, 1, 0]])

    def wind(t, x, y):
        return None, np.full(len(x), "ok")

    def current(t, x, y):
        return None, np.where(x == 0.0003, "missing_component", "ok")

    bundle = SimpleNamespace(
        wind=SimpleNamespace(probe=wind), current=SimpleNamespace(probe=current)
    )
    raw = Frames(
        ids,
        times,
        lon,
        np.where(np.isfinite(lon), 0, np.nan),
        status,
        np.zeros_like(lon),
        {0: "active", 1: "missing_data", 2: "retired"},
    )
    grid = ParticleGrid(GridGraph(3, 3), (0, 0), 100.0)
    events = [
        dict(trajectory_id=id, time_utc=CFG["cst_utc"], mass_bin=category)
        for id, category in ((2, "land"), (11, "outside"))
    ]
    cell = classify(grid, raw, bundle, events)
    sp = grid.special
    expected = [4, sp["land"], sp["inactive"], sp["unknown"], sp["outside"], 4]
    np.testing.assert_array_equal(cell[0], expected)
    np.testing.assert_array_equal(cell[-1], expected[:-1] + [sp["outside"]])
    cell[1, 0] = 5  # A deliberate detection on the fixed audit route.
    audit, rows, _ = audit_mass(grid, ids, times, cell, np.full(6, 1 / 6), 0.78)
    assert rows[0]["Pd"] == 0
    assert rows[-1]["M"] == pytest.approx((5 + 0.22**2) / 6)
    assert rows[-1]["prior_outside"] == pytest.approx(2 / 6)
    assert rows[-1]["prior_total"] == pytest.approx(1.0)
    assert rows[-1]["M"] + rows[-1]["Pd"] == pytest.approx(1.0)
    np.testing.assert_allclose(audit["audit_weights"][-1], [0.22**2 / 6, *([1 / 6] * 5)])


def test_cache_rejects_changed_config_and_archive_bytes(tmp_path):
    native, target = axes(CFG)
    identity = {"config": CFG, "source_hashes": ["a"]}
    key = config_digest(identity)
    for file in runner.ARTIFACTS:
        (tmp_path / file).touch()
    np.savez(tmp_path / "particles.npz", config_hash=key, raw_time_utc=native, time_utc=target)
    meta = dict(
        config_hash=key,
        status="passed",
        artifacts_sha256={file: digest(tmp_path / file) for file in runner.ARTIFACTS},
    )
    (tmp_path / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    assert runner.read_cache(tmp_path, CFG, identity)[0] == meta
    with pytest.raises(ValueError, match="stale"):
        runner.read_cache(tmp_path, CFG, dict(identity, config=dict(CFG, seed=9)))
    (tmp_path / "particles.npz").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="artifact SHA-256"):
        runner.read_cache(tmp_path, CFG, identity)


def test_missing_velocity_archive_blocks_generation(monkeypatch, tmp_path, capsys):
    def missing(*args):
        raise FileNotFoundError("LOOFS file unavailable")

    monkeypatch.setattr(runner, "checked_inputs", missing)
    monkeypatch.setattr(
        sys, "argv", ["generate_historical_drift.py", "--output-dir", str(tmp_path / "new")]
    )
    assert runner.main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"
    assert not (tmp_path / "new").exists()


def test_replay_comparison_accepts_identical_nan_locations_only():
    data = {"trajectory_id": np.array([11, 2]), "lon": np.array([1.0, np.nan])}
    assert compare_replay(data, {k: v.copy() for k, v in data.items()}) == 2
    with pytest.raises(AssertionError, match="lon"):
        compare_replay(data, dict(data, lon=np.array([1.0, 0.0])))
