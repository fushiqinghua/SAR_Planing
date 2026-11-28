"""Read verified prefix-order run records and derive paired study results."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
import os
from pathlib import Path
from statistics import median

METHODS = ("C0", "C0_PREFIX")
INSTANCES = (
    "lake_h2_d1_s3101", "lake_h2_d2_s3201",
    "hudson_h2_d1_s4101", "hudson_h2_d2_s4201",
)
HISTORICAL_J = {
    "hudson_h2_d1_s4101": 28.448979882240007,
    "hudson_h2_d2_s4201": 58.677655392,
}
REPETITIONS = range(3)
J_GAIN_THRESHOLD = 0.001
J_REL_TOL = 1e-8
PD_MAX_DROP = 0.005
SCORE_ATOL = 1e-8


def read_json(path):
    return json.loads(path.read_bytes())


def write_json(path, data):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8", newline="\n",
    )


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def equal_score(value, reference):
    return math.isclose(value, reference, abs_tol=SCORE_ATOL, rel_tol=0.0)


def first_detected_tick(survival):
    return next((tick for tick, mass in enumerate(survival) if mass < survival[0] - 1e-12), None)


def extract_inner(raw):
    if "phases" not in raw:
        return raw
    inners = [phase["inner"] for phase in raw["phases"] if phase.get("inner") is not None]
    if len(inners) != 1:
        raise ValueError("Expected one single-stage solver run")
    return inners[0]


def run_metrics(task, result, record, run_id):
    if result.get("status") not in ("valid", "ok", "completed"):
        raise ValueError("The run result did not pass independent validation")
    raw = result["raw"]
    inner = extract_inner(raw)
    if inner.get("error") is not None:
        raise ValueError("The solver returned an error")
    if inner.get("state_merge", {}).get("mode", "off") != "off":
        raise ValueError("Formal study records must have merging disabled")
    if task.get("seconds", 30.0) != 30.0:
        raise ValueError("Mismatched 30 s task budget")
    score = result["physical_replay"]
    survival = score["survival"]
    K = len(score["observation_times_s"])
    if len(survival) != K + 1:
        raise ValueError("Observation clock and survival vector disagree")
    if not all(math.isfinite(x) and -SCORE_ATOL <= x <= 1.0 + SCORE_ATOL for x in survival):
        raise ValueError("Invalid remaining probability mass")
    if any(b - a > SCORE_ATOL for a, b in zip(survival, survival[1:])):
        raise ValueError("Remaining probability mass increased")
    J, pd = math.fsum(survival[1:]), 1.0 - survival[-1]
    for summary in (score, result, inner):
        if not equal_score(summary["J"], J) or not equal_score(summary["pd_final"], pd):
            raise ValueError("Solver and independent physical replay disagree")
    history = inner["history"]
    first_change = next((x["elapsed_s"] for x in history if x["source"] != "initial_route"), None)
    stats = inner["stats"]
    diagnostics = inner.get("diagnostics", {})
    prefix_stats = diagnostics.get("prefix_order", {})
    if task["method"] == "C0_PREFIX" and not prefix_stats:
        raise ValueError("Candidate prefix scheduling evidence is missing")
    timings = inner["timings"]
    histogram = {int(tick): int(count) for tick, count in diagnostics["histograms"]["expanded_tick"].items()}
    expanded = int(inner["expanded"])
    if sum(histogram.values()) != expanded or any(count < 0 for count in histogram.values()):
        raise ValueError("Expansion histogram is inconsistent with the solver total")
    early = sum(count for tick, count in histogram.items() if 4 * tick < K)
    middle = sum(count for tick, count in histogram.items() if K <= 4 * tick < 3 * K)
    tail = sum(count for tick, count in histogram.items() if tick >= K - 2)
    first_tick = first_detected_tick(survival)
    peak_rss_bytes = record["peak_rss_bytes"]
    if not isinstance(peak_rss_bytes, int) or peak_rss_bytes <= 0:
        raise ValueError("Missing sampled peak RSS")
    stop_reason = inner["stop_reason"]
    if stop_reason not in ("max_seconds", "frontier_exhausted", "max_open",
                           "max_archive", "max_archive_history"):
        raise ValueError(f"Unexpected formal search stop {stop_reason}")
    return dict(
        run_id=run_id, instance=task["instance"], region=task["instance"].split("_", 1)[0],
        method=task["method"], repetition=task["repetition"], J=float(score["J"]),
        pd_final=float(score["pd_final"]), first_detection_tick=first_tick,
        first_detection_time_s=None if first_tick is None else score["observation_times_s"][first_tick - 1],
        algorithm_wall_s=result["algorithm_wall_s"], algorithm_cpu_s=result.get("algorithm_cpu_s"),
        process_wall_s=record.get("process_wall_s"), peak_rss_bytes=peak_rss_bytes,
        peak_rss_mib=peak_rss_bytes / 2**20, expanded=expanded,
        generated=int(inner["generated"]), peak_open=inner.get("peak_open"),
        end_open=inner.get("open_count"), terminal_candidates=stats["terminal_candidates"],
        completion_calls=stats.get("completion_calls"), guide_s=timings.get("guide_s"),
        transition_s=timings.get("transition_s"), tail_expanded=tail,
        tail_expanded_fraction=tail / expanded if expanded else 0.0,
        early_unique_prefixes=early, mid_unique_prefixes=middle,
        global_pops=prefix_stats.get("global_pops"),
        reserved_early_pops=prefix_stats.get("reserved_early_pops"),
        reserved_middle_pops=prefix_stats.get("reserved_middle_pops"),
        empty_band_fallback_pops=prefix_stats.get("empty_band_fallback_pops"),
        first_search_terminal_s=diagnostics.get("first_search_terminal_generated_s"),
        first_improvement_s=first_change, best_elapsed_s=inner.get("best_elapsed_s"),
        incumbent_source=history[-1]["source"] if history else None,
        stop_reason=stop_reason, timeout=stop_reason == "max_seconds",
        budget_ended=stop_reason != "frontier_exhausted",
        independent_audit_s=result.get("independent_audit_s"),
    )


def collect(directory):
    rows, survival_rows, history_rows = [], [], []
    shared_inputs = {}
    for folder in sorted(directory.iterdir()):
        if not folder.is_dir() or not (folder / "task.json").is_file():
            raise ValueError(f"Unregistered run directory entry {folder.name}")
        task = read_json(folder / "task.json")
        if task.get("method") not in METHODS:
            raise ValueError(f"Unknown formal method in {folder.name}")
        record = read_json(folder / "record.json")
        result_bytes = (folder / "result.json").read_bytes()
        payload = json.loads(result_bytes)
        if (record["status"] != "completed" or record["returncode"] != 0
                or record.get("watchdog") is not None or record.get("verification_error") is not None
                or record["task"] != task or payload["task"] != task
                or hashlib.sha256(result_bytes).hexdigest() != record["result_sha256"]):
            raise ValueError(f"Invalid or altered run {folder.name}")
        result = payload["result"]
        row = run_metrics(task, result, record, folder.name)
        input_info = result["inputs"]
        initial_score = extract_inner(result["raw"])["initial_score"]
        identity = (input_info["manifest_sha256"], input_info["particle_sha256"],
                    tuple(initial_score["waypoints"]))
        if shared_inputs.setdefault(task["instance"], identity) != identity:
            raise ValueError(f"Frozen inputs or common initial route changed in {folder.name}")
        rows.append(row)
        common = {key: row[key] for key in ("run_id", "instance", "region", "method", "repetition")}
        score = result["physical_replay"]
        for tick, (time_s, mass) in enumerate(zip([0.0] + score["observation_times_s"], score["survival"])):
            survival_rows.append(dict(common, tick=tick, time_s=time_s, remaining_mass=mass, pd=1.0 - mass))
        for item in extract_inner(result["raw"])["history"]:
            history_rows.append(dict(common, elapsed_s=item["elapsed_s"], source=item["source"],
                                     J=item["J"], pd_final=item["pd_final"]))
    expected = Counter((i, m, r) for i in INSTANCES for m in METHODS for r in REPETITIONS)
    actual = Counter((row["instance"], row["method"], row["repetition"]) for row in rows)
    if actual != expected:
        raise ValueError(f"Expected all 24 paired runs. Missing {list(expected - actual)}, extra {list(actual - expected)}")
    return rows, survival_rows, history_rows


def optional_median(rows, key):
    values = [row[key] for row in rows if row[key] is not None]
    return median(values) if values else None


def compare(rows):
    comparisons = []
    for instance in INSTANCES:
        baseline, candidate = (
            sorted((x for x in rows if x["instance"] == instance and x["method"] == m),
                   key=lambda row: (row["J"], row["repetition"]))
            for m in METHODS
        )
        control, variant = baseline[1], candidate[1]
        J0, J1 = control["J"], variant["J"]
        relative = (J0 - J1) / J0 if J0 > 0 else 0.0 if J1 == 0 else -1.0
        delta_pd = variant["pd_final"] - control["pd_final"]
        historical = HISTORICAL_J.get(instance)
        comparisons.append(dict(
            instance=instance, region=control["region"],
            C0_run_id=control["run_id"], C0_PREFIX_run_id=variant["run_id"],
            C0_J=J0, C0_PREFIX_J=J1, relative_J_gain=relative,
            C0_pd=control["pd_final"], C0_PREFIX_pd=variant["pd_final"], delta_pd=delta_pd,
            J_threshold_met=relative >= J_GAIN_THRESHOLD,
            J_guard_passed=relative >= -J_REL_TOL, Pd_guard_passed=delta_pd >= -PD_MAX_DROP,
            C0_median_time_s=optional_median(baseline, "algorithm_wall_s"),
            C0_PREFIX_median_time_s=optional_median(candidate, "algorithm_wall_s"),
            C0_median_rss_mib=optional_median(baseline, "peak_rss_mib"),
            C0_PREFIX_median_rss_mib=optional_median(candidate, "peak_rss_mib"),
            C0_median_expanded=optional_median(baseline, "expanded"),
            C0_PREFIX_median_expanded=optional_median(candidate, "expanded"),
            C0_median_tail_fraction=optional_median(baseline, "tail_expanded_fraction"),
            C0_PREFIX_median_tail_fraction=optional_median(candidate, "tail_expanded_fraction"),
            C0_median_early_unique_prefixes=optional_median(baseline, "early_unique_prefixes"),
            C0_PREFIX_median_early_unique_prefixes=optional_median(candidate, "early_unique_prefixes"),
            C0_median_mid_unique_prefixes=optional_median(baseline, "mid_unique_prefixes"),
            C0_PREFIX_median_mid_unique_prefixes=optional_median(candidate, "mid_unique_prefixes"),
            C0_median_best_time_s=optional_median(baseline, "best_elapsed_s"),
            C0_PREFIX_median_best_time_s=optional_median(candidate, "best_elapsed_s"),
            C0_first_detection_tick=control["first_detection_tick"],
            C0_PREFIX_first_detection_tick=variant["first_detection_tick"],
            historical_best_J=historical,
            relative_gain_vs_historical=None if historical is None else (historical - J1) / historical,
            exceeds_historical=None if historical is None else (historical - J1) / historical > J_REL_TOL,
            historical_threshold_met=None if historical is None else (historical - J1) / historical >= J_GAIN_THRESHOLD,
        ))
    return comparisons


def gate(rows, comparisons):
    regional_wins = {region: 0 for region in ("lake", "hudson")}
    threshold_wins = [row for row in comparisons if row["J_threshold_met"]]
    for row in threshold_wins:
        regional_wins[row["region"]] += 1
    protection_j = all(row["J_guard_passed"] for row in comparisons)
    protection_pd = all(row["Pd_guard_passed"] for row in comparisons)
    passed = len(threshold_wins) >= 3 and all(regional_wins.values()) and protection_j and protection_pd
    return dict(
        status="prefix_order_development_screen_passed" if passed else "prefix_order_development_screen_not_passed",
        complete=True, expected_runs=24, valid_runs=len(rows), screen_passed=passed,
        relative_J_gain_min=J_GAIN_THRESHOLD, min_instances=3, min_instances_per_region=1,
        relative_J_guard_tolerance=J_REL_TOL, max_pd_drop=PD_MAX_DROP,
        J_threshold_wins=len(threshold_wins), regional_wins=regional_wins,
        J_guard_passed=protection_j, Pd_guard_passed=protection_pd,
        pairs=comparisons, optimality_certified=False,
        scope="four seen development instances, real frozen trajectories, three timing repetitions",
    )


def link(out, path, label):
    if path is None:
        return None
    relative = Path(os.path.relpath(path.resolve(), out.resolve())).as_posix()
    return f"[{label}](<{relative}>)"


def number(value, precision=3):
    return "—" if value is None else f"{value:.{precision}f}"


def report(out, rows, data, tests, diagnostics, protocol):
    result = [
        "# 早中段前缀取点顺序实验",
        "",
        f"四个已见开发实例共 {data['valid_runs']} 次有效运行。判定为 `{data['status']}`。",
        "两组共用冻结初始路线、历史真实 forcing 的粒子档案、原目标和独立物理重放。"
        "合并关闭，每次使用 30 秒预算。早中段前缀取点顺序是本轮候选差异。",
        "每实例每方法按 (J, 重复序号) 取中位代表运行。Pd 来自同一条代表路径。",
        "",
    ]
    evidence = [link(out, path, title) for path, title in (
        (protocol, "冻结协议"), (tests, "toy/Oracle 与测试"), (diagnostics, "等展开数诊断"),
    ) if path is not None]
    if evidence:
        result += [" · ".join(evidence), ""]
    result += [
        "## J 与 Pd",
        "",
        "| 实例 | C0 J | 候选 J | J 改善 | C0 Pd | 候选 Pd | ΔPd 百分点 | 代表运行 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for pair in data["pairs"]:
        display = (
            f"[C0](runs/{pair['C0_run_id']}/result.json) · "
            f"[候选](runs/{pair['C0_PREFIX_run_id']}/result.json)"
        )
        result.append(
            f"| {pair['instance']} | {pair['C0_J']:.9f} | {pair['C0_PREFIX_J']:.9f} | "
            f"{100*pair['relative_J_gain']:+.4f}% | {100*pair['C0_pd']:.4f}% | "
            f"{100*pair['C0_PREFIX_pd']:.4f}% | {100*pair['delta_pd']:+.4f} | {display} |"
        )
    result += [
        "",
        "采用门槛要求至少 3/4 例相对 J 改善 0.1%，Lake 和 Hudson 各至少一例。"
        "任一例 J 相对退化不得超过 1e-8，终点 Pd 降幅不得超过 0.5 个百分点。",
        f"J 改善达标 {data['J_threshold_wins']}/4，"
        f"Lake {data['regional_wins']['lake']}/2，Hudson {data['regional_wins']['hudson']}/2。"
        f"J 护栏{'通过' if data['J_guard_passed'] else '未通过'}，"
        f"Pd 护栏{'通过' if data['Pd_guard_passed'] else '未通过'}。",
        "",
        "## Hudson 历史可行路线",
        "",
        "| 实例 | 历史最好 J | 本轮候选 J | 相对改善 | 突破历史最好 | 改善达 0.1% |",
        "| --- | ---: | ---: | ---: | --- | --- |",
    ]
    for pair in data["pairs"]:
        if pair["historical_best_J"] is not None:
            result.append(
                f"| {pair['instance']} | {pair['historical_best_J']:.9f} | "
                f"{pair['C0_PREFIX_J']:.9f} | {100*pair['relative_gain_vs_historical']:+.4f}% | "
                f"{'是' if pair['exceeds_historical'] else '否'} | "
                f"{'是' if pair['historical_threshold_met'] else '否'} |"
            )
    result += [
        "",
        "历史路线只作事后参照。4201 的历史值来自上轮滚动组。两组求解均使用本轮冻结的共同初始路线。",
        "",
        "## 搜索行为与资源",
        "",
        "表内计时、内存与工作量按三次运行分别取中位数。首探测使用 J 中位代表路线。",
        "关闭合并后，展开树中的每条合法航点前缀对应一次展开。"
        "早段取 4×tick<K，中段取 K≤4×tick<3K。尾两 tick 单列。",
        "",
        "| 实例 | 方法 | 墙钟秒 | 扩展数 | RSS MiB | 尾两 tick 占比 | 早段唯一前缀 | "
        "中段唯一前缀 | 首探测 tick | 找到最佳解秒 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for pair in data["pairs"]:
        for method in METHODS:
            tail_fraction = pair[f"{method}_median_tail_fraction"]
            result.append(
                f"| {pair['instance']} | {method} | {number(pair[f'{method}_median_time_s'])} | "
                f"{number(pair[f'{method}_median_expanded'], 0)} | {number(pair[f'{method}_median_rss_mib'], 1)} | "
                f"{number(100*tail_fraction if tail_fraction is not None else None, 1)}% | "
                f"{number(pair[f'{method}_median_early_unique_prefixes'], 0)} | "
                f"{number(pair[f'{method}_median_mid_unique_prefixes'], 0)} | "
                f"{number(pair[f'{method}_first_detection_tick'], 0)} | {number(pair[f'{method}_median_best_time_s'])} |"
            )
    stops = Counter((row["method"], row["stop_reason"]) for row in rows)
    result += [
        "",
        "搜索停止原因 " + "，".join(f"{method} {reason} ×{count}" for (method, reason), count in sorted(stops.items())) + "。",
        "预算内返回的路线均按原评分器独立重放。该排序实验不产生全局或 ε 界。"
        "四例与重复的用途是开发筛选及计时复核。",
        "",
        "[逐次指标](comparison.csv) · [实例对照](instance_comparison.csv) · "
        "[剩余质量曲线](survival.csv) · [incumbent 记录](incumbent_history.csv) · "
        "[判定 JSON](gate.json) · [逐次原始记录与 stdout/stderr](runs)",
        "",
    ]
    (out / "REPORT.md").write_text("\n".join(result), encoding="utf-8", newline="\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--tests", type=Path)
    parser.add_argument("--diagnostics", type=Path)
    parser.add_argument("--protocol", type=Path)
    args = parser.parse_args()
    try:
        rows, curves, history = collect(args.out / "runs")
        comparisons = compare(rows)
        data = gate(rows, comparisons)
    except (OSError, KeyError, TypeError, ValueError) as error:
        write_json(args.out / "gate.json", dict(status="blocked", complete=False, reason=str(error)))
        raise SystemExit(f"blocked: {error}") from error
    write_csv(args.out / "comparison.csv", rows)
    write_csv(args.out / "instance_comparison.csv", comparisons)
    write_csv(args.out / "survival.csv", curves)
    write_csv(args.out / "incumbent_history.csv", history)
    write_json(args.out / "gate.json", data)
    report(args.out, rows, data, args.tests, args.diagnostics, args.protocol)
    print(data["status"])


if __name__ == "__main__":
    main()

