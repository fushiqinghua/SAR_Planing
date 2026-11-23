"""Table I mission inputs and versioned constant-forcing particle preprocessing."""

from decimal import Decimal
import hashlib
from importlib.metadata import version
import json
from pathlib import Path

import numpy as np

from .grid import GridGraph
from .gridding import ParticleGrid
from .motion import ParticleMotion
from .opendrift_adapter import Frames, planning_times, run_constant, utc_datetime


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def config_digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()


def drift_config(spec, case):
    if spec["forcing_kind"] != "constant_synthetic":
        raise ValueError("stage 7 implements constant_synthetic only")
    if spec["data_availability"] != "historical_wind_current_pair_unverified_locally":
        raise ValueError("historical forcing has no validated local provenance in this experiment")
    width = Decimal(str(case["sweep_width_nm"])) * 1852
    cfg = {k: spec[k] for k in ("forcing_kind", "forcing", "seed", "radius_m", "particles")}
    cfg.update({k: case[k] for k in ("incident_utc", "cst_utc", "lkp_lon_lat", "csp_lon_lat",
                                     "object_key", "budget", "grid_rows_cols", "integration_s")})
    return dict(cfg, step_s=float(width / Decimal(str(spec["speed_m_s"]))),
                cell_width_m=float(width), output_s=case["integration_s"])


def prepare_input(root, folder, name, cfg):
    graph = GridGraph(*cfg["grid_rows_cols"])
    grid = ParticleGrid(graph, cfg["csp_lon_lat"], cfg["cell_width_m"])
    times = planning_times(cfg["cst_utc"], cfg["budget"], cfg["step_s"])
    if name == "lake_ontario":
        import yaml

        original = root / "configs/lake_ontario_constant.yaml"
        old_cfg = yaml.safe_load(original.read_bytes())
        if any(old_cfg.get(k) != value for k, value in cfg.items()):
            raise ValueError("Lake Ontario parameters differ from stage 5")
        archive = root / "outputs/particles/stage5_leeway.npz"
        meta = json.loads((root / "outputs/metrics/stage5_drift.json").read_text(encoding="utf-8"))
        if meta["config_hash"] != digest(original):
            raise ValueError("stale stage 5 manifest")
        expected = meta["config_hash"]
        obj, drift_version = meta["object"], meta["opendrift_version"]
    else:
        archive = folder / "particles.npz"
        drift_version = version("opendrift")
        expected = config_digest(dict(config=cfg, opendrift_version=drift_version, format_version=1))
        if not archive.is_file():
            ds, obj = run_constant(cfg)
            raw = Frames.from_dataset(ds)
            frames = raw.resample(times)
            tmp = folder / "particles.tmp.npz"
            np.savez_compressed(tmp, config_hash=expected, object_json=json.dumps(obj),
                                raw_time_utc=raw.time_utc, raw_lon=raw.lon, raw_lat=raw.lat,
                                raw_status=raw.status, raw_land_binary_mask=raw.land,
                                flags_json=json.dumps(raw.flags), trajectory_id=frames.ids,
                                time_utc=times, lon=frames.lon, lat=frames.lat,
                                status=frames.status, land_binary_mask=frames.land,
                                cell_ids=grid.assign(frames),
                                initial_weights=np.full(len(frames.ids), 1 / len(frames.ids)))
            tmp.replace(archive)
    with np.load(archive, allow_pickle=False) as data:
        if data["config_hash"].item() != expected:
            raise ValueError(f"stale drift input: {archive}; use a fresh output directory")
        if name != "lake_ontario":
            obj = json.loads(data["object_json"].item())
        if obj["key"] != cfg["object_key"]:
            raise ValueError("unexpected Leeway object in archive")
        np.testing.assert_array_equal(data["time_utc"], times)
        incident = np.datetime64(utc_datetime(cfg["incident_utc"]).replace(tzinfo=None), "ns")
        raw_times = data["raw_time_utc"]
        if raw_times[0] != incident or raw_times[-1] < times[-1]:
            raise ValueError("native archive must cover incident through search end")
        ids, cells, weights = data["trajectory_id"], data["cell_ids"], data["initial_weights"]
        if cells.shape != (len(times), cfg["particles"]) or weights.shape != (cfg["particles"],):
            raise ValueError("particle count or planning horizon mismatch")
        np.testing.assert_allclose(weights, np.full(len(ids), 1 / len(ids)), rtol=0, atol=1e-15)
        motion = ParticleMotion(cells, graph.size, ids)
        # CST distances use actual positions before detection, including outside-grid particles.
        x, y = grid.projection.transform(data["lon"][0], data["lat"][0])
        distances = np.hypot(x, y)
        if not np.isfinite(distances).all():
            raise ValueError("synthetic CST distance audit requires located particles")
    special = np.array([motion.cell_mass(weights, t)[graph.size:] for t in range(len(times))])
    totals = np.array([motion.cell_mass(weights, t).sum() for t in range(len(times))])
    np.testing.assert_allclose(totals, 1, atol=1e-12, rtol=0)
    metadata = dict(archive=str(Path(archive).relative_to(root)) if archive.is_relative_to(root)
                    else str(archive), archive_sha256=digest(archive), drift_config_hash=expected,
                    drift_config=cfg, object_resolved=obj, opendrift_version=drift_version,
                    predrift_hours=float((times[0] - incident) / np.timedelta64(1, "h")),
                    cst_particle_distance_m=dict(zip(("min","median","max"),
                                                     np.percentile(distances, [0, 50, 100]).tolist())),
                    cst_cloud_centroid_distance_m=float(np.hypot(np.mean(x), np.mean(y))),
                    special_bins=grid.special, prior_special_mass_by_step=special.tolist(),
                    max_prior_mass_error=float(np.max(np.abs(totals - 1))),
                    search_end_utc=np.datetime_as_string(times[-1], unit="ms") + "Z")
    return graph, motion, weights, times, metadata
