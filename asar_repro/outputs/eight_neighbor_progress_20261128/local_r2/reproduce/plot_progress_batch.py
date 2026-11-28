"""Plot the complete three-arm P30 archive without rerunning any solver."""

from __future__ import annotations

import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
from statistics import median

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


CASES = {
    "lake_h2_d1_s3101": "Lake 3101",
    "lake_h2_d2_s3201": "Lake 3201",
    "hudson_h2_d1_s4101": "Hudson 4101",
    "hudson_h2_d2_s4201": "Hudson 4201",
}
METHODS = {
    "C0": ("C0", "#202b45", "-", None),
    "C0_PREFIX": ("Fixed quota", "#a65119", "--", "o"),
    "C0_PROGRESS": ("Progress-gated", "#007663", "-.", "D"),
}
PAIR_FOR_METHOD = {
    "C0_PREFIX": "fixed_vs_control",
    "C0_PROGRESS": "progress_vs_control",
}


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def groups_and_representatives(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["instance"], row["method"]].append(row)
    expected = {(case, method) for case in CASES for method in METHODS}
    if groups.keys() != expected:
        raise ValueError("The archive must have all four cases and all three arms")
    representatives = {}
    for key, group in groups.items():
        if sorted(int(row["repetition"]) for row in group) != [0, 1, 2]:
            raise ValueError(f"Expected three repeats for {key}")
        representatives[key] = sorted(
            group, key=lambda row: (float(row["J"]), int(row["repetition"]))
        )[1]
    return groups, representatives


def plot(directory):
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8-sig"))
    if (summary.get("valid_runs") != 36 or summary.get("expected_runs") != 36
            or summary.get("stage") != "P30"):
        raise ValueError("Expected a complete analyzed 36-run P30 archive")
    groups, reps = groups_and_representatives(read_csv(directory / "comparison.csv"))
    pairs = {(item["pair"], item["instance"]): item for item in summary["pairs"]}
    survival = defaultdict(list)
    for row in read_csv(directory / "survival.csv"):
        survival[row["run_id"]].append((int(row["tick"]), 100 * float(row["pd"])))

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 11,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.titleweight": "bold",
        "legend.frameon": False,
        "savefig.facecolor": "white",
    })
    fig, panels = plt.subplots(2, 2, figsize=(13.7, 8.6), layout="constrained")
    fig.suptitle("Progress-gated prefix scheduling", fontsize=19, weight="bold")
    case_x = range(len(CASES))
    labels = list(CASES.values())
    left, right = panels[0]

    for offset, (method, pair) in zip((-0.18, 0.18), PAIR_FOR_METHOD.items()):
        label, color, _, _ = METHODS[method]
        gains = []
        for case in CASES:
            entry = pairs[pair, case]
            if (entry["candidate_run_id"] != reps[case, method]["run_id"]
                    or entry["control_run_id"] != reps[case, "C0"]["run_id"]):
                raise ValueError(f"Representative mismatch for {case} {method}")
            gains.append(100 * float(entry["relative_J_gain"]))
        left.bar([x + offset for x in case_x], gains, 0.32, color=color, label=label)
    left.axhline(0, color="#303849", linewidth=1)
    left.axhline(0.1, color="#687184", linestyle=":", linewidth=1.5, label="0.1% gain")
    left.set_title("A  J improvement vs C0")
    left.set_ylabel("Relative J reduction (%)")
    left.legend(loc="best", fontsize=9)

    for offset, (method, (label, color, _, _)) in zip((-0.25, 0, 0.25), METHODS.items()):
        rss = [median(float(row["peak_rss_mib"]) for row in groups[case, method])
               for case in CASES]
        right.bar([x + offset for x in case_x], rss, 0.22, color=color, label=label)
    right.set_title("B  Peak process memory")
    right.set_ylabel("Median peak RSS (MiB)")
    right.set_ylim(bottom=0)
    right.legend(loc="best", fontsize=9)

    for axes in (left, right):
        axes.set_xticks(list(case_x), labels)
        axes.grid(axis="y", alpha=0.2)
        axes.set_axisbelow(True)

    for panel_letter, axes, case in zip("CD", panels[1], list(CASES)[2:]):
        for method, (label, color, linestyle, marker) in METHODS.items():
            row = reps[case, method]
            points = sorted(survival[row["run_id"]])
            if not points or [tick for tick, _ in points] != list(range(len(points))):
                raise ValueError(f"Missing survival ticks for {row['run_id']}")
            ticks, pd = zip(*points)
            if abs(pd[-1] - 100 * float(row["pd_final"])) > 1e-7:
                raise ValueError(f"Terminal Pd mismatch for {row['run_id']}")
            markstart = 3 if method == "C0_PREFIX" else 6
            axes.plot(ticks, pd, color=color, linewidth=1.9, linestyle=linestyle,
                      marker=marker, markersize=3,
                      markevery=(markstart, 8) if marker else None,
                      label=f"{label} {pd[-1]:.2f}%")
        axes.set_title(f"{panel_letter}  {CASES[case]} detection over the mission")
        axes.set_xlabel("Observation tick")
        axes.set_ylabel("Cumulative detection probability (%)")
        axes.set_xlim(left=0)
        axes.set_ylim(bottom=0)
        axes.grid(alpha=0.2)
        axes.legend(loc="upper left", fontsize=9)

    destination = directory / "progress_comparison.png"
    fig.savefig(destination, dpi=170)
    plt.close(fig)
    print(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Analyzed local_rN directory")
    arguments = parser.parse_args()
    plot(arguments.archive)
