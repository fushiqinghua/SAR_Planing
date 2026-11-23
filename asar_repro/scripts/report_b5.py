"""Summarize B5 measurements without mixing profiled timings into the budget scan."""

import argparse
from collections import Counter
import csv
from pathlib import Path

from matplotlib.figure import Figure
import numpy as np

from benchmark_b5 import ROOT, read_json, save_json
from asar_repro.scenarios import digest
from asar_repro.search_reporting import REQUIRED_FIELDS


def export_csv(path, rows):
    keys = REQUIRED_FIELDS + sorted(set().union(*(r.keys() for r in rows)) - set(REQUIRED_FIELDS))
    with path.open("w", encoding="utf-8", newline="") as f:
        import json
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False, allow_nan=False)
                             if isinstance(v, (dict, list)) or v is None else v for k, v in row.items()})


def comparison_rows(pilot, scan):
    pairs = []
    same_fields = ("heuristic", "epsilon", "max_expansions", "max_seconds", "max_open")
    for before in pilot:
        if before["diagnostics"] is not None:
            continue
        after = next(r for r in scan if all(r[k] == before[k] for k in same_fields))
        exact = all(before[k] == after[k] for k in (
            "path", "J", "Pd_T", "M_T", "search_status", "stop_reason", "expanded", "generated", "pruned", "peak_open"))
        if not exact:
            raise AssertionError("unchanged-core repeat differs")
        pairs.append(dict(heuristic=before["heuristic"], epsilon=before["epsilon"],
                          max_expansions=before["max_expansions"], before_s=before["planner_wall_s"],
                          after_s=after["planner_wall_s"], before_peak_MiB=before["peak_process_MiB"],
                          after_peak_MiB=after["peak_process_MiB"], identical_path_score_counters=exact,
                          implementation_changed=False, interpretation="unprofiled repeat; not an optimization speedup"))
    return pairs


