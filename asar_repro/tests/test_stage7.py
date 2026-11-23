import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path
from asar_repro.opendrift_adapter import planning_times, utc_datetime
from asar_repro.scenario_baselines import aco_inspired, parallel_track
from asar_repro.scenarios import drift_config, prepare_input
from asar_repro.search import search_asar


ROOT = Path(__file__).resolve().parents[1]
SPEC = yaml.safe_load((ROOT / "configs/stage7_scenarios.yaml").read_bytes())


@pytest.mark.parametrize("name,hours,width,budget,object_key,wind,current", [
    ("lake_ontario", 1, 185.2, 49, "PIW-2", "HRRR", "LOOFS"),
    ("bay_of_fundy", 9, 740.8, 55, "PIW-1", "HRRR", "GoMOFS"),
    ("salish_sea", 11, 2963.2, 41, "FISHING-VESSEL-1", "HRRR", "CIOPS Salish Sea"),
    ("arctic_ocean", 24, 926, 60, "LIFE-RAFT-DB-10", "GFS", "ESPC-D-V02"),
])
def test_mission_clock_scale_and_sources(name, hours, width, budget, object_key, wind, current):
    case = SPEC["scenarios"][name]
    cfg = drift_config(SPEC, case)
    assert (cfg["cell_width_m"], cfg["budget"], cfg["object_key"]) == (width, budget, object_key)
    assert (case["wind"], case["current"]) == (wind, current)
    assert all(SPEC["archive_catalogs"][k].startswith("https://") for k in [wind, current])
    assert (utc_datetime(case["cst_utc"]) - utc_datetime(case["incident_utc"])).total_seconds() == 3600*hours
    frames = planning_times(cfg["cst_utc"], budget, cfg["step_s"])
    assert len(frames) == budget+1
    np.testing.assert_allclose(np.diff(frames)/np.timedelta64(1,"s"), width/20, atol=1e-12, rtol=0)
    if name == "arctic_ocean":
        assert str(frames[0]).startswith("2025-08-30T00:00:00")
        assert case["alias"] == "hudsons_bay"


@pytest.mark.parametrize("override", [{"forcing_kind":"real_forcing"},{"data_availability":"verified_original"}])
def test_synthetic_provenance_cannot_be_upgraded(override):
    with pytest.raises(ValueError):
        drift_config(SPEC | override, SPEC["scenarios"]["lake_ontario"])


def test_stage5_lake_alignment_and_hash(tmp_path):
    cfg = drift_config(SPEC, SPEC["scenarios"]["lake_ontario"])
    grid, motion, p, times, meta = prepare_input(ROOT, tmp_path, "lake_ontario", cfg)
    old = json.loads((ROOT / "outputs/metrics/stage6_particles.json").read_text())
    assert meta["archive_sha256"] == old["archive_sha256"]
    assert motion.cell_ids.shape == (50,500)
    assert len(times) == 50 and grid.rows == grid.cols == 17 and p.sum() == pytest.approx(1)
    with pytest.raises(ValueError, match="differ from stage 5"):
        prepare_input(ROOT, tmp_path, "lake_ontario", cfg | {"budget":48})


def test_parallel_track_reacts_to_drift_and_keeps_special_mass():
    grid = GridGraph(3, 3)
    # At t=0 both inputs coincide. 60% is outside; only the other ID can be detected.
    outside = grid.size+1
    p = np.array([.4,.6])
    for destination, first_visit in [(1,1), (7,7)]:
        motion = ParticleMotion([[4, outside], [destination,outside], [destination,outside]], 9, [6,42])
        args = dict(start=4, budget=2, p=p, q=.5, motion=motion)
        path = parallel_track(grid, **args)
        assert path[1] == first_visit
        score = score_path(grid, path, **args)
        np.testing.assert_allclose(score.survival,[1,.8,.8])
        assert score.J == pytest.approx(1.6)
        np.testing.assert_array_equal(p,[.4,.6])


def test_parallel_track_alternating_legs_and_t0():
    grid = GridGraph(3,3)
    motion = ParticleMotion(np.tile(np.arange(9),(10,1)),9,np.arange(9))
    args = dict(start=0,budget=8,p=np.full(9,1/9),q=1.,motion=motion)
    path = parallel_track(grid, **args)
    assert path == (0,1,2,5,4,3,6,7,8)
    np.testing.assert_allclose(score_path(grid,path,**args).survival, 1-np.arange(9)/9)


def test_same_scorer_for_ants_and_interrupted_search():
    grid = GridGraph(2,3)
    motion = ParticleMotion(np.tile(np.arange(6),(7,1)),6,np.arange(6))
    args = dict(start=0,budget=6,p=np.array([.05,.15,.05,.28,.40,.07]),q=.78,motion=motion)
    pt = parallel_track(grid, **args)
    result = search_asar(grid,**args,heuristic="paper_greedy",initial_path=pt,max_expansions=0)
    assert (result.path, result.status, result.stop_reason, result.incumbent_source) == (
        pt,"budget_exceeded","max_expansions","initial_path")
    assert result.J == pytest.approx(score_path(grid,pt,**args).J)
    assert not result.theory_certified
    ant = aco_inspired(grid,args,SPEC["aco"],71)
    assert ant == aco_inspired(grid,args,SPEC["aco"],71)
    score = score_path(grid,ant,**args)
    assert score.J == pytest.approx(sum(score.survival[1:]))
