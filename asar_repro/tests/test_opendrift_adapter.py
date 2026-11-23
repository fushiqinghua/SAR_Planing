from pathlib import Path

import numpy as np
import pytest
import xarray as xr
import yaml

from asar_repro.gridding import ParticleGrid, particle_step
from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion
from asar_repro.objective import score_path
from asar_repro.opendrift_adapter import Frames, planning_times, run_constant


def sample():
    # Deliberately unsorted original IDs and mixed orders of variable dimensions.
    ids = [42, 5, 77, 6, 9]
    times = planning_times("2025-08-26T15:45:00Z", 2, 60)
    xy = np.array([[0, 0, .05, 0, 0], [0, 0, .05, np.nan, np.nan],
                   [0, np.nan, 0, np.nan, np.nan]])
    status = np.array([[0, 0, 0, 2, 0], [0, 1, 0, np.nan, 0],
                       [0, np.nan, 0, np.nan, 0]])
    ds = xr.Dataset(coords={"trajectory": ids, "time": times})
    ds["lon"] = (("trajectory", "time"), xy.T)
    ds["lat"] = (("time", "trajectory"), xy * 0)
    ds["status"] = (("time", "trajectory"), status)
    ds.status.attrs.update(flag_values=[0, 1, 2], flag_meanings="active stranded missing_data")
    ds["land_binary_mask"] = (("time", "trajectory"), np.array([[0, 1, 0, 0, 0]] * 3))
    return ds


def test_guide_smoke_corrected_local_api():
    cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / "configs/lake_ontario_constant.yaml")
                         .read_text(encoding="utf-8"))
    cfg.update(object_key="PIW-1", cst_utc=cfg["incident_utc"], step_s=60, budget=120,
               integration_s=60, output_s=60)
    ds, obj = run_constant(cfg)
    f = Frames.from_dataset(ds)
    assert obj["number"] == 1 and obj["key"] == "PIW-1"
    assert f.lon.shape == (121, 500)
    np.testing.assert_array_equal(f.ids, ds.trajectory.values)
    np.testing.assert_array_equal(f.time_utc, planning_times(cfg["incident_utc"], 120, 60))


def test_offset_fractional_time_and_coverage():
    t = planning_times("2025-08-26T11:45:00-04:00", 2, 9.26)
    assert str(t[2]) == "2025-08-26T15:45:18.520000000"
    ds = sample()
    ds["lon"][0, :] = [0., .01, .02]
    f = Frames.from_dataset(ds).resample(t)
    np.testing.assert_array_equal(f.ids, [42, 5, 77, 6, 9])
    np.testing.assert_allclose(f.lon[:, 0], [.0, .01*9.26/60, .01*18.52/60], atol=1e-12)
    assert np.isnan(f.status[1, 1])  # Active-to-stranded interval is ambiguous.
    with pytest.raises(ValueError, match="coverage"):
        Frames.from_dataset(ds).resample(t - np.timedelta64(1, "D"))
    with pytest.raises(ValueError, match="offset"):
        planning_times("2025-08-26T15:45:00", 1, 9.26)
    with pytest.raises(ValueError, match="unique"):
        Frames.from_dataset(ds.assign_coords(trajectory=[5]*5))
    with pytest.raises(ValueError, match="explicit"):
        Frames.from_dataset(ds.drop_vars("trajectory"))


def test_land_outside_reentry_terminal_and_unknown_keep_their_weight():
    raw = Frames.from_dataset(sample())
    f = raw.resample(raw.time_utc)
    grid = ParticleGrid(GridGraph(3, 3), (0, 0), 200)
    cells = grid.assign(f)
    s = grid.special
    np.testing.assert_array_equal(cells, [[4, s["land"], s["outside"], s["inactive"], 4],
                                         [4, s["land"], s["outside"], s["inactive"], s["unknown"]],
                                         [4, s["land"], 4, s["inactive"], s["unknown"]]])
    assert np.isnan(raw.status[-1, 1]) and f.status[-1, 1] == 1
    w = np.full(5, .2)
    new, bins = particle_step(grid, cells[1], w, 4, .75)
    np.testing.assert_allclose(new, [.05, .2, .2, .2, .2])
    np.testing.assert_allclose(bins[[4, *s.values()]], [.05, .2, .2, .2, .2])
    assert new.sum() == pytest.approx(.85)
    assert bins.sum() == pytest.approx(new.sum())
    np.testing.assert_array_equal(w, np.full(5, .2))
    with pytest.raises(ValueError):
        particle_step(grid, cells[1], w, s["land"], .75)


def test_particle_and_matrix_equivalence_for_permutation_motion():
    graph = GridGraph(1, 2)
    grid = ParticleGrid(graph, (0, 0), 100)
    # Two particles in each cell, all follow the same deterministic swap.
    cells = np.array([[0, 1, 0, 1], [1, 0, 1, 0], [0, 1, 0, 1], [1, 0, 1, 0]])
    path = [0, 1, 0, 1]
    score = score_path(graph, path, start=0, budget=3, p=[.5, .5], q=.78,
                       motion=MatrixMotion.stationary([[0, 1], [1, 0]]), record_beliefs=True)
    w = np.full(4, .25)
    for t, frame in enumerate(cells):
        w, mass = particle_step(grid, frame, w, path[t] if t else None, .78)
        np.testing.assert_allclose(mass[:2], score.beliefs[t])
        assert w.sum() == pytest.approx(score.survival[t])


def test_real_or_incomplete_forcing_rejected():
    with pytest.raises(ValueError, match="constant_synthetic"):
        run_constant({"forcing_kind": "real_forcing"})
    with pytest.raises(ValueError, match="constant wind"):
        run_constant({"forcing_kind": "constant_synthetic", "forcing": {"land_binary_mask": 0}})
