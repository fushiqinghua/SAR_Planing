"""Generate and audit the synthetic stage 5 Lake Ontario particle input."""

import argparse
import csv
import hashlib
import json
from importlib.metadata import version
from pathlib import Path

import numpy as np
import yaml
from matplotlib.figure import Figure
from pyproj import Geod

from asar_repro.grid import GridGraph
from asar_repro.gridding import ParticleGrid, particle_step
from asar_repro.opendrift_adapter import Frames, planning_times, run_constant


ROOT = Path(__file__).resolve().parents[1]


def utc_label(t):
    return np.datetime_as_string(t, unit="ms") + "Z"


def interpolation_check(ds, raw):
    """Hold out odd native frames, predict them from neighboring even frames."""
    middle = np.arange(1, len(raw.time_utc) - 1, 2)
    estimate = Frames.from_dataset(ds.isel(time=slice(None, None, 2))).resample(raw.time_utc[middle])
    _, _, distance = Geod(ellps="WGS84").inv(estimate.lon, estimate.lat, raw.lon[middle], raw.lat[middle])
    good = np.asarray(distance)[np.isfinite(distance)]
    return dict(positions=int(good.size), total=int(distance.size),
                rms_m=float(np.sqrt(np.mean(good**2))) if good.size else None,
                p95_m=float(np.percentile(good, 95)) if good.size else None,
                max_m=float(good.max()) if good.size else None)


def audit(grid, frames, cells, q):
    """Replay a fixed horizontal back-and-forth transect through CSP, no search at t=0."""
    n = len(frames.ids)
    w = np.full(n, 1 / n)
    history, bins, visits, rows = [], [], [], []
    row, col = grid.graph.rows // 2, grid.graph.cols // 2
    direction, cumulative = 1, 0.0
    for t, current in enumerate(cells):
        vertex = None
        if t:
            if not 0 <= col + direction < grid.graph.cols:
                direction = -direction
            col += direction
            vertex = grid.graph.vertex(row, col)
        before = w.sum()
        removed = q * w[current == vertex].sum() if t else 0.
        w, mass = particle_step(grid, current, w, vertex, q)
        cumulative += removed
        remaining = w.sum()
        water = mass[:grid.graph.size].sum()
        special_mass = {key: mass[idx] for key, idx in grid.special.items()}
        checks = [before - removed - remaining, remaining - water - sum(special_mass.values()),
                  remaining + cumulative - 1]
        residual = max(abs(x) for x in checks)
        if residual > 1e-12 or remaining > before + 1e-12:
            raise AssertionError(f"mass conservation failed at t={t}")
        rows.append(dict(t=t, utc=utc_label(frames.time_utc[t]), visited=vertex,
                         n_ids=n, water=water, **special_mass, before=before, removed=removed,
                         M=remaining, Pd=cumulative, max_abs_residual=residual))
        visits.append(-1 if vertex is None else vertex)
        history.append(w)
        bins.append(mass)
    return np.array(history), np.array(bins), np.array(visits), rows


