"""Post-hoc descriptive J/Pd audit of accepted paths; never selects a new method.

Execute only after this folder's 36-run benchmark passes. Frozen source and
results are read-only; all new artifacts go into a fresh incumbent_analysis/.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter
import traceback

HERE = Path(__file__).resolve().parent
PROJECT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT / "scripts"))
sys.path.insert(0, str(PROJECT / "src"))

from asar_repro.objective import score_path
from stdc_validation_guards import (
    ROOT, ATOL, PARTICLE_SHA, PROTOCOL_SHA, check_score, digest, load_real,
    read, require, save,
)

VARIANTS = ("paper_baseline", "anytime_zero", "anytime_mass", "anytime_stdc")
WEIGHTS = (1.04, 1.1, 1.0)
BEST_J = 17.29389415456
COLORS = dict(zip(VARIANTS, ("#0072B2", "#999999", "#E69F00", "#009E73")))


def check_sources(expected):
    current = {p.relative_to(ROOT).as_posix(): digest(p)
               for top in ("src", "tests", "scripts") for p in (ROOT / top).rglob("*.py")}
    require(current == expected, "frozen validated source set/content changed")


def check_manifest(folder):
    manifest = read(folder / "artifact_manifest.json")
    require(bool(manifest.get("files")), "benchmark artifact manifest is empty")
    for item in manifest["files"]:
        path = (folder / item["path"]).resolve()
        require(path.is_relative_to(folder), "manifest path outside benchmark")
        require(path.is_file() and path.stat().st_size == item["bytes"]
                and digest(path) == item["sha256"], "benchmark artifact mismatch: " + item["path"])


def path_identity(path):
    return hashlib.sha256(json.dumps(list(path), separators=(",", ":")).encode("ascii")).hexdigest()


def csv_save(path, rows):
    require(bool(rows), "no candidate rows to export")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict))
                             else value for key, value in row.items()})


def nondominated(rows):
    """Numerical Pareto set within ONE method, weight and repeat only."""
    return [row for row in rows if not any(
        other["J"] <= row["J"] + ATOL and other["Pd"] >= row["Pd"] - ATOL
        and (other["J"] < row["J"] - ATOL or other["Pd"] > row["Pd"] + ATOL)
        for other in rows)]


def figures(output, candidates, references, primary):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    selected = [r for r in candidates if r["guide_weight"] == 1.04 and r["repeat"] == 0]
    fig, axes = plt.subplots(1, 2, figsize=(14, 6), constrained_layout=True)
    for ax in axes:
        for variant in VARIANTS:
            group = [r for r in selected if r["variant"] == variant]
            archived = [r for r in group if not r["is_returned_path"]]
            returned = [r for r in group if r["is_returned_path"]]
            if archived:
                ax.scatter([r["J"] for r in archived], [r["Pd"] for r in archived],
                           s=28, alpha=.65, color=COLORS[variant], label=variant + " archived")
            ax.scatter([r["J"] for r in returned], [r["Pd"] for r in returned],
                       s=130, marker="*", edgecolors="black", linewidths=.5,
                       color=COLORS[variant], label=variant + " RETURNED", zorder=5)
            frontier = sorted(nondominated(group), key=lambda r: r["J"])
            if len(frontier) > 1:
                ax.plot([r["J"] for r in frontier], [r["Pd"] for r in frontier],
                        "--", color=COLORS[variant], alpha=.6, lw=.8)
        for key, marker, color, label in (
            ("best_J_baseline", "D", "#000000", "Best-J baseline reference"),
            ("max_Pd_baseline", "^", "#7B3294", "Max-Pd baseline reference")):
            ref = references[key]
            ax.scatter(ref["J"], ref["Pd"], marker=marker, s=70,
                       facecolors="none", edgecolors=color, linewidths=1.4, label=label, zorder=6)
        ax.axvline(references["best_J_baseline"]["J"], color="black", alpha=.25, lw=.8)
        ax.axhline(references["best_J_baseline"]["Pd"], color="black", alpha=.25, lw=.8)
        ax.axhline(references["max_Pd_baseline"]["Pd"], color="#7B3294", alpha=.25, lw=.8)
        ax.set(xlabel="J (lower is better)", ylabel="Pd(T) (higher is better)")
        ax.grid(alpha=.2)
    axes[0].set_title("All archived / returned points in the primary runs")
    axes[0].legend(fontsize=6.5, loc="lower left")
    near = [r for r in selected if r["J"] <= BEST_J + .2]
    points = near + list(references.values())
    xs, ys = [r["J"] for r in points], [r["Pd"] for r in points]
    dx, dy = max(max(xs)-min(xs), .01), max(max(ys)-min(ys), 1e-5)
    axes[1].set_xlim(min(xs)-dx*.12, max(xs)+dx*.12)
    axes[1].set_ylim(min(ys)-dy*.18, max(ys)+dy*.18)
    axes[1].set_title("Zoom near the best baseline; dashed: per-run Pareto set")
    returned = primary["returned"]
    axes[1].annotate("STDC returned: minimum J", (returned["J"], returned["Pd"]),
                     xytext=(5, -26), textcoords="offset points", fontsize=8,
                     arrowprops=dict(arrowstyle="->", lw=.7))
    filtered = primary["posthoc_min_J_with_Pd_at_least_best_J_baseline"]
    if filtered is not None:
        axes[1].scatter(filtered["J"], filtered["Pd"], s=110, facecolors="none",
                        edgecolors="#D55E00", lw=1.5, zorder=7)
        axes[1].annotate("Archived only: post-hoc descriptive filter",
                         (filtered["J"], filtered["Pd"]), xytext=(5, 18),
                         textcoords="offset points", fontsize=8,
                         arrowprops=dict(arrowstyle="->", lw=.7))
    fig.suptitle("Frozen real Lake Ontario; guide weight 1.04, repeat 0 ONLY\n"
                 "J objective unchanged; no pooled multi-run budget claim; all routes uncertified", fontsize=11)
    fig.savefig(output / "pareto_tradeoffs.png", dpi=190)
    plt.close(fig)


def report(output, primary, per_run, references, unique_count, candidate_count):
    returned = primary["returned"]
    selected = primary["posthoc_min_J_with_Pd_at_least_best_J_baseline"]
    best = references["best_J_baseline"]
    maxpd = references["max_Pd_baseline"]
    lines = ["# 已接受候选的 J/Pd 取舍（事后描述性分析）", "",
        f"36 次基准运行已通过；对 {unique_count} 条唯一归档/参考路径重新调用冻结评分器，"
        f"保留 {candidate_count} 条带运行归属的候选记录。所有路径均合法，未修改搜索目标、返回路径或原结果。", "",
        "## 主要预设：STDC、guide=1.04、repeat=0", "",
        "|记录|J ↓|Pd ↑|生成时累计展开|生成时方法秒数|角色|",
        "|---|---:|---:|---:|---:|---|",
        f"|最好 J baseline|{best['J']:.11f}|{best['Pd']:.11f}|—|—|参考返回路径|",
        f"|baseline 最大 Pd 设置|{maxpd['J']:.11f}|{maxpd['Pd']:.11f}|—|—|另一权重的参考返回路径|",
        f"|STDC 最终返回|{returned['J']:.11f}|{returned['Pd']:.11f}|{returned['expanded']}|"
        f"{returned['elapsed_s']:.6f}|按原始最小 J 返回|",
    ]
    if selected is not None:
        lines.append(f"|同次运行内的事后筛选候选|{selected['J']:.11f}|{selected['Pd']:.11f}|"
                     f"{selected['expanded']}|{selected['elapsed_s']:.6f}|"
                     f"{'也是返回路径' if selected['is_returned_path'] else '仅为归档候选，未返回'}|")
    lines += ["", f"最终返回相对最好 J baseline：ΔJ={returned['J']-best['J']:+.11f}，"
              f"ΔPd={returned['Pd']-best['Pd']:+.11f}"
              f"（{100*(returned['Pd']-best['Pd']):+.9f} 个百分点）。",
              "原算法只最小化 J；继续降低 J 时允许 Pd 出现微小下降。这是两个指标的取舍，不能把归档候选的 Pd 冒充为最终返回指标。", ""]
    if selected is not None:
        lines += [f"该次运行确实曾生成 {primary['joint_improvement_count']} 条同时满足"
                  " `J < 最好 baseline J` 且 `Pd ≥ 该 baseline Pd` 的已接受候选。",
                  "表中的候选是在这一个已完成预算记录内，事后按 Pd 门槛筛选后 J 最小的路径。"
                  "这是描述性分析，未实现或验证新的受约束规划方法，也未改变正式返回策略。"]
    else:
        lines += ["该次运行未发现同时满足上述 J/Pd 门槛的归档候选；不能宣称同时改善。"]
    primary_max = primary["joint_improvement_over_max_baseline_Pd_count"]
    lines += ["", f"进一步用 baseline 各设置中的最大 Pd 作门槛：该主要 STDC 运行内合格候选 {primary_max} 条。",
              "这个更严格门槛对应另一条 baseline 返回路径；它不是最好 J 路径的 Pd。", "",
              "## 分运行核对（禁止跨预算合并结论）", "",
              "|方法|guide|重复|归档记录数|J 改善且 Pd≥最好J baseline|J 改善且 Pd≥最大baseline Pd|返回是否同时改善最好J baseline|",
              "|---|---:|---:|---:|---:|---:|---|"]
    for row in per_run:
        lines.append(f"|{row['variant']}|{row['guide_weight']:g}|{row['repeat']}|{row['candidate_records']}|"
                     f"{row['joint_improvement_count']}|{row['joint_improvement_over_max_baseline_Pd_count']}|"
                     f"{'是' if row['returned_joint_improvement'] else '否'}|")
    lines += ["", "每条记录保留 variant、guide、repeat、展开数、elapsed、来源和完整路径。"
              "重复使用同一冻结粒子输入，重复不是独立数据集；不跨权重/重复挑选路径组成免费额外搜索。",
              f"所有比较使用数值容差 {ATOL:g}：J 严格小于基准减容差，Pd 不低于基准减容差。",
              "本分析仅检查搜索过程中已接受并归档的 incumbent，不能推断所有被评估候选的 Pareto 前沿。"
              "图中虚线仅连接各自单次运行归档集内的非支配点，不是全问题 Pareto 前沿。",
              "真实输入经过 SHA-256 校验，保留 all-water 离散近似标签；未运行 OpenDrift，完整路线无 ε 认证。", "",
              "![主要运行 J/Pd 取舍](pareto_tradeoffs.png)", "",
              "数据：`candidate_tradeoffs.json/csv`、`per_run_summary.csv`、`unique_path_replays.json`、"
              "`input_gate.json`、`artifact_manifest.json`。", ""]
    (output / "tradeoffs.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    require(ROOT == PROJECT, "project root mismatch")
    benchmark = HERE / "benchmark"
    output = HERE / "incumbent_analysis"
    require(not output.exists(), "refusing to overwrite incumbent_analysis")
    require(read(benchmark / "summary.json").get("status") == "passed",
            "blocked: wait until the benchmark has passed before running analysis")
    output.mkdir()
    started = perf_counter()
    summary = dict(status="running", method_changed=False, posthoc_descriptive_only=True)
    try:
        data = read(benchmark / "results.json")
        require(data["status"] == "passed" and len(data["rows"]) == 36,
                "all 36 benchmark results must pass")
        check_manifest(benchmark)
        validation = read(HERE / "validation_summary.json")
        require(validation["status"] == "passed" and not validation["not_run"], "prior validation failed")
        check_sources(validation["source_sha256"])
        protocol, grid, cfg, _, times, raw = load_real()
        runs = data["rows"]
        expected = {(variant, weight, repeat) for variant in VARIANTS for weight in WEIGHTS for repeat in range(3)}
        require({(r["variant"], r["guide_weight"], r["repeat"]) for r in runs} == expected,
                "missing, duplicate or unexpected benchmark identity")
        recorded_ref = read(benchmark / "input_gate.json")["reference"]
        ref_source = Path(recorded_ref["source"])
        require(digest(ref_source) == recorded_ref["sha256"], "historical baseline reference changed")
        baseline_rows = [r for r in runs if r["variant"] == "paper_baseline"]
        best_row = min(baseline_rows, key=lambda r: (r["J"], r["repeat"]))
        maxpd_row = max(baseline_rows, key=lambda r: (r["Pd_T"], -r["repeat"]))
        require(abs(best_row["J"] - BEST_J) <= ATOL, "best-J reference mismatch")
        require(abs(best_row["Pd_T"] - recorded_ref["best_J_Pd"]) <= ATOL
                and abs(maxpd_row["Pd_T"] - recorded_ref["best_Pd"]) <= ATOL,
                "baseline Pd reference mismatch")
        references = {
            "best_J_baseline": dict(J=best_row["J"], Pd=best_row["Pd_T"],
                                    guide_weight=best_row["guide_weight"], path=best_row["path"]),
            "max_Pd_baseline": dict(J=maxpd_row["J"], Pd=maxpd_row["Pd_T"],
                                   guide_weight=maxpd_row["guide_weight"], path=maxpd_row["path"]),
        }
        evidence = dict(status="passed", forcing_kind="historical_real",
            experiment_label=protocol["experiment_label"], particle_sha256=PARTICLE_SHA,
            protocol_sha256=PROTOCOL_SHA, verified_forcing=raw, time_utc=[str(t)+"Z" for t in times],
            benchmark_results_sha256=digest(benchmark / "results.json"),
            benchmark_manifest_sha256=digest(benchmark / "artifact_manifest.json"),
            baseline_reference_sha256=recorded_ref["sha256"], source_sha256=validation["source_sha256"],
            analysis_script_sha256=digest(Path(__file__)), command=[sys.executable, *sys.argv],
            objective="unchanged J=sum(M[1:T+1]); no Pd constraint in the method", references=references)
        save(output / "input_gate.json", evidence)
        cache, unique_rows, candidates = {}, [], []

        def replay(path):
            key = tuple(path)
            if key not in cache:
                tic = perf_counter()
                score = score_path(grid, key, **cfg)
                check_score(score)
                cached = dict(path=list(key), path_sha256=path_identity(key), J=score.J,
                              Pd=score.pd_final, legal=True, replay_wall_s=perf_counter()-tic)
                cache[key] = cached
                unique_rows.append(cached)
            return cache[key]

        for row in runs:
            require(row["forcing_kind"] == "historical_real" and not row["theory_certified"]
                    and row["legal"], "invalid source or certification label")
            run_id = f"{row['variant']}_w{row['guide_weight']}_rep{row['repeat']}"
            worker_file = benchmark / run_id / "result.json"
            require(read(worker_file) == row, "aggregate differs from immutable worker result")
            final = replay(row["path"])
            require(abs(final["J"] - row["J"]) <= ATOL and abs(final["Pd"] - row["Pd_T"]) <= ATOL,
                    "returned path replay mismatch")
            history = row.get("incumbent_history")
            is_anytime = row["variant"] != "paper_baseline"
            if is_anytime:
                require(bool(history) and history[0]["path"] == protocol["initial_path"]
                        and history[-1]["path"] == row["path"], "incomplete incumbent history")
            else:
                history = [dict(path=row["path"], J=row["J"], Pd=row["Pd_T"],
                    expanded=row["expanded"], generated=row["generated"], elapsed_s=row["search_wall_s"],
                    source=row["incumbent_source"])]
            previous_J, previous_time = float("inf"), 0.0
            for index, event in enumerate(history):
                check = replay(event["path"])
                require(abs(check["J"] - event["J"]) <= ATOL and abs(check["Pd"] - event["Pd"]) <= ATOL,
                        "accepted history replay mismatch")
                require(check["J"] < previous_J - ATOL, "history is not strictly improving J")
                require(previous_time <= event["elapsed_s"] <= row["search_wall_s"], "history clock mismatch")
                require(0 <= event["expanded"] <= row["expanded"]
                        and 0 <= event["generated"] <= row["generated"], "history effort mismatch")
                previous_J, previous_time = check["J"], event["elapsed_s"]
                returned = tuple(event["path"]) == tuple(row["path"])
                j_win = check["J"] < references["best_J_baseline"]["J"] - ATOL
                candidates.append(dict(
                    run_id=run_id, variant=row["variant"], guide_weight=row["guide_weight"], repeat=row["repeat"],
                    history_index=index if is_anytime else None,
                    source=event["source"], source_worker=str(worker_file.relative_to(ROOT)),
                    source_worker_sha256=digest(worker_file), forcing_kind="historical_real",
                    particle_sha256=PARTICLE_SHA, path_sha256=check["path_sha256"], path=check["path"],
                    J=check["J"], Pd=check["Pd"], replay_error_J=abs(check["J"]-event["J"]),
                    replay_error_Pd=abs(check["Pd"]-event["Pd"]), legal=True,
                    expanded=event["expanded"], generated=event["generated"], elapsed_s=event["elapsed_s"],
                    effort_scope="observed accepted incumbent event" if is_anytime else "returned endpoint; discovery time unavailable",
                    is_returned_path=returned, is_initial_PT=tuple(event["path"]) == tuple(protocol["initial_path"]),
                    role="returned_path" if returned else "archived_accepted_candidate",
                    search_status=row["status"], stop_reason=row["stop_reason"],
                    delta_J_vs_best_baseline=check["J"]-references["best_J_baseline"]["J"],
                    delta_Pd_vs_best_J_baseline=check["Pd"]-references["best_J_baseline"]["Pd"],
                    delta_Pd_vs_max_baseline=check["Pd"]-references["max_Pd_baseline"]["Pd"],
                    beats_best_J=j_win,
                    joint_improvement=j_win and check["Pd"] >= references["best_J_baseline"]["Pd"]-ATOL,
                    joint_improvement_over_max_baseline_Pd=j_win and check["Pd"] >= references["max_Pd_baseline"]["Pd"]-ATOL,
                    pareto_nondominated_within_run=False, theory_certified=False))
        per_run, primary = [], None
        for row in runs:
            group = [c for c in candidates if (c["variant"], c["guide_weight"], c["repeat"])
                     == (row["variant"], row["guide_weight"], row["repeat"])]
            for candidate in nondominated(group):
                candidate["pareto_nondominated_within_run"] = True
            returned = next(c for c in group if c["is_returned_path"])
            eligible = [c for c in group if c["joint_improvement"]]
            maxpd_eligible = [c for c in group if c["joint_improvement_over_max_baseline_Pd"]]
            selected = min(eligible, key=lambda c: c["J"]) if eligible else None
            item = dict(variant=row["variant"], guide_weight=row["guide_weight"], repeat=row["repeat"],
                candidate_records=len(group), unique_paths=len({c["path_sha256"] for c in group}),
                joint_improvement_count=len(eligible), joint_improvement_over_max_baseline_Pd_count=len(maxpd_eligible),
                returned_J=returned["J"], returned_Pd=returned["Pd"], returned_joint_improvement=returned["joint_improvement"],
                posthoc_min_J_joint_candidate_J=None if selected is None else selected["J"],
                posthoc_min_J_joint_candidate_Pd=None if selected is None else selected["Pd"],
                posthoc_min_J_joint_candidate_returned=None if selected is None else selected["is_returned_path"],
                posthoc_selection_is_a_method=False)
            per_run.append(item)
            if (row["variant"], row["guide_weight"], row["repeat"]) == ("anytime_stdc", 1.04, 0):
                primary = dict(returned=returned, joint_improvement_count=len(eligible),
                    joint_improvement_over_max_baseline_Pd_count=len(maxpd_eligible),
                    joint_candidates=eligible, first_joint_candidate=eligible[0] if eligible else None,
                    posthoc_min_J_with_Pd_at_least_best_J_baseline=selected,
                    posthoc_filter="within this single run only: J < baseline_J - atol and Pd >= baseline_Pd - atol; choose minimum J",
                    selection_is_a_new_method=False)
        require(primary is not None, "missing primary STDC run")
        require(abs(primary["returned"]["J"] - min(c["J"] for c in candidates
                if (c["variant"], c["guide_weight"], c["repeat"]) == ("anytime_stdc", 1.04, 0))) <= ATOL,
                "primary returned path is not the minimum-J accepted path")
        save(output / "unique_path_replays.json", dict(unique_paths=len(unique_rows), rows=unique_rows))
        save(output / "candidate_tradeoffs.json", dict(status="passed", atol=ATOL, references=references,
            primary=primary, runs=per_run, candidates=candidates, unique_paths=len(unique_rows),
            interpretation="post-hoc descriptive only; no objective or returned result changes; no pooling for a free-budget method"))
        csv_save(output / "candidate_tradeoffs.csv", candidates)
        csv_save(output / "per_run_summary.csv", per_run)
        figures(output, candidates, references, primary)
        report(output, primary, per_run, references, len(unique_rows), len(candidates))
        check_sources(validation["source_sha256"])
        require(digest(benchmark / "results.json") == evidence["benchmark_results_sha256"]
                and digest(ref_source) == recorded_ref["sha256"], "source result changed during analysis")
        summary.update(status="passed", benchmark_runs=36, candidate_records=len(candidates),
            unique_replayed_paths=len(unique_rows), primary_returned_J=primary["returned"]["J"],
            primary_returned_Pd=primary["returned"]["Pd"],
            primary_joint_candidates=primary["joint_improvement_count"],
            primary_joint_over_max_baseline_Pd=primary["joint_improvement_over_max_baseline_Pd_count"],
            source_files_checked=len(validation["source_sha256"]),
            source_preservation="all validated source hashes unchanged; benchmark and baseline results unchanged")
        print(json.dumps(summary, ensure_ascii=False, allow_nan=False), flush=True)
    except Exception as exc:
        summary.update(status="blocked", error=str(exc), traceback=traceback.format_exc())
        raise
    finally:
        summary["analysis_wall_s"] = perf_counter()-started
        save(output / "summary.json", summary)
        save(output / "artifact_manifest.json", dict(files=[
            dict(path=p.relative_to(output).as_posix(), bytes=p.stat().st_size, sha256=digest(p))
            for p in sorted(output.rglob("*")) if p.is_file() and p.name != "artifact_manifest.json"]))


if __name__ == "__main__":
    main()
