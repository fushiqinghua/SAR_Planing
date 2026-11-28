"""Audit delayed OPEN splitting runs and apply the preregistered gates."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
from math import isclose, isfinite
from pathlib import Path
from statistics import median

import analyze_eight_neighbor_prefix_order as metrics
import analyze_eight_neighbor_progress as progress_analysis


ROOT = Path(__file__).resolve().parents[1]
METHODS = ("C0", "C0_PROGRESS", "C0_LAZY")
INSTANCES = progress_analysis.INSTANCES
PAIRS = (
    ("lazy_vs_control", "C0_LAZY", "C0"),
    ("progress_vs_control", "C0_PROGRESS", "C0"),
    ("lazy_vs_progress", "C0_LAZY", "C0_PROGRESS"),
)
EXPECTED_ALGORITHM = {
    "C0": "physical_refinement_diagnostic_v1",
    "C0_PROGRESS": "physical_progress_prefix_v1",
    "C0_LAZY": "physical_lazy_prefix_v1",
}
H4101 = "hudson_h2_d1_s4101"
H4201 = "hudson_h2_d2_s4201"
H4201_J = 58.5220872
H4201_PD = 0.090948
ABS_TOL = 1e-8


def require(condition, detail):
    if not condition:
        raise ValueError(detail)


def file_sha(path):
    return sha256(path.read_bytes()).hexdigest()


def same_score(replayed, recorded):
    return (
        replayed["waypoints"] == recorded["waypoints"]
        and replayed["observation_times_s"] == recorded["observation_times_s"]
        and isclose(replayed["physical_duration_s"], recorded["physical_duration_s"],
                    rel_tol=0, abs_tol=ABS_TOL)
        and len(replayed["survival"]) == len(recorded["survival"])
        and all(isclose(a, b, rel_tol=0, abs_tol=ABS_TOL)
                for a, b in zip(replayed["survival"], recorded["survival"]))
        and all(isclose(replayed[k], recorded[k], rel_tol=0, abs_tol=ABS_TOL)
                for k in ("J", "pd_final"))
    )


def scheduler_metrics(inner, method, gate):
    diagnostic = inner["diagnostics"]
    history = inner["history"]
    deadline = inner["max_seconds"]
    first_terminal = diagnostic["first_search_terminal_generated_s"]
    first_search = next((entry["elapsed_s"] for entry in history if entry["source"] == "search"), None)
    require(history and history[0]["source"] == "initial_route", "Initial route is missing from history")
    require(all(0 <= entry["elapsed_s"] <= deadline for entry in history),
            "Incumbent outside inner search budget")
    require(all(a["elapsed_s"] <= b["elapsed_s"] and b["J"] < a["J"] - 1e-10
                for a, b in zip(history, history[1:])), "Invalid incumbent chronology or improvement")
    require(first_search is None or (first_terminal is not None and first_terminal <= first_search),
            "Strict search improvement precedes the first search terminal")
    order = diagnostic.get("prefix_order") or {}
    progress = diagnostic.get("progress_schedule")
    require((progress is not None) == (method != "C0"), "Incorrect scheduler evidence for this arm")
    cutoff = deadline * gate["first_search_improvement_before_fraction"]
    if progress is not None:
        reported_first = progress["first_search_improvement_s"]
        require(reported_first == first_search
                or (method == "C0_LAZY" and reported_first is None
                    and first_search is not None and first_search > cutoff),
                "First strict search improvement differs from history")
    events = [] if progress is None else progress["events"]
    active = False
    previous = -1.0
    for event in events:
        elapsed = event["elapsed_s"]
        tail = event["tail_fraction"]
        require(first_search is not None and first_search <= min(elapsed, cutoff)
                and previous <= elapsed <= deadline and 0 <= tail <= 1
                and (tail * gate["window_expansions"]).is_integer(), "Invalid scheduler event")
        latest = next(entry["elapsed_s"] for entry in reversed(history) if entry["elapsed_s"] <= elapsed)
        if event["event"] == "on":
            require(not active and tail >= gate["tail_enter_fraction"]
                    and elapsed - latest >= gate["stagnation_seconds"], "Invalid scheduler activation")
            active = True
        else:
            require(event["event"] == "off" and active
                    and (tail < gate["tail_exit_fraction"]
                         or elapsed - latest < gate["recent_improvement_pause_s"]),
                    "Invalid scheduler deactivation")
            active = False
        previous = elapsed
    activations = sum(event["event"] == "on" for event in events)
    deactivations = len(events) - activations
    if progress is not None:
        require(activations == progress["activations"] and deactivations == progress["deactivations"],
                "Scheduler event count differs from final record")
    if not activations:
        require(not (order.get("reserved_early_pops", 0) or order.get("reserved_middle_pops", 0)),
                "Reserved pop without an activation")
    lazy = diagnostic.get("lazy_frontier")
    require((lazy is not None) == (method == "C0_LAZY"), "Unexpected lazy migration evidence")
    if lazy is not None:
        attempts, migrations = lazy["migration_attempts"], lazy["migrations"]
        require(lazy["starting_heaps"] == 1 and 0 <= migrations <= attempts <= 1
                and bool(attempts) == bool(activations)
                and lazy["ending_heaps"] == (3 if migrations else 1)
                and lazy["diagnostic_heaps"] is None and not lazy["diagnostic_statistics"]
                and not lazy["trace_pops"] and isfinite(lazy["migration_s"])
                and 0 <= lazy["migration_s"] <= inner["wall_s"], "Invalid lazy migration counters")
        require(bool(lazy["migrated_open"]) == bool(migrations)
                and (migrations or not (order.get("reserved_early_pops", 0)
                                         or order.get("reserved_middle_pops", 0))),
                "Reservation occurred without a completed migration")
        require(isclose(progress["qualification_cutoff_s"], cutoff, rel_tol=0, abs_tol=ABS_TOL)
                and 0 <= progress["retained_tail_count"] <= progress["retained_window_size"]
                <= min(progress["monitored_expansions"], gate["window_expansions"])
                and progress["monitored_expansions"] <= inner["expanded"], "Invalid tail window evidence")
        if progress["expired"]:
            require(not progress["eligible"] and not activations
                    and cutoff < progress["expired_s"] <= deadline, "Invalid eligibility cutoff")
    return dict(
        first_search_improvement_s=first_search,
        first_search_cutoff_s=cutoff if progress is not None else None,
        first_activation_s=next((e["elapsed_s"] for e in events if e["event"] == "on"), None),
        activations=activations,
        deactivations=deactivations,
        active_decisions=0 if progress is None else progress["active_decisions"],
        reserved_early_pops=order.get("reserved_early_pops", 0),
        reserved_middle_pops=order.get("reserved_middle_pops", 0),
        migration_attempts=0 if lazy is None else lazy["migration_attempts"],
        migrations=0 if lazy is None else lazy["migrations"],
        migration_s=0.0 if lazy is None else lazy["migration_s"],
        migrated_open=0 if lazy is None else lazy["migrated_open"],
        ending_heaps=(3 if method == "C0_PROGRESS" else 1) if lazy is None else lazy["ending_heaps"],
        eligibility_expired_s=None if lazy is None else progress["expired_s"],
        monitored_expansions=None if lazy is None else progress["monitored_expansions"],
        schedule_events=events,
    )


def load_problems(protocol):
    from asar_repro.h2_inputs import load_h2_input

    references = protocol["references"]
    source = ROOT / protocol["config"]["source_root"] / "inputs"
    problems = {}
    for instance in INSTANCES:
        problem, _, _, info = load_h2_input(
            ROOT, references["instances"][instance], source / instance, "heading_square")
        archive = references["archive_hashes"][instance]
        require(info["manifest_sha256"] == archive["manifest_sha256"]
                and info["particle_sha256"] == archive["particle_sha256"]
                and info["forcing_kind"] == "historical_real"
                and info["opendrift_runs_in_search"] == 0, f"Invalid H2 archive for {instance}")
        problems[instance] = problem
    return problems


def collect(out, protocol):
    from asar_repro.physical_search import independent_replay
    from run_eight_neighbor_rolling import object_digest, verify_result

    tasks = metrics.read_json(out / "tasks.json")
    expected = Counter((i, m, r) for i in INSTANCES for m in METHODS for r in range(3))
    observed = Counter((t["instance"], t["method"], t["repetition"]) for t in tasks)
    require(expected == observed and all(t["seconds"] == 30 for t in tasks),
            "Formal tasks do not match the frozen 36-run matrix")
    task_keys = {object_digest(task) for task in tasks}
    protocol_sha = file_sha(out / "protocol.json")
    validation_sha = file_sha(out / "validation" / "validation.json")
    problems = load_problems(protocol)
    rows, schedules, survival, histories = [], [], [], []
    emitted = set()
    gate = protocol["design"]["progress_policy"]["activation"]
    for folder in sorted((out / "runs").iterdir()):
        task = metrics.read_json(folder / "task.json")
        identity = object_digest(task)
        require(identity in task_keys and identity not in emitted, f"Unregistered task {folder.name}")
        emitted.add(identity)
        record = metrics.read_json(folder / "record.json")
        result_path = folder / "result.json"
        payload = metrics.read_json(result_path)
        evidence = record["frozen_evidence"]
        require(record["task"] == task == payload["task"] and record["status"] == "completed"
                and record["returncode"] == 0 and record["watchdog"] is None
                and record["verification_error"] is None
                and evidence["protocol_sha256"] == protocol_sha and evidence["validation_sha256"] == validation_sha
                and record["result_sha256"] == file_sha(result_path)
                and (folder / "stdout.log").is_file() and (folder / "stderr.log").is_file(),
                f"Invalid frozen run record {folder.name}")
        result = payload["result"]
        method = task["method"]
        inner = metrics.extract_inner(result["raw"])
        wall = result["algorithm_wall_s"]
        cpu = result["algorithm_cpu_s"]
        require(0 < wall <= 30 and isfinite(cpu) and cpu >= 0
                and result["method"] == method and inner["algorithm"] == EXPECTED_ALGORITHM[method]
                and inner["max_expansions"] is None, f"Wrong method or budget in {folder.name}")
        verify_result(dict(task, method="C0"), dict(result, method="C0"), protocol)
        score = result["physical_replay"]
        problem = problems[task["instance"]]
        route = score["waypoints"]
        require(same_score(problem.replay(route, connectivity=8), score)
                and same_score(independent_replay(problem, route, connectivity=8), score),
                f"Independent route replay mismatch in {folder.name}")
        row = metrics.run_metrics(task, result, record, folder.name)
        row["wall_minus_cpu_s"] = wall - cpu
        rows.append(row)
        common = {key: row[key] for key in ("run_id", "instance", "region", "method", "repetition")}
        schedules.append(dict(common, **scheduler_metrics(inner, method, gate)))
        for tick, (clock, mass) in enumerate(zip([0.0] + score["observation_times_s"], score["survival"])):
            survival.append(dict(common, tick=tick, time_s=clock, remaining_mass=mass, pd=1 - mass))
        for entry in inner["history"]:
            histories.append(dict(common, elapsed_s=entry["elapsed_s"], source=entry["source"],
                                  J=entry["J"], pd_final=entry["pd_final"]))
    require(emitted == task_keys, "Incomplete formal comparison")
    return rows, schedules, survival, histories


def comparisons(rows):
    result = []
    for name, candidate, control in PAIRS:
        for instance in INSTANCES:
            a = progress_analysis.representative(rows, instance, candidate)
            b = progress_analysis.representative(rows, instance, control)
            gain = (b["J"] - a["J"]) / b["J"]
            delta = a["pd_final"] - b["pd_final"]
            result.append(dict(
                pair=name, instance=instance, region=a["region"], candidate=candidate, control=control,
                candidate_run_id=a["run_id"], control_run_id=b["run_id"],
                candidate_J=a["J"], control_J=b["J"], candidate_Pd=a["pd_final"], control_Pd=b["pd_final"],
                relative_J_gain=gain, delta_Pd_pp=100 * delta,
                threshold_0p1=gain >= progress_analysis.MIN_GAIN,
                threshold_0p5=gain >= progress_analysis.SECONDARY_GAIN,
                J_nonregression=gain >= -progress_analysis.J_TOL,
                Pd_guard=delta >= -progress_analysis.MAX_PD_DROP,
            ))
    return result


def method_summary(rows):
    output = []
    for instance in INSTANCES:
        for method in METHODS:
            items = [row for row in rows if row["instance"] == instance and row["method"] == method]
            selected = progress_analysis.representative(rows, instance, method)
            output.append(dict(
                instance=instance, method=method, run_id=selected["run_id"], J=selected["J"],
                Pd=selected["pd_final"],
                median_wall_s=median(row["algorithm_wall_s"] for row in items),
                median_cpu_s=median(row["algorithm_cpu_s"] for row in items),
                median_rss_mib=median(row["peak_rss_mib"] for row in items),
                max_rss_mib=max(row["peak_rss_mib"] for row in items),
                median_expanded=median(row["expanded"] for row in items),
                median_terminal_candidates=median(row["terminal_candidates"] for row in items),
                median_tail_fraction=median(row["tail_expanded_fraction"] for row in items),
                stop_reasons=dict(Counter(row["stop_reason"] for row in items)),
            ))
    return output


def summarize(rows):
    pairs = comparisons(rows)
    screens = [progress_analysis.screen(pairs, key) for key, _, _ in PAIRS]
    primary = screens[0]
    protection = next(row for row in pairs if row["pair"] == primary["pair"] and row["instance"] == H4101)
    retention = progress_analysis.representative(rows, H4201, "C0_LAZY")
    j_retained = retention["J"] <= H4201_J + ABS_TOL
    pd_retained = retention["pd_final"] >= H4201_PD - ABS_TOL
    protected_4101 = protection["J_nonregression"] and protection["Pd_guard"]
    status = ("lazy_prefix_development_screen_passed"
              if primary["passed"] and protected_4101 and j_retained and pd_retained
              else "lazy_prefix_development_screen_not_passed")
    return dict(
        status=status, stage="P30", valid_runs=len(rows), expected_runs=36,
        primary_decision=primary["pair"], screens=screens, pairs=pairs,
        hudson_4101=dict(
            instance=H4101, passed=protected_4101, J_nonregression=protection["J_nonregression"],
            Pd_guard=protection["Pd_guard"], relative_J_gain=protection["relative_J_gain"],
            delta_Pd_pp=protection["delta_Pd_pp"], candidate_run_id=protection["candidate_run_id"],
            control_run_id=protection["control_run_id"],
        ),
        hudson_4201=dict(
            instance=H4201, passed=j_retained and pd_retained, target_J=H4201_J, target_Pd=H4201_PD,
            absolute_tolerance=ABS_TOL, J_retained=j_retained, Pd_retained=pd_retained,
            J=retention["J"], Pd=retention["pd_final"], candidate_run_id=retention["run_id"],
        ),
        method_instances=method_summary(rows), data_role="seen_H2_development",
        dual_route_replay=True, optimality_certified=False,
    )


def report(out, summary):
    primary = summary["primary_decision"]
    h1, h2 = summary["hudson_4101"], summary["hudson_4201"]
    lines = [
        "# 延迟分堆同预算实验", "",
        f"正式结果为 **{summary['status']}**。36 项完整运行均经双重物理重放。",
        "每实例每方法取 J 排序后的中位路线，同路线提供终点 Pd。三组沿用原目标、评分器、forcing 和 S30 初始路线。",
        "", "## 延迟分堆相对同批 C0", "",
        "| 实例 | C0 J | 延迟分堆 J | J 改善 | C0 Pd | 延迟分堆 Pd | Pd 变化（百分点） |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["pairs"]:
        if row["pair"] == primary:
            lines.append(f"| {row['instance']} | {row['control_J']:.9f} | {row['candidate_J']:.9f} | "
                         f"{row['relative_J_gain']:+.4%} | {row['control_Pd']:.4%} | "
                         f"{row['candidate_Pd']:.4%} | {row['delta_Pd_pp']:+.4f} |")
    h1_label = "通过" if h1["passed"] else "未通过"
    h2_label = "保住" if h2["passed"] else "未同时保住"
    lines += [
        "",
        f"**Hudson 4101 {h1_label}原 J/Pd 护栏。** 相对同批 C0 的 J 改善为 "
        f"{h1['relative_J_gain']:+.4%}、终点 Pd 变化为 {h1['delta_Pd_pp']:+.4f} 个百分点。",
        f"**Hudson 4201 {h2_label}上一批的 J/Pd。** 代表路线为 "
        f"J={h2['J']:.9f}、Pd={h2['Pd']:.4%}，目标为 J≤{H4201_J}、Pd≥{H4201_PD:.4%}。",
        "",
        "## 三组配对筛选", "",
        "| 配对 | 通过 | J 改善 ≥0.1% | J 改善 ≥0.5% | 所有 J 非退化 | 所有 Pd 过护栏 |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for row in summary["screens"]:
        lines.append(f"| {row['pair']} | {row['passed']} | {row['threshold_0p1']}/4 | "
                     f"{row['threshold_0p5']}/4 | {row['all_J_nonregression']} | {row['all_Pd_guard']} |")
    lines += [
        "", "## 证据", "",
        "固定展开诊断核对队列与统计的机制。C0/C0 对照用于估计计时波动，两项均独立于正式筛选。",
        "墙钟、CPU、内存及停机原因按次保留。正式数据为四个已见开发实例。",
        "",
        "[冻结协议](protocol.json) · [固定展开消融](ablation.json) · [C0/C0 对照](jitter.json) · "
        "[质量门槛](summary.json) · [逐次 CSV](comparison.csv) · "
        "[调度诊断](progress_diagnostics.csv) · [全部运行](runs/)",
        "",
    ]
    (out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")


def analyze(out):
    out = Path(out).resolve()
    protocol = metrics.read_json(out / "protocol.json")
    design = protocol["design"]
    require(set(design["methods"]) == set(METHODS) and tuple(design["instances"]) == INSTANCES,
            "Unexpected formal methods or instances in protocol")
    values = design["decision"]
    require(
        values["minimum_relative_J_improvement"] == progress_analysis.MIN_GAIN
        and values["secondary_relative_J_improvement"] == progress_analysis.SECONDARY_GAIN
        and values["relative_J_nonregression_tolerance"] == progress_analysis.J_TOL
        and values["max_terminal_Pd_drop"] == progress_analysis.MAX_PD_DROP
        and values["minimum_winning_instances"] == 3 and values["minimum_wins_per_region"] == 1,
        "Analyzer quality gates differ from frozen protocol",
    )
    ablation = metrics.read_json(out / "ablation.json")
    jitter = metrics.read_json(out / "jitter.json")
    require(ablation["status"] == jitter["status"] == "passed"
            and ablation["semantic_runs"] == 8 and ablation["timed_runs"] == 24
            and jitter["run_count"] == 12, "Missing prerequisite diagnostics")
    rows, schedules, survival, history = collect(out, protocol)
    summary = summarize(rows)
    summary["diagnostics"] = {
        "ablation_sha256": file_sha(out / "ablation.json"),
        "jitter_sha256": file_sha(out / "jitter.json"),
    }
    for name, records in (
        ("comparison", rows), ("instance_comparison", summary["pairs"]),
        ("progress_diagnostics", schedules), ("survival", survival), ("incumbent_history", history),
    ):
        metrics.write_csv(out / (name + ".csv"), records)
    metrics.write_json(out / "summary.json", summary)
    report(out, summary)
    print(summary["status"], flush=True)
    return summary


def plot_comparison(out):
    import csv

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = Path(out)
    summary = metrics.read_json(out / "summary.json")
    with (out / "survival.csv").open(encoding="utf-8", newline="") as stream:
        curves = {}
        for item in csv.DictReader(stream):
            curves.setdefault(item["run_id"], []).append(
                (int(item["tick"]), 100 * float(item["pd"])))
    groups = {(item["instance"], item["method"]): item for item in summary["method_instances"]}
    labels = ("Lake 3101", "Lake 3201", "Hudson 4101", "Hudson 4201")
    colors = {"C0": "#25364A", "C0_PROGRESS": "#B45E19", "C0_LAZY": "#097A78"}
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), constrained_layout=True)
    locations = range(len(INSTANCES))
    ax = axes[0, 0]
    for offset, name, method in (
        (-0.18, "progress_vs_control", "C0_PROGRESS"), (0.18, "lazy_vs_control", "C0_LAZY"),
    ):
        values = [100 * next(entry["relative_J_gain"] for entry in summary["pairs"]
                             if entry["instance"] == case and entry["pair"] == name)
                  for case in INSTANCES]
        ax.bar([x + offset for x in locations], values, width=0.34, color=colors[method], label=method)
    ax.axhline(0, color="#25364A", linewidth=0.8)
    ax.axhline(0.1, color="#59667A", linestyle=":", label="0.1% improvement")
    ax.set_title("J improvement relative to same-batch C0")
    ax.set_ylabel("Improvement (%)")
    ax.set_xticks(locations, labels)
    ax.legend(frameon=False)

    ax = axes[0, 1]
    for offset, method in zip((-0.24, 0.0, 0.24), METHODS):
        ax.bar([x + offset for x in locations],
               [groups[case, method]["median_rss_mib"] for case in INSTANCES],
               width=0.22, color=colors[method], label=method)
    ax.set_title("Peak memory by method")
    ax.set_ylabel("Median peak RSS (MiB)")
    ax.set_xticks(locations, labels)
    ax.legend(frameon=False)

    for ax, instance, title in zip(axes[1], (H4101, H4201), labels[2:]):
        for method, style in zip(METHODS, ("-", "--", "-.")):
            group = groups[instance, method]
            clock, pd = zip(*sorted(curves[group["run_id"]]))
            ax.plot(clock, pd, color=colors[method], linestyle=style, linewidth=1.8,
                    label=f"{method}  {group['Pd']:.3%}")
        ax.set_title(title + " representative routes")
        ax.set_xlabel("Observation tick")
        ax.set_ylabel("Cumulative Pd (%)")
        ax.legend(frameon=False)
    for ax in axes.flat:
        ax.set_axisbelow(True)
        ax.grid(axis="y", color="#CFD7DB", linewidth=0.6, alpha=0.65)
    fig.savefig(out / "lazy_prefix_comparison.png", dpi=170, facecolor="white")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--plot-only", action="store_true")
    args = parser.parse_args()
    if args.plot_only:
        plot_comparison(args.out)
    else:
        analyze(args.out)


if __name__ == "__main__":
    main()
