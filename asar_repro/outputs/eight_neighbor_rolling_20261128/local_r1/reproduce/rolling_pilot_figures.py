"""Plot the completed R30 pilot from verified frozen output, with no fresh solve."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.colors import PowerNorm
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter
import numpy as np


DEFAULT_OUT = Path("outputs/eight_neighbor_rolling_20261128/local_r1")
C0, C1 = "#236190", "#AA462A"
INK, GRID = "#1B2838", "#DDE5ED"
ALPHA = 0.84
METHOD_COLORS = {"C0": C0, "C1": C1}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_complete(out):
    summary = read(out / "summary.json")
    protocol = read(out / "protocol.json")
    if summary["status"]["status"] != "complete" or summary["status"]["valid"] != 24:
        raise ValueError("A complete 24-task pilot is required for the figures.")
    if digest(out / "protocol.json") != summary["protocol_sha256"]:
        raise ValueError("Frozen plotting protocol fingerprint mismatch.")
    for name, expected in summary["derived_file_sha256"].items():
        if digest(out / name) != expected:
            raise ValueError(f"Published table fingerprint mismatch: {name}")
    config = protocol["config"]
    groups, selected = {}, {}
    comparisons = {row["instance"]: row for row in summary["decision"]["comparisons"]}
    for run_id, expected in summary["raw_evidence"].items():
        path = out / "runs" / run_id / "result.json"
        if digest(path) != expected:
            raise ValueError(f"Raw result fingerprint mismatch: {run_id}")
        row = read(path)
        key = (row["task"]["instance"], row["task"]["method"])
        if row["result"]["status"] != "valid":
            raise ValueError(f"Invalid route record: {run_id}")
        groups.setdefault(key, []).append(dict(row, run_id=run_id))
    for instance in config["instances"]:
        item = comparisons[instance]
        for method in config["methods"]:
            group = groups[instance, method]
            if set(row["task"]["repetition"] for row in group) != {0, 1, 2} or len(group) != 3:
                raise ValueError(f"Missing or repeated timing repetitions: {instance}/{method}")
            rep = sorted(group, key=lambda row: (row["result"]["J"], row["task"]["repetition"]))[1]
            if rep["run_id"] != item[f"{method}_run_id"]:
                raise ValueError(f"Figure and registered J-median representative disagree: {instance}/{method}")
            selected[instance, method] = rep
    if len(groups) != 8 or len(summary["raw_evidence"]) != 24:
        raise ValueError("Unexpected run identities in the formal matrix.")
    return protocol, comparisons, groups, selected


def instance_label(instance):
    region, _, block, seed = instance.split("_")
    name = {"lake": "Lake Ontario", "hudson": "Hudson Bay"}[region]
    return f"{name} · {block.upper()} · {seed[1:]}"


def rep_caption(selected, instance):
    return "  |  ".join(
        f'{method} {selected[instance, method]["run_id"]} (r{selected[instance, method]["task"]["repetition"]})'
        for method in ("C0", "C1")
    )


def method_handles():
    return [
        Line2D([0], [0], color=C0, linewidth=2, linestyle="--", label="C0  ·  one-shot"),
        Line2D([0], [0], color=C1, linewidth=2, label="C1  ·  rolling"),
    ]


def gain_figure(instances, comparisons, groups):
    fig, ax = plt.subplots(figsize=(11.6, 6.3), layout="constrained")
    settings = ((0, -0.14, "o"), (1, 0, "s"), (2, 0.14, "^"))
    for x, case in enumerate(instances):
        reps = [{row["task"]["repetition"]: row["result"]["J"] for row in groups[case, method]}
                for method in ("C0", "C1")]
        for repeat, shift, marker in settings:
            gain = 100 * (reps[0][repeat] - reps[1][repeat]) / reps[0][repeat]
            ax.scatter(x + shift, gain, s=56, marker=marker, color=C0, alpha=0.62, zorder=3)
        gain = 100 * comparisons[case]["relative_J_gain"]
        ax.plot([x - 0.29, x + 0.29], [gain, gain], solid_capstyle="round",
                linewidth=3.0, color=C1, zorder=4)
        ax.annotate(f"{gain:+.2f}%", (x + 0.29, gain), xytext=(4, 3), textcoords="offset points",
                    color=C1, fontsize=9, weight="bold")
    ax.axhline(0.0, color=INK, linewidth=1)
    ax.axhline(0.5, color="#4D6D5D", linestyle=":", linewidth=1.1)
    ax.set_xticks(range(len(instances)), [instance_label(x).replace(" · ", "\n", 1) for x in instances])
    ax.set_xlim(-0.57, len(instances)-0.30)
    ax.margins(y=0.21)
    ax.set_ylabel("Relative reduction in J (%)")
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    handles = [
        Line2D([0], [0], color=C1, linewidth=3, label="Registered gain from method medians"),
        Line2D([0], [0], color="#4D6D5D", linestyle=":", label="0.5% engineering threshold"),
        *[Line2D([0], [0], color=C0, marker=marker, linestyle="none", alpha=0.70,
                 label=f"Timing repeat {r}") for r, _, marker in settings],
    ]
    ax.legend(handles=handles, loc="best", ncol=2)
    fig.suptitle("Route quality under the shared 30-second computation cap", weight="bold")
    return fig


def pd_figure(instances, groups, selected):
    fig, axes = plt.subplots(2, 2, figsize=(13.6, 8.3), layout="constrained")
    styles = {"C0": "--", "C1": "-"}
    for ax, case in zip(axes.flat, instances, strict=True):
        end_times = []
        for method, color in METHOD_COLORS.items():
            rep = selected[case, method]
            for row in sorted(groups[case, method], key=lambda row: row["run_id"] == rep["run_id"]):
                replay = row["result"]["physical_replay"]
                t = [0, *replay["observation_times_s"]]
                pd = 100 * (1-np.asarray(replay["survival"]))
                is_rep = row["run_id"] == rep["run_id"]
                ax.step(t, pd, where="post", color=color, linestyle=styles[method],
                        alpha=ALPHA if is_rep else 0.15, linewidth=2.15 if is_rep else 1.1,
                        zorder=3 if is_rep else 2)
                if is_rep:
                    ax.scatter(t[-1], pd[-1], s=27, color=color, zorder=5)
                    end_times.append(t[-1])
            terminal = rep["result"]["pd_final"]
            ax.text(0.98, 0.16 if method == "C0" else 0.06, f"{method} final {100*terminal:.2f}%",
                    ha="right", transform=ax.transAxes, color=color, fontsize=8)
        if end_times[0] != end_times[1]:
            raise ValueError(f"Conflicting observation horizons: {case}")
        ax.set_xlim(0, end_times[0] * 1.023)
        ax.set_ylim(bottom=0)
        ax.set_xlabel("Physical time since CST (s)")
        ax.set_ylabel("Cumulative detection probability (%)")
        ax.set_title(instance_label(case) + "\n" + rep_caption(selected, case), fontsize=9, loc="left")
        ax.grid(color=GRID, linewidth=0.6)
    # Preserve grid space for the shared legend with a dedicated outside row.
    fig.legend(handles=method_handles(), loc="outside lower center", ncol=2)
    fig.suptitle("Detection on the common observation clock · faint lines show the other timing repeats",
                 weight="bold", fontsize=13)
    return fig


def route_to_time(replay, elapsed):
    segments = replay["segments"]
    points = [segments[0]["start_xy"]]
    for segment in segments:
        start, end = segment["start_time_s"], segment["end_time_s"]
        if elapsed <= start:
            break
        if elapsed >= end:
            points.append(segment["actual_end_xy"])
            continue
        ratio = (elapsed - start)/(end - start)
        beginning, ending = np.asarray(segment["start_xy"]), np.asarray(segment["actual_end_xy"])
        points.append(beginning + ratio*(ending-beginning))
        break
    return np.asarray(points, dtype=float)/1000


def prior_frames(problem, ticks):
    width = problem.cell_width_m/1000
    x = (np.arange(problem.cols+1) - problem.cols/2) * width
    y = (np.arange(problem.rows+1) - problem.rows/2) * width
    frames, extents = [], []
    for tick in ticks:
        mask = problem.searchable[tick]
        positions = problem.positions_xy[tick, mask]/1000
        weights = problem.initial_weights[mask]
        hist = np.histogram2d(positions[:, 1], positions[:, 0], bins=(y, x), weights=weights)[0]
        frames.append(hist)
        searchable_mass = float(np.sum(weights))
        if not np.isclose(hist.sum(), searchable_mass, rtol=0, atol=1e-10):
            raise ValueError("Prediction histogram omitted searchable particle mass.")
        row, col = np.where(hist > 0)
        if row.size:
            extents.append(np.asarray([[x[col.min()], y[row.min()]], [x[col.max()+1], y[row.max()+1]]]))
    return x, y, frames, extents


def read_map_problem(project, protocol, instance):
    from asar_repro.h2_inputs import load_h2_input

    cfg, ref = protocol["config"], protocol["references"]
    case = ref["instances"][instance]
    path = project/cfg["source_root"]/"inputs"/instance
    problem, _, _, info = load_h2_input(project, case, path, cfg["objective"]["footprint"])
    if info["particle_sha256"] != ref["archive_hashes"][instance]["particle_sha256"]:
        raise ValueError(f"Prediction archive fingerprint mismatch: {instance}")
    return problem


def map_figure(project, protocol, instances, selected):
    fig = plt.figure(figsize=(14.2, 10.2), layout="constrained")
    grid = fig.add_gridspec(2, 4, width_ratios=(1, 1, 1, 0.043))
    for row, instance in enumerate(instances):
        problem = read_map_problem(project, protocol, instance)
        ticks = [0, len(problem.times_s)//2, len(problem.times_s)-1]
        x, y, hist, occupied = prior_frames(problem, ticks)
        replays = {m: selected[instance, m]["result"]["physical_replay"] for m in METHOD_COLORS}
        anchors = [p for p in selected[instance, "C1"]["result"]["raw"]["phases"]
                   if p["stage_index"] > 0 and p["anchor_time_s"] is not None]
        occupied.extend(route_to_time(v, float(problem.times_s[-1])) for v in replays.values())
        points = np.concatenate(occupied)
        pad = 1.5 * problem.cell_width_m/1000
        lower = np.maximum(points.min(axis=0)-pad, [x[0], y[0]])
        upper = np.minimum(points.max(axis=0)+pad, [x[-1], y[-1]])
        norm = PowerNorm(gamma=0.55, vmin=0, vmax=max(max(h.max() for h in hist), 1e-5))
        for col, (tick, masses) in enumerate(zip(ticks, hist, strict=True)):
            ax = fig.add_subplot(grid[row, col])
            display = np.ma.masked_where(masses == 0, masses)
            img = ax.imshow(display, extent=(x[0], x[-1], y[0], y[-1]),
                            cmap="Blues", norm=norm, interpolation="nearest", origin="lower")
            elapsed = float(problem.times_s[tick])
            for method, color in METHOD_COLORS.items():
                route = route_to_time(replays[method], elapsed)
                ax.plot(*route.T, color=color, linewidth=1.8, alpha=ALPHA,
                        linestyle="--" if method == "C0" else "-", zorder=3)
                if len(route) > 1:
                    ax.scatter(*route[-1], color=color, marker=".", s=29, zorder=4)
            start = route_to_time(replays["C0"], 0)[0]
            ax.scatter(*start, color=INK, marker="^", s=38, zorder=5)
            for phase in anchors:
                time = phase["anchor_time_s"]
                if time <= elapsed:
                    point = route_to_time(replays["C1"], time)[-1]
                    ax.scatter(*point, edgecolors=C1, facecolors=C1 if phase["accepted"] else "white",
                               marker="D", s=32, zorder=5)
            ax.set(xlim=(lower[0], upper[0]), ylim=(lower[1], upper[1]), aspect="equal",
                   xlabel="East from CSP (km)", ylabel="North from CSP (km)")
            ax.set_title(f"{instance_label(instance)}\n"
                         f"t = {elapsed:.2f} s · in-grid prior {100*masses.sum():.1f}%",
                         loc="left", fontsize=9)
            if col == 1:
                ax.text(0.5, -0.24, rep_caption(selected, instance), transform=ax.transAxes,
                        ha="center", fontsize=7.3, color=INK)
        cb = fig.colorbar(img, cax=fig.add_subplot(grid[row, 3]))
        cb.ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{100*value:.1f}%"))
        cb.set_label("Prior probability per cell", fontsize=8)
    handles = method_handles() + [
        Line2D([0], [0], marker="^", color=INK, linestyle="none", label="CST position"),
        Line2D([0], [0], marker="D", color=C1, linestyle="none", label="C1 accepted anchor"),
        Line2D([0], [0], marker="D", markeredgecolor=C1, markerfacecolor="white", linestyle="none",
               label="C1 anchor retained on prior route"),
    ]
    fig.legend(handles=handles, loc="outside lower center", ncol=3)
    fig.suptitle("Frozen predicted particle mass and virtually executed route prefixes", weight="bold")
    return fig


def timeline_figure(instances, selected):
    fig, axes = plt.subplots(4, 2, figsize=(14, 12.6), layout="constrained")
    for (left, right), case in zip(axes, instances, strict=True):
        run = selected[case, "C1"]
        replay = run["result"]["physical_replay"]
        raw = run["result"]["raw"]
        phases = raw["phases"]
        stages = [p["stage_index"] for p in phases]
        for phase in phases:
            stage = phase["stage_index"]
            spend = phase["actual_compute_s"]
            color = C1 if phase["accepted"] else "#6B7C90"
            origin = phase["stage_start_compute_s"]
            right.barh(stage, phase["allocated_seconds"], left=origin, height=0.62,
                       color="#E5DBD5", linewidth=0)
            right.barh(stage, spend, left=origin, height=0.34, color=color, linewidth=0)
            right.text(origin + spend + 0.19, stage, f"{spend:.2f}s", va="center", color=INK, fontsize=8)
            if stage == 0:
                left.text(0.02, stage, f"Before CST · {'accepted' if phase['accepted'] else 'no replacement'}",
                          transform=left.get_yaxis_transform(), color=color, va="center", fontsize=8)
                continue
            request = phase["request_time_s"]
            if request is None:
                reason = phase["reason"].replace("_", " ")
                left.text(0.02, stage, reason, transform=left.get_yaxis_transform(),
                          color=color, va="center", fontsize=8)
                continue
            ready, execution, anchor = (phase[k] for k in
                                        ("ready_time_s", "execution_ready_time_s", "anchor_time_s"))
            left.scatter(request, stage+0.17, marker="|", s=79, color=C0, zorder=4)
            if ready is not None and phase["candidate_J"] is not None:
                left.plot([request, ready], [stage, stage], color=GRID)
                left.scatter(ready, stage, marker="o", s=21, color=C0, zorder=4)
            if execution is not None:
                left.scatter(execution, stage-0.17, marker="v", s=22, color=INK, zorder=4)
            if anchor is not None:
                left.scatter(anchor, stage, marker="D", s=29, edgecolors=color,
                             facecolors=color if phase["accepted"] else "white", zorder=5)
        left.set_xlim(0, replay["horizon_s"]*1.02)
        right.axvline(raw["total_seconds"], linestyle=":", color=INK, linewidth=1)
        right.set_xlim(0, max(raw["total_seconds"], raw["active_compute_s"])+2.0)
        for ax in (left, right):
            ax.set_yticks(stages, ["pre-CST" if i == 0 else f"A{i}" for i in stages])
            ax.set_ylim(max(stages)+0.58, -0.58)
            ax.grid(axis="x", color=GRID, linewidth=0.6)
        left.set_title(f"{instance_label(case)} · {run['run_id']} (r{run['task']['repetition']})", fontsize=9, loc="left")
        right.set_title(f"Actual total {raw['active_compute_s']:.2f} s", fontsize=9, loc="left")
        left.set_xlabel("Physical time since CST (s)")
        right.set_xlabel("Cumulative charged computation (s)")
    fig.legend(handles=[
        Line2D([0], [0], marker="|", color=C0, linestyle="none", label="Request"),
        Line2D([0], [0], marker="o", color=C0, linestyle="none", label="Candidate ready"),
        Line2D([0], [0], marker="v", color=INK, linestyle="none", label="Execution ready incl. accounting"),
        Line2D([0], [0], marker="D", markeredgecolor=C1, markerfacecolor=C1, linestyle="none",
               label="Accepted anchor"),
        Line2D([0], [0], marker="D", markeredgecolor="#6B7C90", markerfacecolor="white", linestyle="none",
               label="Anchor without accepted replacement"),
        Patch(facecolor="#E5DBD5", label="Allocated slot"),
        Patch(facecolor="#6B7C90", label="Charged without replacement"),
        Patch(facecolor=C1, label="Charged with replacement"),
    ], ncol=3, loc="outside lower center")
    fig.suptitle("Rolling schedule · physical execution and computation accounting", weight="bold")
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    project = args.project.resolve()
    out = (project/args.out).resolve()
    sys.path.insert(0, str(project/"src"))
    protocol, comparisons, groups, selected = read_complete(out)
    cases = protocol["config"]["instances"]
    fixed = {}
    for case in cases:
        fixed.setdefault(comparisons[case]["base_scene"], case)
    map_cases = list(fixed.values())
    if len(map_cases) != 2:
        raise ValueError("Expected a fixed first illustrative case from each of two regions.")
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
        "axes.spines.right": False, "axes.edgecolor": "#708095", "axes.labelcolor": INK,
        "text.color": INK, "xtick.color": INK, "ytick.color": INK,
        "legend.frameon": False, "figure.facecolor": "white",
    })
    target = out/"figures"
    target.mkdir(exist_ok=False)
    constructors = (
        ("01_relative_j.png", lambda: gain_figure(cases, comparisons, groups)),
        ("02_cumulative_detection.png", lambda: pd_figure(cases, groups, selected)),
        ("03_predicted_mass_routes.png", lambda: map_figure(project, protocol, map_cases, selected)),
        ("04_rolling_timeline.png", lambda: timeline_figure(cases, selected)),
    )
    files = {}
    for name, construct in constructors:
        figure = construct()
        path = target/name
        figure.savefig(path, dpi=200, facecolor="white")
        plt.close(figure)
        files[name] = digest(path)
    with (target/"manifest.json").open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(dict(summary_sha256=digest(out/"summary.json"),
                       generator_sha256=digest(Path(__file__).resolve()),
                       matplotlib_version=matplotlib.__version__,
                       representative_rule="median J, then frozen repetition order",
                       first_in_each_region=map_cases,
                       representative_runs={case: {m: selected[case, m]["run_id"] for m in METHOD_COLORS} for case in cases},
                       png_sha256=files), handle, indent=2)
        handle.write("\n")
    print(f"Wrote {len(files)} verified PNGs and plotting manifest to {target}.")


if __name__ == "__main__":
    main()

