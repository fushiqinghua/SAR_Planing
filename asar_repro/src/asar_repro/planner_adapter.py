"""Standalone interface from pre-gridded UTC particle frames to discrete SAR routes."""

import json
from pathlib import Path

import numpy as np
from pyproj.enums import TransformDirection

from .grid import GridGraph
from .gridding import ParticleGrid
from .motion import ParticleMotion
from .objective import score_path
from .opendrift_adapter import planning_times
from .scenario_baselines import parallel_track
from .scenarios import config_digest, digest
from .search import search_asar


def plan_particle_path(
    *,
    grid,
    start,
    cell_ids,
    trajectory_ids,
    initial_weights,
    time_utc,
    q,
    heuristic="paper_greedy",
    epsilon=1.10,
    warm_start=True,
    max_expansions=600,
    max_open=2400,
    max_seconds=30
):
    """Return a JSON-compatible plan for a ParticleGrid. time_utc is datetime64 UTC.

    Each row of cell_ids uses the same ID columns as initial_weights. The first
    frame precedes detection. All four special bins follow the water cells.
    Warm start constructs a feasible dynamic ParallelTrack on the supplied data.
    """
    times = np.asarray(time_utc)
    if (
        times.ndim != 1
        or not times.size
        or times.dtype.kind != "M"
        or np.isnat(times).any()
        or np.any(times[1:] <= times[:-1])
    ):
        raise ValueError("time_utc must be a strictly increasing UTC datetime64 vector")
    motion = ParticleMotion(cell_ids, grid.graph.size, trajectory_ids)
    if motion.cell_ids.shape[0] != len(times):
        raise ValueError("expected one UTC instant per particle frame")
    args = dict(start=start, budget=len(times) - 1, p=initial_weights, q=q, motion=motion)
    initial = parallel_track(grid.graph, **args) if warm_start else None
    result = search_asar(
        grid.graph,
        **args,
        heuristic=heuristic,
        epsilon=epsilon,
        initial_path=initial,
        max_expansions=max_expansions,
        max_open=max_open,
        max_seconds=max_seconds
    )
    output = dict(
        status=result.status,
        stop_reason=result.stop_reason,
        incumbent_source=(
            "ParallelTrack" if result.incumbent_source == "initial_path" else result.incumbent_source
        ),
        expanded=result.expanded,
        generated=result.generated,
        pruned=result.pruned,
        peak_open=result.peak_open,
        heuristic=heuristic,
        epsilon=float(epsilon),
        discrete_model_certified=result.theory_certified,
        uav_constraints="unevaluated",
        T=len(times) - 1,
        path=None,
        waypoints=None,
        J=None,
        Pd_T=None,
        M_0_to_T=None,
    )
    if result.path is None:
        return output
    score = score_path(grid.graph, result.path, **args)
    np.testing.assert_allclose(score.J, result.J, atol=1e-10, rtol=0)
    waypoints = []
    for t, v in enumerate(result.path):
        row, col = grid.graph.coordinates(v)
        east = (col + 0.5 - grid.graph.cols / 2) * grid.width_m
        north = (grid.graph.rows / 2 - row - 0.5) * grid.width_m
        lon, lat = grid.projection.transform(east, north, direction=TransformDirection.INVERSE)
        waypoints.append(
            dict(
                t=t,
                vertex=int(v),
                row=row,
                col=col,
                lon=lon,
                lat=lat,
                utc=str(np.datetime_as_string(times[t], unit="ns")) + "Z",
            )
        )
    output.update(
        path=list(map(int, result.path)),
        waypoints=waypoints,
        J=score.J,
        Pd_T=score.pd_final,
        M_0_to_T=score.survival.tolist(),
    )
    return output


def plan_from_bundle(manifest, scenario, **search_options):
    """Plan offline using one mission in the portable stage 8 particle bundle."""
    manifest = Path(manifest)
    bundle = json.loads(manifest.read_text(encoding="utf-8"))
    if bundle["format_version"] != 1:
        raise ValueError("unsupported particle bundle version")
    entry = bundle["scenarios"][scenario]
    metadata_hash = config_digest({k: v for k, v in entry.items() if k != "metadata_sha256"})
    if metadata_hash != entry["metadata_sha256"]:
        raise ValueError("mission metadata SHA-256 mismatch")
    archive = manifest.parent / entry["archive"]
    if digest(archive) != entry["archive_sha256"]:
        raise ValueError("particle archive SHA-256 mismatch")
    cfg = entry["drift_config"]
    graph = GridGraph(*cfg["grid_rows_cols"])
    grid = ParticleGrid(graph, cfg["csp_lon_lat"], cfg["cell_width_m"])
    if entry["special_bins"] != grid.special:
        raise ValueError("particle archive special-bin convention mismatch")
    times = planning_times(cfg["cst_utc"], cfg["budget"], cfg["step_s"])
    with np.load(archive, allow_pickle=False) as data:
        if data["config_hash"].item() != entry["drift_config_hash"]:
            raise ValueError("particle archive drift configuration mismatch")
        if not np.array_equal(data["time_utc"], times):
            raise ValueError("particle archive UTC clock mismatch")
        if data["cell_ids"].shape != (len(times), cfg["particles"]):
            raise ValueError("unexpected particle archive dimensions")
        result = plan_particle_path(
            grid=grid,
            start=entry["start_vertex"],
            q=entry["q"],
            cell_ids=data["cell_ids"],
            trajectory_ids=data["trajectory_id"],
            initial_weights=data["initial_weights"],
            time_utc=times,
            **(entry["search_limits"] | search_options)
        )
    result.update(
        scenario=scenario,
        archive_sha256=entry["archive_sha256"],
        forcing_kind=cfg["forcing_kind"],
        data_availability=entry["data_availability"],
    )
    return result
