"""One historical Leeway simulation and an ID-aligned particle archive."""

from datetime import timedelta, timezone
from importlib.metadata import version
import json

import numpy as np

from .grid import GridGraph
from .gridding import ParticleGrid, particle_step
from .motion import ParticleMotion
from .objective import score_path
from .opendrift_adapter import Frames, planning_times, utc_datetime
from .scenarios import config_digest


def utc_label(value):
    return np.datetime_as_string(value, unit="ns").rstrip("0").rstrip(".") + "Z"


def axes(cfg):
    target = planning_times(cfg["cst_utc"], cfg["budget"], cfg["step_s"])
    incident = np.datetime64(utc_datetime(cfg["incident_utc"]).replace(tzinfo=None), "ns")
    dt, output = cfg["integration_s"], cfg["output_s"]
    if dt <= 0 or output <= 0 or output % dt or incident > target[0]:
        raise ValueError("invalid pre-drift time or integration/output intervals")
    span = int((target[-1] - incident).astype("timedelta64[ns]").astype(np.int64))
    interval = output * 10**9
    steps = (span + interval - 1) // interval
    native = planning_times(cfg["incident_utc"], steps, output)
    return native, target


def identity(cfg, inputs):
    packages = ("opendrift", "numpy", "scipy", "pyproj", "netCDF4", "shapely")
    return dict(
        schema=1,
        config=cfg,
        input_fingerprints=inputs,
        versions={name: version(name) for name in packages},
    )


def forcing_bins(bundle, time, lon, lat):
    """Classify paired velocity availability at actual particle positions."""
    _, wind = bundle.wind.probe(time, lon, lat)
    _, current = bundle.current.probe(time, lon, lat)
    if np.any(wind == "outside_time") or np.any(current == "outside_time"):
        raise ValueError("historical forcing does not cover the required simulation time")
    bins = np.full(len(lon), "unknown", dtype="U12")
    bins[(wind == "ok") & (current == "ok")] = "ok"
    bins[(wind == "outside_grid") | np.isin(current, ["outside_grid", "outside_mesh"])] = "outside"
    bins[current == "dry"] = "land"
    return bins, wind, current


def run_historical(cfg, bundle):
    """Integrate once and record the actual cause of velocity reader misses."""
    from opendrift.models.leeway import Leeway
    from .historical_reader import attach_historical_readers

    if cfg["forcing_kind"] != "historical_real" or bundle.forcing_kind != "historical_real":
        raise ValueError("historical run requires real wind and current")
    native, _ = axes(cfg)
    incident, end = (utc_datetime(utc_label(t)) for t in (native[0], native[-1]))
    for field in (bundle.wind, bundle.current):
        if not field.times[0] <= incident <= end <= field.times[-1]:
            raise ValueError(f"{field.role} does not bracket the rounded native output axis")

    class AuditedLeeway(Leeway):
        def report_missing_variables(self, missing):
            if np.any(missing):
                ids = self.elements.ID[missing]
                time = self.time.replace(tzinfo=timezone.utc)
                bins, wind, current = forcing_bins(
                    bundle, time, self.elements.lon[missing], self.elements.lat[missing]
                )
                for particle, category, ws, cs in zip(ids, bins, wind, current):
                    if category == "ok":
                        raise ValueError(
                            "OpenDrift reported a miss for an available wind/current pair"
                        )
                    failures.append(
                        dict(
                            trajectory_id=int(particle),
                            time_utc=time.isoformat(),
                            mass_bin=str(category),
                            wind_status=str(ws),
                            current_status=str(cs),
                        )
                    )
            super().report_missing_variables(missing)

    failures = []
    rng = np.random.get_state()
    try:
        model = AuditedLeeway(seed=cfg["seed"], loglevel=40)
        candidates = [
            n for n, props in model.leewayprop.items() if props["OBJKEY"] == cfg["object_key"]
        ]
        if len(candidates) != 1:
            raise ValueError("unknown or ambiguous local Leeway object key")
        obj = candidates[0]
        readers = attach_historical_readers(model, bundle)
        model.set_config("seed:ocean_only", False)
        model.set_config("drift:stokes_drift", False)
        lon, lat = cfg["lkp_lon_lat"]
        model.seed_elements(
            lon=lon,
            lat=lat,
            number=cfg["particles"],
            radius=cfg["radius_m"],
            time=incident.replace(tzinfo=None),
            object_type=obj,
        )
        seeded = model.elements_scheduled.ID.copy()
        ds = model.run(
            duration=end - incident,
            time_step=timedelta(seconds=cfg["integration_s"]),
            time_step_output=timedelta(seconds=cfg["output_s"]),
            stop_on_error=True,
            export_variables=["lon", "lat", "status", "land_binary_mask"],
        )
        raw = Frames.from_dataset(ds)
        if len(seeded) != cfg["particles"] or not np.array_equal(np.sort(raw.ids), np.sort(seeded)):
            raise ValueError("OpenDrift native output lost or added trajectory IDs")
        if not np.array_equal(raw.time_utc, native):
            raise ValueError("OpenDrift did not generate the complete expected native UTC axis")
        priorities = {v: model.env.priority_list[v] for r in readers for v in r.variables}
        if any(priorities[v] != [r.name] for r in readers for v in r.variables):
            raise ValueError("historical reader priority changed during integration")
        info = dict(
            object=dict(
                number=obj, key=cfg["object_key"], description=model.leewayprop[obj]["Description"]
            ),
            readers=priorities,
            integration_steps=int(model.steps_calculation),
            source_dims=list(ds.lon.dims),
        )
        return raw, failures, info
    finally:
        np.random.set_state(rng)


