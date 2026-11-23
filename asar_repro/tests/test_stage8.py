import csv
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from asar_repro.grid import GridGraph
from asar_repro.gridding import ParticleGrid
from asar_repro.planner_adapter import plan_from_bundle, plan_particle_path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/processed/manifest.json"


@pytest.fixture
def mission():
    return dict(
        grid=ParticleGrid(GridGraph(1, 2), (-76.5, 44.2), 100),
        start=0,
        time_utc=np.array(
            ["2025-08-26T23:59:58", "2025-08-27T00:00:03", "2025-08-27T00:00:08"], dtype="datetime64[ns]"
        ),
        trajectory_ids=[37, 12],
        cell_ids=[[0, 3], [1, 3], [0, 3]],
        initial_weights=[0.6, 0.4],
        q=0.5,
    )


def test_adapter_discrete_path_geometry_and_mass(mission):
    result = plan_particle_path(**mission, heuristic="zero", epsilon=1)
    assert result["path"] == [0, 1, 0]
    np.testing.assert_allclose(result["M_0_to_T"], [1, 0.7, 0.55])
    assert result["J"] == pytest.approx(1.25)
    assert result["Pd_T"] == pytest.approx(0.45)
    for wp, expected in zip(result["waypoints"], [-50, 50, -50], strict=True):
        x, y = mission["grid"].projection.transform(wp["lon"], wp["lat"])
        np.testing.assert_allclose([x, y], [expected, 0], atol=1e-6)
    assert result["waypoints"][1]["utc"] == "2025-08-27T00:00:03.000000000Z"
    assert result["uav_constraints"] == "unevaluated"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("warm_start", [False, True])
def test_adapter_budget_stop_has_explicit_outcome(mission, warm_start):
    result = plan_particle_path(**mission, warm_start=warm_start, max_seconds=0.0)
    assert result["status"] == "budget_exceeded" and result["stop_reason"] == "max_seconds"
    assert result["discrete_model_certified"] is False
    if warm_start:
        assert result["path"] == [0, 1, 0] and result["incumbent_source"] == "ParallelTrack"
    else:
        assert all(
            result[k] is None for k in ("path", "waypoints", "J", "Pd_T", "M_0_to_T", "incumbent_source")
        )


@pytest.mark.parametrize(
    "times",
    [
        np.array(["2025-01-01", "2025-01-01", "2025-01-02"], dtype="datetime64[D]"),
        np.array(["2025-01-01", "2025-01-02"], dtype="datetime64[D]"),
        ["2025-01-01"],
    ],
)
def test_clock_must_align(mission, times):
    with pytest.raises(ValueError, match="UTC"):
        plan_particle_path(**(mission | dict(time_utc=times)))


def test_bundle_integrity(tmp_path):
    bundle = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entry = bundle["scenarios"]["lake_ontario"]
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(bundle), encoding="utf-8")
    (tmp_path / entry["archive"]).write_bytes(b"damaged particle file")
    with pytest.raises(ValueError, match="archive SHA-256"):
        plan_from_bundle(manifest, "lake_ontario")
    entry["drift_config"]["forcing_kind"] = "real_forcing"
    manifest.write_text(json.dumps(bundle), encoding="utf-8")
    with pytest.raises(ValueError, match="metadata SHA-256"):
        plan_from_bundle(manifest, "lake_ontario")


def test_offline_adapter_matches_saved_search_without_importing_leeway(tmp_path):
    code = """import json, sys
from asar_repro.planner_adapter import plan_from_bundle
result = plan_from_bundle(sys.argv[1], 'lake_ontario', epsilon=1.10)
assert 'opendrift' not in sys.modules
print(json.dumps(result,allow_nan=False))
"""
    result = json.loads(
        subprocess.check_output([sys.executable, "-c", code, str(MANIFEST)], cwd=tmp_path)
    )
    recorded = json.loads(
        (ROOT / "outputs/stage7/lake_ontario/results.json").read_text(encoding="utf-8")
    )
    ref = next(r for r in recorded["runs"] if r["method"] == "ASAR_paper" and r["epsilon"] == 1.1)
    assert result["path"] == ref["path"] and result["J"] == pytest.approx(ref["J"])
    assert result["Pd_T"] == pytest.approx(ref["Pd_T"]) and not result["discrete_model_certified"]
    assert result["expanded"] == ref["expanded"] and result["status"] == ref["status"]
    assert [p["vertex"] for p in result["waypoints"]] == ref["path"]
    assert result["waypoints"][0]["lon"] == pytest.approx(-76.496)
    assert result["waypoints"][0]["lat"] == pytest.approx(44.215)


def test_report_experiment_keys_and_dynamic_labels():
    with (ROOT / "outputs/metrics/summary.csv").open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    keys = {(r["config_hash"], r["seed"], r["algorithm"], r["epsilon"]) for r in rows}
    assert len(keys) == len(rows)
    marine = [r for r in rows if r["stage"] == "7"]
    with (ROOT / "outputs/stage7/metrics.csv").open(encoding="utf-8-sig") as handle:
        original = list(csv.DictReader(handle))
    assert len(marine) == len(original)
    for row, source in zip(marine, original, strict=True):
        assert row["config_hash"] == source["config_hash"]
        assert float(row["J"]) == float(source["J"]) and row["status"] == source["status"]
        assert row["reference_kind"] == "ParallelTrack" and row["theory_certified"] == "False"
    assert sum(r["timing_scope"] == "cProfile_solver" for r in rows) == 1