def plot_particles(grid, raw, frames, cfg, filename):
    fig = Figure(figsize=(12, 5.2))
    axes = fig.subplots(1, 3, sharex=True, sharey=True)
    fig.subplots_adjust(left=.085, right=.985, bottom=.16, top=.76, wspace=.08)
    half_x = grid.graph.cols * grid.width_m / 2
    half_y = grid.graph.rows * grid.width_m / 2
    for ax, (f, t, label) in zip(axes, [(raw, 0, "Incident"), (frames, 0, "CST"),
                                       (frames, -1, "End of search window")]):
        x, y = grid.projection.transform(f.lon[t], f.lat[t])
        ax.scatter(x, y, s=4, alpha=.44, color="#086985")
        ax.scatter([0], [0], s=34, marker="+", color="#c14616", label="CSP")
        ax.plot([-half_x, half_x, half_x, -half_x, -half_x],
                [-half_y, -half_y, half_y, half_y, -half_y], color="#929ca3", lw=.8)
        ax.set(title=f"{label}\n{utc_label(f.time_utc[t])[11:]}", xlabel="East of CSP (m)", aspect="equal")
        ax.grid(alpha=.2)
    axes[0].set_ylabel("North of CSP (m)")
    axes[-1].legend(loc="upper left")
    fig.suptitle(f"Synthetic constant forcing | {cfg['object_key']} | {cfg['particles']} particles"
                 f" | {cfg['incident_utc'][:10]} UTC")
    fig.savefig(filename, dpi=170)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/lake_ontario_constant.yaml")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
    opts = parser.parse_args()
    content = opts.config.read_bytes()
    cfg = yaml.safe_load(content)
    digest = hashlib.sha256(content).hexdigest()
    ds, obj = run_constant(cfg)
    raw = Frames.from_dataset(ds)
    target = planning_times(cfg["cst_utc"], cfg["budget"], cfg["step_s"])
    frames = raw.resample(target)
    grid = ParticleGrid(GridGraph(*cfg["grid_rows_cols"]), cfg["csp_lon_lat"], cfg["cell_width_m"])
    cells = grid.assign(frames)
    weights, mass, visits, ledger = audit(grid, frames, cells, cfg["audit_q"])
    archive = opts.output_dir / "particles"
    metrics = opts.output_dir / "metrics"
    figures = opts.output_dir / "figures"
    for path in [archive, metrics, figures]:
        path.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(archive / "stage5_leeway.npz", config_hash=digest, trajectory_id=frames.ids,
                        raw_time_utc=raw.time_utc, raw_lon=raw.lon, raw_lat=raw.lat,
                        raw_status=raw.status, raw_land_binary_mask=raw.land,
                        raw_cell_ids=grid.assign(raw.resample(raw.time_utc)),
                        time_utc=frames.time_utc, lon=frames.lon, lat=frames.lat, status=frames.status,
                        land_binary_mask=frames.land, cell_ids=cells, initial_weights=weights[0],
                        audit_weights=weights, audit_cell_mass=mass, audit_visited=visits)
    with (metrics / "stage5_mass.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ledger[0])
        writer.writeheader()
        writer.writerows(ledger)
    # Clip the same CST cloud to a single CSP cell to exercise domain loss
    # accounting with actual drift data, without changing the production grid.
    clipped = ParticleGrid(GridGraph(1, 1), cfg["csp_lon_lat"], cfg["cell_width_m"])
    small_cells = clipped.assign(frames)[0]
    _, small_mass = particle_step(clipped, small_cells, weights[0])
    np.testing.assert_allclose(small_mass.sum(), 1, atol=1e-12, rtol=0)
    report = dict(config=cfg, config_hash=digest, object=obj, opendrift_version=version("opendrift"),
                  native_dims=list(ds.lon.dims), archive_dims=["time", "trajectory_id"], status_flags=raw.flags,
                  source_frames=len(raw.time_utc), source_first=utc_label(raw.time_utc[0]),
                  source_last=utc_label(raw.time_utc[-1]), planning_frames=len(target),
                  search_start=utc_label(target[0]), search_end=utc_label(target[-1]),
                  special_cells=grid.special, grid_crs_wkt=grid.projection.target_crs.to_wkt(),
                  grid_index="AEQD centered on CSP; west/south inclusive, east/north exclusive; row 0 north",
                  resampling="UTC linear latitude and shortest-arc longitude within matching status and mask; "
                             "ambiguous intervals unknown; carry terminal status through trailing missing flags",
                  midpoint_holdout=interpolation_check(ds, raw),
                  max_distance_to_nearest_source_time_s=float(np.abs(target[:, None]-raw.time_utc)
                                                              .min(axis=1).max()/np.timedelta64(1, "s")),
                  mass_tolerance=1e-12, max_abs_residual=max(row["max_abs_residual"] for row in ledger),
                  single_cell_cst_check=dict(water=small_mass[0],
                                             **{k:small_mass[v] for k,v in clipped.special.items()}),
                  first=ledger[0], last=ledger[-1],
                  audit_path="east/west transect from CSP; audit_weights are path-specific; start other paths "
                             "from initial_weights")
    (metrics / "stage5_drift.json").write_text(json.dumps(report, indent=2, allow_nan=False),
                                              encoding="utf-8")
    plot_particles(grid, raw, frames, cfg, figures / "stage5_particles.png")
    print(obj, frames.lon.shape, report["search_end"], report["max_abs_residual"], report["last"])


if __name__ == "__main__":
    main()
