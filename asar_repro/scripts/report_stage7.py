"""Replay all stage 7 paths, export comparable metrics and plot frozen results."""

import argparse
import csv
import json
from pathlib import Path

import numpy as np
import yaml
from matplotlib.figure import Figure
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable

from asar_repro.grid import GridGraph
from asar_repro.gridding import ParticleGrid
from asar_repro.scenarios import config_digest, digest


ROOT = Path(__file__).resolve().parents[1]
COLORS = {"ASAR_paper": "#1769a2", "ParallelTrack": "#b04a10", "ACO_inspired": "#754f91"}


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def audit_runs(meta, runs, spec, grid, archive):
    """Independent direct ID-mask replay, including off-grid particles."""
    cells, p = archive["cell_ids"], archive["initial_weights"]
    methods = [row["method"] for row in runs]
    aco = spec["aco"]
    assert methods.count("ParallelTrack") == 1 and len(runs) == 1+len(spec["epsilon"])+aco["trials"]
    assert [r["epsilon"] for r in runs if r["method"] == "ASAR_paper"] == spec["epsilon"]
    assert [r["algorithm_seed"] for r in runs if r["method"] == "ACO_inspired"] == list(
        range(aco["first_seed"], aco["first_seed"] + aco["trials"]))
    expected_hash = config_digest({k:v for k,v in spec.items() if k != "scenarios"}
                                  | {"case": spec["scenarios"][meta["scenario"]]})
    start = grid.vertex(grid.rows // 2, grid.cols // 2)
    max_error = 0.
    for r in runs:
        assert r["archive_sha256"] == meta["archive_sha256"] and r["config_hash"] == expected_hash
        assert r["q"] == spec["q"] and r["start"] == start and r["T"] == meta["budget"]
        grid.validate_path(r["path"], start=start, budget=meta["budget"])
        w = p.copy()
        masses = [w.sum()]
        for t, vertex in enumerate(r["path"][1:], 1):
            w[cells[t] == vertex] *= 1-r["q"]
            masses.append(w.sum())
        err = max(np.max(np.abs(np.array(masses)-r["M_0_to_T"])),
                  abs(np.sum(masses[1:])-r["J"]), abs(1-masses[-1]-r["Pd_T"]))
        if err > 1e-10:
            raise ValueError("independent path replay failed")
        max_error = max(max_error, float(err))
    return max_error


def plot_paths(folder, m, rows, archive):
    graph = GridGraph(*m["grid_rows_cols"])
    width = m["drift_config"]["cell_width_m"] / 1000
    grid = ParticleGrid(graph, m["csp_lon_lat"], width*1000)
    t = 19
    ants = [r for r in rows if r["method"] == "ACO_inspired"]
    picks = [next(r for r in rows if r["method"] == "ASAR_paper"),
             next(r for r in rows if r["method"] == "ParallelTrack"),
             min(ants, key=lambda r: abs(r["J"] - m["aco_median_J"]))]
    ref = picks[0]
    labels = [f"ASAR_paper  ε={ref['epsilon']:.2f}", "ParallelTrack",
              f"ACO_inspired  seed {picks[2]['algorithm_seed']}"]
    fig = Figure(figsize=(14, 8), layout="constrained")
    layout = fig.add_gridspec(2, 4, height_ratios=[1.05, 1])
    top = [fig.add_subplot(layout[0,i]) for i in range(4)]
    routes, survival = fig.add_subplot(layout[1,:2]), fig.add_subplot(layout[1,2:])

    def km(lon, lat):
        return np.asarray(grid.projection.transform(lon, lat)) / 1000

    fw = archive["initial_weights"]
    cells = archive["cell_ids"]
    lon, lat = archive["lon"][t], archive["lat"][t]
    cloud = km(lon, lat)
    mappable = Normalize(0, max(float(np.bincount(cells[t], weights=fw,
                                minlength=graph.size)[:graph.size].max()), 1e-12))
    raw_end = archive["raw_time_utc"] <= archive["time_utc"][t]
    subset = np.linspace(0, len(fw)-1, min(30, len(fw)), dtype=int)
    tracks = km(archive["raw_lon"][raw_end][:,subset], archive["raw_lat"][raw_end][:,subset])
    top[0].plot(tracks[0], tracks[1], lw=.5, alpha=.5, color="#78a394")
    top[0].scatter(*cloud, s=3, color="#17654b", alpha=.45)
    top[0].scatter(*km(*m["lkp_lon_lat"]), marker="^", color="#283747", s=32, label="LKP")
    top[0].set_title("Leeway drift to step 19")
    full_xy = []
    extent = np.array([-graph.cols, graph.cols, -graph.rows, graph.rows]) * width / 2
    for ax, r, label in zip(top[1:], picks, labels):
        w = fw.copy()
        for i, v in enumerate(r["path"][1:t+1], 1):
            w[cells[i] == v] *= 1-r["q"]
        mass = np.bincount(cells[t], weights=w, minlength=graph.size)[:graph.size]
        ax.imshow(mass.reshape(graph.rows, graph.cols), extent=extent, origin="upper",
                  cmap="YlGn", norm=mappable, interpolation="nearest")
        row, col = np.divmod(r["path"], graph.cols)
        x, y = (col - graph.cols//2)*width, (graph.rows//2-row)*width
        full_xy.append(np.array([x,y]))
        color = COLORS[r["method"]]
        ax.plot(x[:t+1], y[:t+1], color=color, lw=1.9)
        ax.scatter(x[t], y[t], color=color, s=21)
        ax.set_title(label + f"\nM₁₉ = {r['M_0_to_T'][t]:.3f}")
        routes.plot(x, y, lw=1.6, alpha=.83, label=r["method"], color=color)
        routes.scatter(x[-1], y[-1], color=color, s=20)
        survival.plot(r["M_0_to_T"], label=f"{r['method']}  J={r['J']:.2f}", color=color)
    search_cloud = km(archive["lon"], archive["lat"]).reshape(2, -1)
    bounds = np.hstack([search_cloud, tracks.reshape(2,-1), *full_xy])
    lo, hi = bounds.min(axis=1), bounds.max(axis=1)
    pad = max(width, .07 * (hi-lo).max())
    for ax in [*top, routes]:
        ax.scatter(0, 0, marker="+", color="#202020", s=55, linewidths=1.3)
        ax.set(xlim=(lo[0]-pad, hi[0]+pad), ylim=(lo[1]-pad, hi[1]+pad), aspect="equal",
               xlabel="East of CSP (km)")
    top[0].legend(fontsize=8, loc="best")
    top[0].set_ylabel("North of CSP (km)")
    fig.colorbar(ScalarMappable(norm=mappable, cmap="YlGn"), ax=top[1:], shrink=.72,
                 label="Undetected mass / cell")
    routes.set(title=f"Complete {m['budget']}-move routes  (+ CSP, dot = end)", ylabel="North of CSP (km)")
    routes.legend(fontsize=8)
    survival.set(title="Undetected mass along each route", xlabel="Moves after CST", ylabel="M(t)",
                 xlim=(0,m["budget"]), ylim=(0,1.03))
    survival.grid(alpha=.22)
    survival.legend(fontsize=9)
    fig.suptitle(f"{m['name']}  |  constant wind and current  |  {len(fw)} particles\n"
                 f"Step 19 at {m['time_utc'][t]}   ·   ACO trial nearest median J   ·   "
                 f"A^SAR {ref['status']}", fontsize=13)
    fig.savefig(folder / "paths.png", dpi=150)

    # Figure 2-style sequences use the same route, frame clock, crop and color
    # limits across all four panels so a change in shade has one interpretation.
    snapshots = (1, 5, 15, 30)
    w = fw.copy()
    fields = []
    for step, v in enumerate(ref["path"][1:max(snapshots)+1], 1):
        w[cells[step] == v] *= 1-ref["q"]
        if step in snapshots:
            field = np.bincount(cells[step], weights=w, minlength=graph.size)[:graph.size]
            fields.append(field.reshape(graph.rows, graph.cols))
    series = Figure(figsize=(13, 4.2), layout="constrained")
    panels = series.subplots(1, len(snapshots))
    norm = Normalize(0, max(max(f.max() for f in fields), 1e-12))
    x, y = full_xy[0]
    for panel, step, field in zip(panels, snapshots, fields, strict=True):
        im = panel.imshow(field, origin="upper", extent=extent, cmap="YlGn",
                          interpolation="nearest", norm=norm)
        panel.plot(x[:step+1], y[:step+1], color=COLORS["ASAR_paper"], lw=1.8)
        panel.scatter(x[step], y[step], s=24, color=COLORS["ASAR_paper"])
        panel.scatter(0, 0, marker="+", color="#202020", s=48)
        panel.set(xlim=(lo[0]-pad, hi[0]+pad), ylim=(lo[1]-pad, hi[1]+pad),
                  title=f"Step {step}   M={ref['M_0_to_T'][step]:.3f}", xlabel="East of CSP (km)")
    panels[0].set_ylabel("North of CSP (km)")
    series.colorbar(im, ax=panels.tolist(), shrink=.75, label="Undetected mass / cell")
    series.suptitle(f"{m['name']}   |   synthetic constant forcing   |   ASAR_paper  ε={ref['epsilon']:.2f}")
    series.savefig(folder / "belief_sequence.png", dpi=150)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/stage7")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/stage7_scenarios.yaml")
    opts = parser.parse_args()
    spec = yaml.safe_load(opts.config.read_bytes())
    metrics, steps, deviations = [], [], []
    fig = Figure(figsize=(11, 7), layout="constrained")
    axes = fig.subplots(2, 2).flat
    for ax, name in zip(axes, spec["scenarios"], strict=True):
        folder = opts.output_dir / name
        report = json.loads((folder / "results.json").read_text(encoding="utf-8"))
        m, rows = report["metadata"], report["runs"]
        archive_path = ROOT / m["archive"]
        if digest(archive_path) != m["archive_sha256"]:
            raise ValueError(f"{name}: particle archive has changed")
        with np.load(archive_path, allow_pickle=False) as archive:
            error = audit_runs(m, rows, spec, GridGraph(*m["grid_rows_cols"]), archive)
            plot_paths(folder, m, rows, archive)
        for r in rows:
            metrics.append({k:v for k,v in r.items() if k not in ("path","M_0_to_T")})
            key = {k:r[k] for k in ("scenario","method","epsilon","algorithm_seed")}
            for t, (v, mass) in enumerate(zip(r["path"], r["M_0_to_T"], strict=True)):
                steps.append(dict(key, t=t, utc=m["time_utc"][t], vertex=v, M_t=mass, Pd_t=1-mass))
        pts = [r for r in rows if r["method"] == "ASAR_paper"]
        ref = next(r["J"] for r in rows if r["method"] == "ParallelTrack")
        ax.axhline(1, color=COLORS["ParallelTrack"], lw=1.3, label="ParallelTrack")
        ci = np.array(m["aco_median_J_ci99"])/ref
        ax.axhspan(*ci, color=COLORS["ACO_inspired"], alpha=.17)
        ax.axhline(m["aco_median_J"]/ref, color=COLORS["ACO_inspired"], ls="--", label="ACO median (99% CI)")
        for i,r in enumerate(pts):
            ax.plot(i,r["J_over_PT"],"o",mec=COLORS["ASAR_paper"],
                    mfc=COLORS["ASAR_paper"] if r["status"]=="completed" else "white")
        ax.set(title=m["name"], xticks=range(len(pts)), xticklabels=[f"{r['epsilon']:g}" for r in pts],
               xlabel="A^SAR ε", ylabel="J / J(ParallelTrack)")
        ax.grid(axis="y", alpha=.2)
        deviations.append(dict(scenario=name, alias=m.get("alias",""), paper_source=m["paper_source"],
            paper_url=m["paper_url"], paper_wind=m["wind"], wind_catalog=m["catalogs"][m["wind"]],
            paper_current=m["current"], current_catalog=m["catalogs"][m["current"]],
            incident_utc=m["incident_utc"], lkp_lon_lat=json.dumps(m["lkp_lon_lat"]),
            cst_utc=m["cst_utc"], csp_lon_lat=json.dumps(m["csp_lon_lat"]), search_end_utc=m["search_end_utc"],
            paper_object=m["object"], local_object=m["object_resolved"]["key"],
            local_object_number=m["object_resolved"]["number"], sweep_width_nm=m["sweep_width_nm"],
            cell_width_m=m["drift_config"]["cell_width_m"], T=m["budget"], step_s=m["drift_config"]["step_s"],
            predrift_h=m["predrift_hours"], cst_median_distance_to_csp_m=m["cst_particle_distance_m"]["median"],
            max_prior_special_mass=float(np.max(np.sum(m["prior_special_mass_by_step"],axis=1))),
            grid_rows_cols=json.dumps(m["grid_rows_cols"]), actual_forcing=m["forcing_kind"],
            local_reader_values=json.dumps(m["drift_config"]["forcing"]), opendrift=m["opendrift_version"],
            availability=m["data_availability"], local_access="No local historical pair; target endpoint probes WinError 10013 (2026-11-23 local).",
            shoreline_ice="All-water mask; no ice dynamics or shoreline interaction.",
            paper_inputs="Author seeds, scatter, grid bounds, archived input files and manual PT route unavailable locally.",
            local_baselines="Dynamic percentile-envelope ParallelTrack; ACO_inspired local ant system.",
            bound="Dynamic paper_greedy; no certified optimum. Reference is ParallelTrack.",
            asar_completed=sum(r["status"]=="completed" for r in pts),
            asar_budget_exceeded=sum(r["status"]=="budget_exceeded" for r in pts),
            independent_replay_max_abs_error=error, aco_trials=m["aco_settings"]["trials"],
            aco_median_J=m["aco_median_J"], aco_median_J_ci99_low=m["aco_median_J_ci99"][0],
            aco_median_J_ci99_high=m["aco_median_J_ci99"][1]))
    fig.axes[0].legend(fontsize=8)
    fig.suptitle("Constant forcing  |  Cost relative to each mission’s ParallelTrack\n"
                 "A^SAR: filled = completed, open = budget stop with feasible incumbent", fontsize=13)
    fig.savefig(opts.output_dir / "relative_cost.png", dpi=150)
    for name, data in [("metrics",metrics),("step_metrics",steps),("deviations",deviations)]:
        write_csv(opts.output_dir / (name+".csv"), data)
    print(f"Audited {len(metrics)} routes, {len(steps)} time samples. Max absolute replay error "
          f"{max(d['independent_replay_max_abs_error'] for d in deviations):.3g}")


if __name__ == "__main__":
    main()