def render(scan, output):
    fig = Figure(figsize=(12, 8), layout="constrained")
    axes = fig.subplots(2, 2)
    labels = [("J", "Returned J (steps)"), ("planner_wall_s", "Search time (s)"),
              ("expanded", "Expanded nodes"), ("peak_process_MiB", "Process peak working set (MiB)")]
    for (mode, style) in (("paper_greedy", "-"), ("mass_lb", "--")):
        for eps, color in zip((1.1, 1.04, 1.), ("#147c8f", "#ce692e", "#7651a8"), strict=True):
            rows = sorted([r for r in scan if r["heuristic"] == mode and r["epsilon"] == eps and
                           r["max_seconds"] == 60], key=lambda r: r["max_expansions"])
            for ax, (field, label) in zip(axes.flat, labels, strict=True):
                ax.plot([r["max_expansions"] for r in rows], [r[field] for r in rows],
                        style, color=color, lw=1.1, label=f"{mode}, eps={eps:g}")
                for row in rows:
                    ax.plot(row["max_expansions"], row[field], "o" if mode == "paper_greedy" else "s",
                            mec=color, mfc=color if row["search_completed"] else "white", ms=6)
                ax.set(xlabel="Expansion limit", ylabel=label, xticks=[600, 2000, 5000])
                ax.grid(alpha=.2)
    axes[0, 0].legend(fontsize=8)
    fig.suptitle("Lake Ontario historical reconstruction | N=500, T=49, q=.78\n"
                 "60s limit, OPEN<=20000 | filled: completed; hollow: aborted incumbent | no certificate obtained")
    fig.savefig(output / "budget_scan.png", dpi=150)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/baseline_v1.1/b5")
    opts = parser.parse_args()
    output = opts.output_dir.resolve()
    rows, pilot = read_json(output / "scan_runs.json"), read_json(output / "pilot_runs.json")
    manifest = read_json(output / "scan_manifest.json")
    scan = [r for r in rows if r["max_open"] == manifest["config"]["max_open"]]
    probes = [r for r in rows if r["max_open"] != manifest["config"]["max_open"]]
    identity = ("particle_archive_sha256", "source_manifest_sha256", "warm_path_sha256", "T", "q", "seed", "cpu_affinity", "thread_environment")
    if any(any(r[k] != scan[0][k] for k in identity) for r in rows + pilot):
        raise AssertionError("benchmark input/CPU settings differ")
    pairs = comparison_rows(pilot, scan)
    profile_stats = read_json(output / "profile_cprofile_stats.json")
    search = next(r for r in profile_stats if r["function"] == "search_asar")
    estimate = next(r for r in profile_stats if r["function"] == "__call__" and "heuristic.py" in r["file"])
    summary = dict(stage="B5", status="passed", report_script_sha256=digest(Path(__file__).resolve()), main_scan_runs=len(scan), open_probe_runs=len(probes),
                   diagnostic_runs=len(pilot), stop_distribution=dict(Counter(r["stop_reason"] or "completed" for r in scan)),
                   probe_stops=dict(Counter(r["stop_reason"] or "completed" for r in probes)),
                   certified_runs=sum(r["discrete_model_certified"] for r in rows),
                   peak_process_MiB_range=[min(r["peak_process_MiB"] for r in scan), max(r["peak_process_MiB"] for r in scan)],
                   max_independent_replay_error=max(r["independent_replay_error"] for r in rows + pilot),
                   profiler_heuristic_cumulative_share=estimate["cumulative_s"] / search["cumulative_s"],
                   implementation_changed=False, decision="retain numerical core; hotspots primarily required greedy rollout and validated belief operations",
                   limits="finite-budget evidence only; not a claim of global optimum, author data equivalence, or general algorithm failure",
                   before_after=pairs, artifacts_sha256={p.name: digest(p) for p in output.glob("*.json") if p.name != "summary.json"})
    save_json(output / "summary.json", summary)
    export_csv(output / "metrics.csv", rows)
    export_csv(output / "diagnostic_metrics.csv", pilot)
    # A compact comparison table with no invented optimization speedup.
    with (output / "before_after.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(pairs[0]))
        writer.writeheader()
        writer.writerows(pairs)
    render(scan, output)
    lines = ["# B5 预算与性能核验", "", "状态：passed。只执行 B5；未实施 B6 的最终基线比较。", "",
             f"主扫描 {len(scan)} 次；原 OPEN=2400 探针 {len(probes)} 次；独立 profile/内存及原速对照 {len(pilot)} 次。",
             f"主扫描退出分布：{summary['stop_distribution']}；OPEN 探针：{summary['probe_stops']}。",
             "所有运行使用 B3 冻结的 500 条轨迹、seed=41、T=49、q=.78 和同一动态 PT 初始路线。",
             "实际标签 historical_real_forcing_allwater：事后历史环境重建，全水域岸线假设，不是原作者完整数据复现。",
             "主扫描设 OPEN=20000，使 5000 次展开的测试不先被 2400 OPEN 限制。30/60 秒两档按完整矩阵执行。", "",
             "## 联合结果", "",
             "| heuristic | ε | 展开上限 | 秒上限 | OPEN上限 | J | Pd(T) | 展开 | OPEN峰值 | 搜索秒 | 进程峰值MiB | 状态/原因 | 来源 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|"]
    for r in rows:
        lines.append(f"| {r['heuristic']} | {r['epsilon']:g} | {r['max_expansions']} | {r['max_seconds']} | {r['max_open']} | {r['J']:.10f} | {r['Pd_T']:.8f} | {r['expanded']} | {r['peak_open']} | {r['planner_wall_s']:.4f} | {r['peak_process_MiB']:.2f} | {r['stop_reason'] or r['search_status']} | {r['incumbent_source']} |")
    lines += ["", "## 瓶颈与本轮决策", "",
              f"paper_greedy 的 cProfile 中，启发函数累计时间约占搜索 {100 * summary['profiler_heuristic_cumulative_share']:.1f}%。主要成本是每个展开分支反复执行余下时域的 Algorithm 2 贪心模拟。累计时间包含子调用，不应把各项累计比例相加。",
              "粒子按格索引和可达范围已缓存；profile 中仍出现的 bincount 是对各路径专属未探测权重的重新聚合，不能跨不同 belief 直接复用。",
              "mass_lb 单次展开便宜，但下界较松，当前预算内未完成。大量 OPEN 节点各持有独立权重数组，父指针还保留祖先。不得按 (vertex,depth) 合并以压低内存。",
              "本轮没有修改数值核心，也没有宣称没有其他优化空间。既有缓存已生效；在当前测量下，重复模拟及状态数是主要成本，简单绕过校验或改变累加方式需要另做等价性与收益实验。本轮交付可解释的预算限制及测量工具加固。", "",
              "| 同配置原速测量 | 首次秒 | 复测秒 | 首次峰值MiB | 复测峰值MiB | 路径/J/计数完全相同 |",
              "|---|---:|---:|---:|---:|---|"]
    for p in pairs:
        lines.append(f"| {p['heuristic']} ε={p['epsilon']:g}, cap={p['max_expansions']} | {p['before_s']:.4f} | {p['after_s']:.4f} | {p['before_peak_MiB']:.2f} | {p['after_peak_MiB']:.2f} | {p['identical_path_score_counters']} |")
    lines += ["", "数值实现未变，上表是首次/复测，不是优化加速比。cProfile 与 tracemalloc 分别单独运行，其额外开销不混入主扫描。", "",
              "## 测量口径与保证边界", "",
              "每个搜索为新子进程，不复用搜索缓存；OpenDrift 未导入或重新运行。所有路线通过统一评分器和独立逐 ID 布尔掩码重放。",
              f"独立重放最大 J 误差：{summary['max_independent_replay_error']}。本轮获得离散认证的运行数：{summary['certified_runs']}。",
              "paper_greedy 完成仅表示本次搜索正常退出，不能由此获得 ε 最优保证。mass_lb 有条件下界不等于中止运行获得证书。返回 PT 时 J 属于 PT；J_over_PT 的分母为本地 PT。",
              "本次 paper_greedy 的 ε=1.04 完成路线 J 比 ε=1.10 更低，但终点 Pd 略低；J 与终点 Pd 衡量不同目标，不据其中一个推定另一个更优。",
              "planner_wall_s 仅求解；warm_start_s 是一次实际 PT 构造时间，以同一未摊销成本记入各运行；total_wall_s 为二者之和。worker_wall_s 另含启动、输入校验和报告，不能与纯求解时间混用。",
              "peak_process_MiB 为独立进程从启动至搜索返回的 Windows 峰值工作集，包含导入与预处理，不是只计搜索新增的内存。rss_before_search_MiB 为起点工作集，不能简单相减得到精确的搜索峰值。",
              "诊断运行的 search_allocation_peak_MiB 是 tracemalloc 在搜索区间追踪的分配峰值，不含其未追踪的原生内存。frontier_belief_lower_bound_MiB 只计 OPEN 中权重数组的最低负担，未计祖先、Node、heap、索引及临时数组。",
              "CPU/可用 affinity、NumPy 构建、环境与单线程变量均记录于 manifest。Windows 正常调度下每个矩阵单元测一次，不做统计加速结论。",
              "限时为协作式检查；父进程另有 max_seconds+60 秒 watchdog。任何 watchdog 或 worker 异常都显式写入 JSON，路线/得分置 null，整轮命令失败退出。本轮真实扫描没有触发时间上限或 watchdog，先触发的是展开或 OPEN 限制；30 改成 60 秒未改变本轮的路线、计数与退出状态。", "",
              "![预算、J、时间与内存](budget_scan.png)", "",
              "## 文件与下一步", "",
              "metrics.csv/scan_runs.json 保存主扫描与 OPEN 探针；diagnostic_metrics.csv/pilot_runs.json 保存诊断。",
              "profile_cprofile.prof/.txt 与 mass_profile_cprofile.prof/.txt 保留可复查调用栈；对应 *_stats.json 为结构化热点。",
              "pilot_manifest.json、scan_manifest.json、warm_start.json 保存配置、代码、输入和 CPU 条件；summary.json 汇总状态。",
              "下一阶段 B6 才进行相同真实输入上 PT / ASAR_paper / ASAR_mass_lb / 可选 ACO_inspired 的最终比较。"]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print({k: summary[k] for k in ("status", "main_scan_runs", "stop_distribution", "probe_stops", "certified_runs")})


if __name__ == "__main__":
    main()
