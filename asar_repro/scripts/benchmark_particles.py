"""Stage 6: isolated search processes on one frozen particle archive."""

import argparse
import cProfile
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import pstats
import subprocess
import sys
from time import perf_counter

import numpy as np
import yaml

from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.search import search_asar


ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / "configs/stage6_particle_search.yaml"


def load_input(spec):
    archive = ROOT / spec["archive"]
    raw_config = (ROOT / spec["drift_config"]).read_bytes()
    cfg = yaml.safe_load(raw_config)
    from asar_repro.opendrift_adapter import planning_times
    times = planning_times(cfg["cst_utc"], cfg["budget"], cfg["step_s"])
    grid = GridGraph(*cfg["grid_rows_cols"])
    start = grid.vertex(grid.rows // 2, grid.cols // 2)
    with np.load(archive, allow_pickle=False) as data:
        digest = hashlib.sha256(raw_config).hexdigest()
        if (str(data["config_hash"]) != digest or not np.array_equal(times, data["time_utc"])
                or data["cell_ids"].shape != (len(times), cfg["particles"])):
            raise ValueError("stage 5 archive/config identity, UTC clock or particle count mismatch")
        motion = ParticleMotion(data["cell_ids"], grid.size, data["trajectory_id"])
        p = data["initial_weights"]
        if spec["initial_path"] != "stage5_audit_transect" or data["audit_visited"][0] != -1:
            raise ValueError("expected the stage 5 audit transect")
        warm = (start, *map(int, data["audit_visited"][1:]))
    args = dict(start=start, budget=cfg["budget"], p=p, q=cfg["audit_q"], motion=motion)
    return grid, args, warm, cfg, times, digest


def peak_process_mib():
    if sys.platform == "win32":
        import psutil
        return psutil.Process().memory_info().peak_wset / 2**20
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (2**20 if sys.platform == "darwin" else 1024)


def run_one(spec, eps, profile_path=None):
    grid, args, warm, cfg, times, digest = load_input(spec)
    profile = cProfile.Profile() if profile_path else None
    if profile:
        profile.enable()
    started = perf_counter()
    result = search_asar(grid, **args, heuristic=spec["heuristic"], epsilon=eps,
                         initial_path=warm, **spec["limits"])
    elapsed = perf_counter() - started
    if profile:
        profile.disable()
    peak = peak_process_mib()
    if profile:
        with profile_path.open("w", encoding="utf-8") as f:
            pstats.Stats(profile, stream=f).strip_dirs().sort_stats("cumulative").print_stats(30)
    row = dict(**asdict(result), Pd=None, elapsed_s=elapsed, peak_process_MiB=peak,
               timed_out=result.stop_reason == "max_seconds", seed=cfg["seed"], config_hash=digest,
               survival=[], replay_error=None)
    if result.path is not None:
        grid.validate_path(result.path, start=args["start"], budget=args["budget"])
        # Independent of the search index: match original ID columns by boolean mask.
        w = args["p"].copy()
        curve = [float(w.sum())]
        for t, v in enumerate(result.path[1:], 1):
            w[args["motion"].cell_ids[t] == v] *= 1 - args["q"]
            curve.append(float(w.sum()))
        err = abs(result.J - sum(curve[1:]))
        if err > 1e-10 or np.any(np.diff(curve) > 1e-12):
            raise AssertionError("particle survival or path cost disagrees with independent replay")
        row.update(Pd=1-curve[-1], survival=curve, replay_error=err)
    if "opendrift" in sys.modules:
        raise RuntimeError("planning unexpectedly imported OpenDrift")
    return row


def plot_runs(spec, runs, destination):
    from matplotlib.figure import Figure

    grid, args, _, cfg, _, _ = load_input(spec)
    prior = args["motion"].cell_mass(args["p"], 0)[:grid.size].reshape(grid.rows, grid.cols)
    fig = Figure(figsize=(12, 4.4))
    axes = fig.subplots(1, 3, gridspec_kw={"width_ratios": [1, 1, 1.5]})
    fig.subplots_adjust(left=.06, right=.98, top=.77, bottom=.28, wspace=.35)
    for ax, r in zip(axes[:2], (runs[0], runs[-1])):
        im = ax.imshow(prior, cmap="Blues", vmin=0, vmax=prior.max())
        if r["path"] is not None:
            y, x = np.array([grid.coordinates(v) for v in r["path"]]).T
            ax.plot(x, y, color="#bc461e", lw=1.4)
            ax.plot(x[0], y[0], "o", mfc="white", mec="black", ms=6)
            ax.plot(x[-1], y[-1], "D", color="#bc461e", ms=4)
        ax.set_title(f"ε={r['epsilon']:g}  |  {r['stop_reason'] or r['status']}", fontsize=10)
        ax.set_xlabel("Grid column")
    axes[0].set_ylabel("Grid row")
    cb = fig.colorbar(im, cax=fig.add_axes([.09,.13,.33,.023]), orientation="horizontal")
    cb.set_label("Particle mass at CST")
    for r in runs:
        if r["survival"]:
            axes[2].plot(r["survival"], label=f"{r['epsilon']:g}", lw=1.1,
                         ls="--" if r["status"] == "budget_exceeded" else "-")
    axes[2].set(xlabel="Search step", ylabel="Undetected mass", ylim=(0, 1.05))
    axes[2].legend(title="ε", ncols=2, fontsize=8)
    fig.suptitle(f"{cfg['object_key']} in synthetic constant forcing | {cfg['particles']} particles"
                 f" | T={args['budget']} | q={args['q']}")
    fig.savefig(destination, dpi=150)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT)
    parser.add_argument("--worker-epsilon", type=float, help=argparse.SUPPRESS)
    parser.add_argument("--profile-to", type=Path, help=argparse.SUPPRESS)
    opts = parser.parse_args()
    spec = yaml.safe_load(opts.config.read_text(encoding="utf-8"))
    if opts.worker_epsilon is not None:
        print(json.dumps(run_one(spec, opts.worker_epsilon, opts.profile_to), allow_nan=False))
        return
    outputs = ROOT / "outputs"
    for subdir in ("logs", "metrics", "figures"):
        (outputs / subdir).mkdir(parents=True, exist_ok=True)
    base = [sys.executable, __file__, "--config", str(opts.config.resolve()), "--worker-epsilon"]
    runs = []
    for eps in spec["epsilon_grid"]:
        row = json.loads(subprocess.check_output([*base, str(eps)], text=True))
        runs.append(row)
        print(eps, row["status"], row["stop_reason"], row["J"], row["expanded"], flush=True)
    prof = outputs / "logs/stage6_profile.txt"
    profile_run = json.loads(subprocess.check_output([*base, str(spec["epsilon_grid"][0]),
                                                       "--profile-to", str(prof)], text=True))
    report = dict(config=spec, archive_sha256=hashlib.sha256((ROOT/spec["archive"]).read_bytes()).hexdigest(),
                  memory="isolated process lifetime peak resident memory through search return, MiB",
                  timing="unprofiled search including scoring the common feasible starting path",
                  profile_run=profile_run, runs=runs)
    metrics = outputs / "metrics"
    (metrics / "stage6_particles.json").write_text(json.dumps(report, indent=2, allow_nan=False),
                                                  encoding="utf-8")
    keys = [k for k in runs[0] if k not in ("path", "survival")]
    with (metrics / "stage6_epsilon.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(runs)
    plot_runs(spec, runs, outputs / "figures/stage6_particle_search.png")


if __name__ == "__main__":
    main()