def classify(grid, frames, bundle, failures):
    """Use the native status, sampling domain and per-ID terminal causes in grid assignment."""
    cells = grid.assign(frames)
    active_code = next(code for code, name in frames.flags.items() if name == "active")
    active = (frames.status == active_code) & (frames.land != 1)
    for i, time in enumerate(frames.time_utc):
        index = np.flatnonzero(active[i])
        if len(index):
            bins, _, _ = forcing_bins(
                bundle, utc_datetime(utc_label(time)), frames.lon[i, index], frames.lat[i, index]
            )
            for name in ("land", "outside", "unknown"):
                cells[i, index[bins == name]] = grid.special[name]
    columns = {int(particle): i for i, particle in enumerate(frames.ids)}
    for record in failures:
        t = np.datetime64(utc_datetime(record["time_utc"]).replace(tzinfo=None), "ns")
        cells[frames.time_utc >= t, columns[record["trajectory_id"]]] = grid.special[
            record["mass_bin"]
        ]
    return cells


def audit_mass(grid, ids, times, cells, weights, q):
    graph = grid.graph
    row, col = graph.rows // 2, graph.cols // 2
    direction = 1
    path = [graph.vertex(row, col)]
    for _ in times[1:]:
        if not 0 <= col + direction < graph.cols:
            direction = -direction
        col += direction
        path.append(graph.vertex(row, col))
    motion = ParticleMotion(cells, graph.size, ids)
    score = score_path(
        graph,
        path,
        start=path[0],
        budget=len(times) - 1,
        p=weights,
        q=q,
        motion=motion,
        record_beliefs=True,
    )
    posterior = weights.copy()
    history, masses, ledger = [], [], []
    detected = 0.0
    for i, (t, frame) in enumerate(zip(times, cells)):
        _, prior = particle_step(grid, frame, weights)
        before = posterior.sum()
        vertex = path[i] if i else None
        removed = float(q * posterior[frame == vertex].sum()) if i else 0.0
        posterior, mass = particle_step(grid, frame, posterior, vertex, q)
        remaining = float(posterior.sum())
        detected += removed
        error = max(
            abs(prior.sum() - 1),
            abs(remaining + detected - 1),
            abs(before - removed - remaining),
            abs(mass.sum() - remaining),
            abs(score.survival[i] - remaining),
        )
        if error > 1e-12 or remaining > before + 1e-12:
            raise ValueError(f"mass ledger invariant failed at search step {i}")
        np.testing.assert_allclose(posterior, score.beliefs[i], rtol=0, atol=1e-14)
        ledger.append(
            dict(
                step=i,
                utc=utc_label(t),
                visited=vertex,
                particles=len(ids),
                prior_searchable=float(prior[: graph.size].sum()),
                **{f"prior_{k}": float(prior[v]) for k, v in grid.special.items()},
                prior_total=float(prior.sum()),
                posterior_searchable=float(mass[: graph.size].sum()),
                **{f"posterior_{k}": float(mass[v]) for k, v in grid.special.items()},
                M=remaining,
                Pd=detected,
                delta_Pd=removed,
                max_error=float(error),
            )
        )
        history.append(posterior)
        masses.append(mass)
    return (
        dict(
            audit_path=np.array(path),
            audit_weights=np.stack(history),
            audit_cell_mass=np.stack(masses),
        ),
        ledger,
        score.J,
    )


def build_archive(raw, failures, bundle, cfg, fingerprint):
    native, times = axes(cfg)
    np.testing.assert_array_equal(raw.time_utc, native)
    aligned = raw.resample(times)
    grid = ParticleGrid(GridGraph(*cfg["grid_rows_cols"]), cfg["csp_lon_lat"], cfg["cell_width_m"])
    raw_cells = classify(grid, raw.resample(native), bundle, failures)
    cells = classify(grid, aligned, bundle, failures)
    weights = np.full(len(raw.ids), 1 / len(raw.ids))
    audit, ledger, objective = audit_mass(grid, aligned.ids, times, cells, weights, cfg["audit_q"])
    data = dict(
        config_hash=np.array(config_digest(fingerprint)),
        trajectory_id=raw.ids,
        raw_time_utc=raw.time_utc,
        raw_lon=raw.lon,
        raw_lat=raw.lat,
        raw_status=raw.status,
        raw_land_binary_mask=raw.land,
        raw_cell_ids=raw_cells,
        time_utc=times,
        lon=aligned.lon,
        lat=aligned.lat,
        status=aligned.status,
        land_binary_mask=aligned.land,
        cell_ids=cells,
        initial_weights=weights,
        flags_json=np.array(json.dumps(raw.flags)),
        special_bins_json=np.array(json.dumps(grid.special)),
        terminal_forcing_json=np.array(json.dumps(failures)),
        **audit,
    )
    return grid, data, ledger, objective


def compare_replay(first, second):
    """Compare semantic NPZ content, including native positions, IDs and NaN locations."""
    if set(first) != set(second):
        raise ValueError("replay archive variables differ")
    for name in first:
        np.testing.assert_array_equal(
            first[name], second[name], err_msg=f"replay differs in {name}"
        )
    return len(first)
