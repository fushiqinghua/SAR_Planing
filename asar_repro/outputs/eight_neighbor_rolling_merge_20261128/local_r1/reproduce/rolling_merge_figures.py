"""Render byte-verified D0 and F30 diagnostics from a completed rolling-merge run.

Run from asar_repro: python <script> --out outputs/eight_neighbor_rolling_merge_20261128/local_r1
"""

import argparse
from collections import defaultdict
import csv
from hashlib import sha256
import json
from math import isclose, isfinite
from pathlib import Path
from statistics import median

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import PercentFormatter


DEFAULT_OUT = Path("outputs/eight_neighbor_rolling_merge_20261128/local_r1")
INK = "#1b2936"
COLORS = {"C0": "#286487", "C1": "#b1492b", "C0_M": "#328270", "C1_M": "#75528e"}
DASHES = {"C0": (0, (5, 3)), "C1": (0, (2, 1)), "C0_M": (0, (6, 2, 1, 2)), "C1_M": "-"}
LABELS = {
    "lake_h2_d1_s3101": "Lake D1\n3101",
    "lake_h2_d2_s3201": "Lake D2\n3201",
    "hudson_h2_d1_s4101": "Hudson D1\n4101",
    "hudson_h2_d2_s4201": "Hudson D2\n4201",
}
MIB = 1024 * 1024


def check(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(path):
    digest = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def number(row, key):
    value = float(row[key])
    check(isfinite(value), f"Non-finite {key} in {row.get('run_id')}")
    return value


def verify_stage(out, stage, count, protocol_sha):
    folder = out / stage
    summary = read_json(folder / "summary.json")
    status = summary["status"]
    check(summary["stage"] == stage and summary["protocol_sha256"] == protocol_sha,
          f"Unexpected {stage} protocol identity")
    check(status["status"] == "complete" and status["planned"] == status["valid"] == count
          and not status["errors"] and not status["missing"], f"{stage} is incomplete")
    check(summary["formal_optimality_certificate"] is False and summary["speedup_claim"] is False,
          f"Unsupported {stage} certificate or speedup claim")
    expected = {"comparison.csv", "survival.csv", "phases.csv", "merge_diagnostics.csv",
                "incumbent_history.csv", "instance_comparison.csv"}
    hashes = summary["derived_file_sha256"]
    check(set(hashes) == expected, f"Missing {stage} evidence table")
    for name, sha in hashes.items():
        check(digest(folder / name) == sha, f"{stage}/{name} checksum mismatch")
    records = summary["raw_evidence"]
    matrix = read_csv(folder / "comparison.csv")
    check(len(matrix) == count and len({r["run_id"] for r in matrix}) == count
          and set(records) == {r["run_id"] for r in matrix}, f"Invalid {stage} task matrix")
    for run_id, sha in records.items():
        check(Path(run_id).name == run_id and run_id.startswith(stage + "_"),
              f"Unexpected run ID {run_id}")
        record_dir = out / "runs" / run_id
        record = read_json(record_dir / "record.json")
        check(record["status"] == "completed" and record["returncode"] == 0
              and record["watchdog"] is None and record["result_sha256"] == sha
              and digest(record_dir / "result.json") == sha,
              f"Raw run {run_id} failed byte or validity checks")
    return summary, matrix


def read_d0(out, cases, protocol_sha, rules):
    summary, matrix = verify_stage(out, "D0", len(cases), protocol_sha)
    gate = read_json(out / "D0_gate.json")
    check(gate["protocol_sha256"] == protocol_sha and gate["decision"] == summary["decision"]
          and gate["raw_evidence"] == summary["raw_evidence"], "D0 gate differs from summary")
    check({(r["instance"], r["method"], r["repetition"]) for r in matrix}
          == {(case, "D0", "0") for case in cases}, "Unexpected D0 registration")
    diagnostics = read_csv(out / "D0/merge_diagnostics.csv")
    by_case = {r["instance"]: r for r in diagnostics}
    decision = gate["decision"]
    check(len(diagnostics) == len(by_case) == len(cases)
          and {r["instance"] for r in decision["instances"]} == set(cases), "Missing D0 case")
    for row in decision["instances"]:
        case = row["instance"]
        stat = by_case[case]
        optional = int(stat["mergeable_children"])
        total = int(stat["nonterminal_children"])
        cap = int(stat["capacity_skips"])
        qualifies = optional >= rules["minimum_mergeable_children"] and (
            total > 0 and optional / total >= rules["minimum_mergeable_fraction"])
        check(row["run_id"] == stat["run_id"] and stat["mode"] == "shadow"
              and int(stat["discarded_children"]) == int(stat["stale_pops"]) == 0
              and 0 <= optional + cap <= total
              and row["mergeable_children"] == optional and row["nonterminal_children"] == total
              and row["capacity_skips"] == cap and row["qualifies"] == qualifies,
              f"D0 statistics differ from gate for {case}")
    return gate, by_case


def read_f30(out, config, protocol_sha, gate):
    summary, matrix = verify_stage(out, "F30", 48, protocol_sha)
    check(gate["decision"]["passed"] and summary["D0_gate_sha256"] == digest(out / "D0_gate.json"),
          "F30 does not bind a passing D0 gate")
    groups = defaultdict(dict)
    for row in matrix:
        identity = (row["instance"], row["method"])
        groups[identity][int(row["repetition"])] = row
    check(set(groups) == {(case, method) for case in config["instances"] for method in config["methods"]}
          and all(set(reps) == {0, 1, 2} for reps in groups.values()), "Incomplete F30 repetition matrix")
    representatives = {
        key: sorted(reps.values(), key=lambda r: (number(r, "J"), int(r["repetition"])))[1]
        for key, reps in groups.items()
    }
    pairs = read_csv(out / "F30/instance_comparison.csv")
    comparisons = {(r["comparison"], r["instance"]): r for r in pairs}
    check(len(comparisons) == len(pairs) == 16, "Expected sixteen F30 instance pairs")
    for pair in config["comparisons"]:
        for case in config["instances"]:
            control, candidate = pair["control"], pair["candidate"]
            a, b = representatives[case, control], representatives[case, candidate]
            official = comparisons[pair["id"], case]
            j0, j1 = number(a, "J"), number(b, "J")
            p0, p1 = number(a, "pd_final"), number(b, "pd_final")
            check(j0 > 0 and j1 > 0 and official["control_run_id"] == a["run_id"]
                  and official["candidate_run_id"] == b["run_id"]
                  and isclose(number(official, "relative_J_gain"), (j0 - j1) / j0, abs_tol=1e-12)
                  and isclose(number(official, "delta_pd_percentage_points"), 100 * (p1 - p0), abs_tol=1e-12),
                  f"Median-J reference or same-route Pd mismatch for {pair['id']} / {case}")
    return groups, representatives, comparisons


def names(ax, cases):
    ax.set_xticks(range(len(cases)), [LABELS[c] for c in cases])
    ax.grid(axis="y", color="#d7e0e8", alpha=0.65, zorder=0)


def d0_plot(cases, diagnostics, rules):
    rows = [diagnostics[case] for case in cases]
    total = [int(r["nonterminal_children"]) for r in rows]
    matches = [int(r["mergeable_children"]) for r in rows]
    skipped = [int(r["capacity_skips"]) for r in rows]
    rate = [100 * a / b if b else 0 for a, b in zip(matches, total, strict=True)]
    cap = [100 * a / b if b else 0 for a, b in zip(skipped, total, strict=True)]
    min_rate = 100 * rules["minimum_mergeable_fraction"]
    min_count = rules["minimum_mergeable_children"]
    x = range(len(cases))
    fig, axes = plt.subplots(1, 2, figsize=(12.3, 5.0), layout="constrained")
    fig.suptitle("D0 · Exact-state opportunities in the charged shadow search", weight="bold")
    colors = ["#328270" if a >= min_rate and b >= min_count else "#8098ab"
              for a, b in zip(rate, matches, strict=True)]
    bars = axes[0].bar(x, rate, color=colors, zorder=3)
    axes[0].bar_label(bars, labels=[f"{p:.3f}%\n{n:,} children" for p, n in zip(rate, matches, strict=True)],
                      padding=4, fontsize=9)
    axes[0].axhline(min_rate, color="#8b4b40", ls=":", label=f"{min_rate:g}% rate gate")
    axes[0].legend(loc="upper left")
    axes[0].set_ylim(0, max(max(rate), min_rate) * 1.30)
    axes[0].set(ylabel="% of eligible nonterminal children",
                title=f"Exact matches with stored J ≤ child J\nCount gate is {min_count} children")
    bars = axes[1].bar(x, cap, color="#b77d47", zorder=3)
    axes[1].bar_label(bars, labels=[f"{p:.1f}%\n{n:,} children" for p, n in zip(cap, skipped, strict=True)],
                      padding=4, fontsize=9)
    axes[1].set_ylim(0, 111)
    axes[1].set(ylabel="% of eligible nonterminal children",
                title="New keys skipped at index capacity\nIdentity beyond these misses remains unobserved")
    for ax in axes:
        names(ax, cases)
    return fig


def paired_j_plot(config, groups, comparisons):
    cases = config["instances"]
    threshold = 100 * config["decision"]["instance_winner_min"]
    repeats, centers = {}, {}
    for pair in config["comparisons"]:
        for case in cases:
            identity = (pair["id"], case)
            c = groups[case, pair["control"]]
            b = groups[case, pair["candidate"]]
            repeats[identity] = [100 * (1 - number(b[r], "J") / number(c[r], "J")) for r in range(3)]
            centers[identity] = 100 * number(comparisons[identity], "relative_J_gain")
    extents = [0.0, threshold, *centers.values(), *(v for group in repeats.values() for v in group)]
    lo, hi = min(extents), max(extents)
    margin = max(0.10, 0.16 * (hi - lo))
    fig, axes = plt.subplots(2, 2, figsize=(13.8, 8.3), layout="constrained", sharey=True)
    fig.suptitle("F30 · Four registered contrasts at the same total budget", weight="bold")
    marks, shifts = ("o", "s", "^"), (-0.19, 0.0, 0.19)
    for ax, pair in zip(axes.flat, config["comparisons"], strict=True):
        ax.axhline(0, color=INK, lw=0.8, zorder=1)
        ax.axhline(threshold, color="#486650", ls=":", lw=1.3, zorder=1)
        for x, case in enumerate(cases):
            identity = (pair["id"], case)
            gain = centers[identity]
            ax.hlines(gain, x - 0.31, x + 0.31, color="#b1492b", lw=2.8, zorder=4)
            for dx, mark, value in zip(shifts, marks, repeats[identity], strict=True):
                ax.scatter(x + dx, value, marker=mark, s=30, color="#286487", alpha=0.68, zorder=3)
            ax.annotate(f"{gain:+.2f}%", (x, gain), xytext=(6, 7), textcoords="offset points",
                        ha="left", color="#a13d26", fontsize=9, weight="bold")
        ax.set_ylim(lo - margin, hi + margin)
        ax.set_xlim(-0.52, 3.64)
        ax.set_title(f"{pair['candidate']} vs {pair['control']}  ·  {pair['role']}")
        names(ax, cases)
    for ax in axes[:, 0]:
        ax.set_ylabel("Relative reduction in J (%)")
    fig.legend(handles=[
        Line2D([0], [0], color="#b1492b", lw=2.8, label="Gain from separately selected median-J runs"),
        Line2D([0], [0], color="#486650", linestyle=":", label=f"Registered {threshold:g}% gate"),
        *[Line2D([0], [0], color="#286487", linestyle="none", marker=m,
                  label=f"Same-index timing repeat {r}") for r, m in enumerate(marks)],
    ], loc="outside lower center", ncol=3, fontsize=9)
    return fig


def detection_plot(out, config, representatives):
    reference_points = defaultdict(list)
    keys = {r["run_id"] for r in representatives.values()}
    for p in read_csv(out / "F30/survival.csv"):
        if p["run_id"] in keys:
            reference_points[p["run_id"]].append(p)
    fig, axs = plt.subplots(2, 2, figsize=(12.8, 8.0), layout="constrained")
    fig.suptitle("F30 · Cumulative detection on the original observation clock", weight="bold")
    for ax, case in zip(axs.flat, config["instances"], strict=True):
        observation_clock = None
        pd_summary = []
        for method in config["methods"]:
            rep = representatives[case, method]
            points = sorted(reference_points[rep["run_id"]], key=lambda p: int(p["tick"]))
            t = [number(p, "time_s") for p in points]
            d = [number(p, "pd_by_time") for p in points]
            check(len(t) > 1 and t[0] == 0 and all(b > a for a, b in zip(t, t[1:]))
                  and isclose(d[-1], number(rep, "pd_final"), abs_tol=1e-10),
                  f"Inconsistent observation evidence for {rep['run_id']}")
            if observation_clock is None:
                observation_clock = t
            check(t == observation_clock, f"Physical observation clock changed for {case}")
            color = COLORS[method]
            ax.step(t, d, where="post", color=color, linestyle=DASHES[method],
                    alpha=0.88, lw=1.8, label=method)
            ax.scatter(t[-1], d[-1], s=18, color=color, zorder=4)
            pd_summary.append(f"{method} {d[-1]:.2%}")
        ax.set_title(f"{LABELS[case].replace(chr(10), ' · ')}  |  " + " / ".join(pd_summary), fontsize=10.5)
        ax.set_xlabel("Physical time since CST (s)")
        ax.yaxis.set_major_formatter(PercentFormatter(1))
        ax.set_ylabel("Cumulative detection probability")
        ax.grid(color="#d7e0e8", alpha=0.65)
    handles = axs.flat[0].get_legend_handles_labels()[0]
    fig.legend(handles=handles, loc="outside lower center", ncol=4,
               title="Actual representative routes selected by median J")
    return fig


def resource_plot(out, config, groups):
    cases, methods = config["instances"], config["methods"]
    stats = defaultdict(list)
    for row in read_csv(out / "F30/merge_diagnostics.csv"):
        stats[row["run_id"]].append(row)
    fig, axes = plt.subplots(2, 2, figsize=(13.8, 8.0), layout="constrained")
    fig.suptitle("F30 · Merging events and measured resource use", weight="bold")
    measures = (
        ("discarded", "Exact child discards across calls", "child events · symmetric log axis"),
        ("lookup", "Charged index lookup including key build", "seconds per run"),
        ("wall", "Total algorithm wall time", "seconds per run"),
        ("rss", "Sampled process peak RSS", "MiB per run"),
    )
    for ax, (metric, title, unit) in zip(axes.flat, measures, strict=True):
        shown = methods if metric in {"wall", "rss"} else [m for m in methods if m.endswith("_M")]
        spacing = 0.19 if len(shown) == 4 else 0.24
        for i, case in enumerate(cases):
            for index, method in enumerate(shown):
                x = i + (index - (len(shown) - 1) / 2) * spacing
                values = []
                for repeat in range(3):
                    item = groups[case, method][repeat]
                    if metric == "wall":
                        value = number(item, "algorithm_wall_s")
                    elif metric == "rss":
                        value = number(item, "peak_rss_bytes") / MIB
                    else:
                        key = "discarded_children" if metric == "discarded" else "lookup_s"
                        value = sum(number(row, key) for row in stats[item["run_id"]] if row.get(key))
                    values.append(value)
                color = COLORS[method]
                ax.scatter([x - 0.043, x, x + 0.043], values, color=color, s=24, alpha=0.55, zorder=3)
                ax.hlines(median(values), x - 0.070, x + 0.070, color=color, lw=2, zorder=4)
        if metric == "discarded":
            ax.set_yscale("symlog", linthresh=1)
        if metric == "wall":
            ax.axhline(config["stages"]["F30"]["seconds"], color="#646d60", ls=":", lw=1)
        names(ax, cases)
        ax.set_xlim(-0.52, 3.52)
        ax.set(title=title, ylabel=unit)
    fig.legend(handles=[Line2D([0], [0], color=COLORS[m], marker="o", label=m) for m in methods],
               loc="outside lower center", ncol=4, title="Dots show timing repeats. Dashes show medians.")
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out = args.out.resolve()
    protocol_file = out / "protocol.json"
    protocol_sha = digest(protocol_file)
    config = read_json(protocol_file)["config"]
    cases = config["instances"]
    check(len(cases) == 4 and set(cases) == set(LABELS), "Unexpected registered instances")
    check(set(config["methods"]) == set(COLORS), "Unexpected registered methods")
    gate, diagnostic = read_d0(out, cases, protocol_sha, config["diagnostic_gate"])
    f30_path = out / "F30/summary.json"
    f30_ready = f30_path.is_file() and read_json(f30_path)["status"]["status"] == "complete"
    f30 = read_f30(out, config, protocol_sha, gate) if f30_ready else None
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10, "figure.facecolor": "white",
        "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#8795a2",
        "axes.labelcolor": INK, "text.color": INK, "xtick.color": INK, "ytick.color": INK,
        "legend.frameon": False,
    })
    target = out / "figures"
    target.mkdir(exist_ok=False)
    constructors = [
        ("01_d0_opportunity_capacity.png", lambda: d0_plot(cases, diagnostic, config["diagnostic_gate"])),
    ]
    selected = {}
    if f30 is not None:
        groups, representatives, comparisons = f30
        constructors.extend([
            ("02_f30_paired_relative_j.png", lambda: paired_j_plot(config, groups, comparisons)),
            ("03_f30_cumulative_pd.png", lambda: detection_plot(out, config, representatives)),
            ("04_f30_merge_resources.png", lambda: resource_plot(out, config, groups)),
        ])
        selected = {case: {method: representatives[case, method]["run_id"]
                           for method in config["methods"]} for case in cases}
    assets = {}
    for name, make in constructors:
        fig = make()
        path = target / name
        fig.savefig(path, dpi=190)
        plt.close(fig)
        assets[name] = digest(path)
    manifest = {
        "protocol_sha256": protocol_sha, "d0_gate_sha256": digest(out / "D0_gate.json"),
        "d0_summary_sha256": digest(out / "D0/summary.json"),
        "f30_summary_sha256": digest(f30_path) if f30_ready else None,
        "generator_sha256": digest(Path(__file__).resolve()),
        "matplotlib_version": matplotlib.__version__,
        "median_j_representative_run_ids": selected,
        "png_sha256": assets,
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(assets)} verified diagnostic figures to {target}.")


if __name__ == "__main__":
    main()
