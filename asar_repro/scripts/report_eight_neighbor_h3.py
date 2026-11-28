"""Date-level scoring and report generation for the frozen P2/H3 experiment."""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from statistics import median

from h3_protocol import digest, read, save, stamp


REGION = {"lake_ontario": "Lake Ontario", "arctic_ocean": "Hudson Bay"}
ARMS = ("C0", "Lazy")


def per_seed(rows):
    grouped = defaultdict(lambda: defaultdict(list))
    for row in rows:
        task = row["task"]
        grouped[(task["site"], task["date"], task["seed"])][task["method"]].append(row)
    comparisons = []
    for (site, date, seed), methods in sorted(grouped.items()):
        if not all(len(methods[arm]) == 3 for arm in ARMS):
            continue
        representatives = {}
        for arm in ARMS:
            values = methods[arm]
            if {row["task"]["repetition"] for row in values} != {0, 1, 2}:
                raise ValueError("H3 seed comparison requires three distinct repetitions in each arm")
            row = sorted(values, key=lambda r: (r["result"]["J"], r["task"]["repetition"]))[1]
            representatives[arm] = dict(
                J=row["result"]["J"], Pd=row["result"]["pd_final"], run_id=row["run_id"],
                median_wall_s=median(r["result"]["algorithm_wall_s"] for r in values),
                median_cpu_s=median(r["result"]["algorithm_cpu_s"] for r in values),
                median_rss_mib=median(r["record"]["peak_rss_bytes"] for r in values) / 2**20,
            )
        base, candidate = (representatives[arm] for arm in ARMS)
        comparisons.append(dict(
            site=site, date=date, seed=seed, C0=base, Lazy=candidate,
            J_gain=(base["J"] - candidate["J"]) / base["J"] if base["J"] > 0 else None,
            delta_Pd_pp=100 * (candidate["Pd"] - base["Pd"]),
        ))
    return comparisons


def date_screen(comparisons, *, complete):
    dates = defaultdict(list)
    for row in comparisons:
        dates[(row["site"], row["date"])].append(row)
    dates = [
        dict(site=site, date=date, seeds=[row["seed"] for row in samples],
             J_gain=median(row["J_gain"] for row in samples))
        for (site, date), samples in sorted(dates.items())
        if len(samples) == 2 and all(row["J_gain"] is not None for row in samples)
    ]
    regions = {
        site: dict(count=len(values), median_J_gain=median(values), worst_J_gain=min(values),
                   wins_0_1_pct=sum(value >= .001 for value in values))
        for site in REGION if (values := [row["J_gain"] for row in dates if row["site"] == site])
    }
    endpoints = [row["seed"] for row in comparisons if row["delta_Pd_pp"] < -.5]
    result = dict(status="incomplete", date_rows=dates, regions=regions,
                  pd_risk_seeds=endpoints, dual_J_Pd_screen_passed=False)
    if (not complete or len(comparisons) != 12 or len(dates) != 6
            or any(regions.get(site, {}).get("count") != 3 for site in REGION)):
        return result
    gains = [row["J_gain"] for row in dates]
    wins = sum(value >= .001 for value in gains)
    worst_seed = min(comparisons, key=lambda row: row["J_gain"])
    passes = (wins >= 4 and all(region["wins_0_1_pct"] >= 1 for region in regions.values())
              and min(gains) >= -.005 and worst_seed["J_gain"] >= -.01)
    result.update(status="date_J_screen_passed" if passes else "date_J_screen_failed",
                  wins_0_1_pct=wins, wins_0_5_pct=sum(value >= .005 for value in gains),
                  median_J_gain=median(gains), worst_date_J_gain=min(gains),
                  worst_seed=worst_seed["seed"], worst_seed_J_gain=worst_seed["J_gain"],
                  dual_J_Pd_screen_passed=passes and not endpoints)
    return result


def _csv(path, rows):
    if not rows:
        return
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _detail(row):
    task, result, record = (row[k] for k in ("task", "result", "record"))
    inner = result["raw"]["phases"][0]["inner"] if task["stage"] == "E30" else result["initialization"]["raw_solver"]
    return dict(run_id=row["run_id"], stage=task["stage"], site=task["site"], date=task["date"],
                seed=task["seed"], method=task["method"], repetition=task["repetition"], J=result["J"],
                Pd=result["pd_final"], algorithm_wall_s=result["algorithm_wall_s"],
                algorithm_cpu_s=result["algorithm_cpu_s"], peak_rss_mib=record["peak_rss_bytes"]/2**20,
                process_wall_s=record["process_wall_s"], input_load_s=result["input_load_s"],
                audit_wall_s=result["audit_wall_s"], solver_status=inner.get("status") if inner else None,
                stop_reason=inner.get("stop_reason") if inner else None,
                expansions=inner.get("expanded") if inner else None,
                particle_sha256=task["particle_sha256"], formal_optimality_certificate=False)


def _figures(folder, comparisons, runs):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if not comparisons:
        return
    colors = {"C0": "#266b8d", "Lazy": "#bf621e"}
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    by_id = {row["run_id"]: row for row in runs}
    for view in ("survival", "paths"):
        fig, panels = plt.subplots(3, 4, figsize=(13, 8), squeeze=False, constrained_layout=True)
        for ax, case in zip(panels.flat, comparisons):
            ax.set_title(f"{REGION[case['site']]} · {case['date'][5:]} · {case['seed']}", fontsize=9)
            for arm in ARMS:
                replay = by_id[case[arm]["run_id"]]["result"]["physical_replay"]
                if view == "survival":
                    ax.step([0, *replay["observation_times_s"]], replay["survival"], where="post",
                            color=colors[arm], label=arm, lw=1.5)
                else:
                    points = [seg["start_xy"] for seg in replay["segments"]] + [replay["final_xy"]]
                    x, y = zip(*points)
                    ax.plot(x, y, color=colors[arm], label=arm, lw=1.15, alpha=.82)
                    ax.scatter(x[0], y[0], marker="+", c="#232c30", s=16)
            ax.grid(alpha=.16)
            if view == "paths":
                ax.set_aspect("equal", adjustable="datalim")
        for ax in list(panels.flat)[len(comparisons):]:
            ax.set_visible(False)
        panels.flat[0].legend(frameon=False, fontsize=8)
        fig.supxlabel("Time from CST (s)" if view == "survival" else "Local east (m)")
        fig.supylabel("Remaining probability" if view == "survival" else "Local north (m)")
        fig.savefig(folder / f"{view}.png", dpi=150)
        plt.close(fig)
    fig, panels = plt.subplots(2, 1, figsize=(12, 6), constrained_layout=True)
    index = list(range(len(comparisons)))
    for ax, key, unit in zip(panels, ("median_wall_s", "median_rss_mib"), ("Algorithm time (s)", "Peak RSS (MiB)"), strict=True):
        for sign, arm in zip((-1, 1), ARMS, strict=True):
            ax.bar([i + sign * .19 for i in index], [case[arm][key] for case in comparisons],
                   width=.35, color=colors[arm], label=arm)
        ax.set_ylabel(unit)
        ax.set_xticks(index, [row["seed"] for row in comparisons])
        ax.grid(axis="y", alpha=.2)
    panels[0].legend(frameon=False)
    panels[1].set_xlabel("Particle seed")
    fig.savefig(folder / "resources.png", dpi=150)
    plt.close(fig)


def analyze(out):
    from run_eight_neighbor_h3 import freeze_s30, saved_task, task_id, verify_protocol

    assessments = sorted((out / "qualification").glob("*.json"))
    audit = read(assessments[-1]) if assessments else {}
    validations = sorted((out / "validation").glob("*/validation.json"))
    checks = read(validations[-1]) if validations else {}
    runs, failed = {"S30": [], "E30": []}, []
    protocol = None
    if (out / "protocol.json").exists():
        protocol, tasks = verify_protocol(out, full=True)
        for stage, allocated in tasks.items():
            for task in allocated:
                path = out / "runs" / task_id(task)
                if path.exists():
                    try:
                        runs[stage].append(saved_task(out, task, protocol))
                    except (KeyError, OSError, TypeError, ValueError) as exc:
                        failed.append(dict(run_id=path.name, error=str(exc)))
        if len(runs["S30"]) == 12:
            freeze_s30(out, protocol, tasks["S30"])
    complete = len(runs["S30"]) == 12 and len(runs["E30"]) == 72 and not failed
    comparisons = per_seed(runs["E30"])
    screen = date_screen(comparisons, complete=complete)
    data_status = audit.get("status", "pending_qualification")
    status = "complete" if complete else "data_incomplete" if data_status == "data_incomplete" else "blocked"
    folder = out / "reports" / stamp()
    folder.mkdir(parents=True, exist_ok=False)
    all_runs = runs["S30"] + runs["E30"]
    details = [_detail(row) for row in all_runs]
    resources = {
        arm: dict(wall_median_s=median(row["algorithm_wall_s"] for row in rows),
                  cpu_median_s=median(row["algorithm_cpu_s"] for row in rows),
                  rss_median_mib=median(row["peak_rss_mib"] for row in rows),
                  rss_max_mib=max(row["peak_rss_mib"] for row in rows),
                  stops=dict(Counter(row["stop_reason"] for row in rows)))
        for arm in ARMS if (rows := [row for row in details if row["method"] == arm])
    }
    summary = dict(
        status=status, forcing_status=data_status, forcing_kind="historical_real",
        dates_verified=len(audit.get("selected", [])), replacements=audit.get("replacements", {}),
        valid_runs={stage: len(result) for stage, result in runs.items()}, failed_runs=failed,
        validation=checks.get("status"), validation_counts={row["scope"]: row["testcase_count"]
                                                          for row in checks.get("evidence", [])},
        planned_algorithm_seconds=2520, elapsed_algorithm_seconds=sum(row["algorithm_wall_s"] for row in details),
        resources=resources, seed_comparisons=comparisons, date_screen=screen,
        global_optimality_certified=False, independent_weather_units=len(screen["date_rows"]),
        evidence_sha256={str(path.relative_to(out)): digest(path)
                         for path in (*assessments[-1:], *validations[-1:], out/"method_lock.json",
                                      out/"inputs_lock.json", out/"date_lock.json", out/"protocol.json", out/"s30_lock.json")
                         if path.is_file()},
    )
    save(folder / "summary.json", summary)
    _csv(folder / "forcing_qualification.csv", [
        {key: row.get(key) for key in ("block_id", "scene", "date", "primary", "status", "reason")}
        for row in audit.get("dates", [])
    ])
    _csv(folder / "runs.csv", details)
    _csv(folder / "seeds.csv", [
        dict(site=row["site"], date=row["date"], seed=row["seed"], J_gain=row["J_gain"],
             delta_Pd_pp=row["delta_Pd_pp"], **{f"{arm}_{key}": value for arm in ARMS for key, value in row[arm].items()})
        for row in comparisons
    ])
    _csv(folder / "dates.csv", screen["date_rows"])
    _csv(folder / "survival.csv", [
        dict(run_id=row["run_id"], seed=row["task"]["seed"], method=row["task"]["method"], t_s=t, mass=m)
        for row in all_runs for t, m in zip([0., *row["result"]["physical_replay"]["observation_times_s"]],
                                            row["result"]["physical_replay"]["survival"], strict=True)
    ])
    _figures(folder, comparisons, runs["E30"])
    lines = [
        "# P2/H3 新天气日期外推",
        "",
        f"状态 **{status}**。真实 forcing 资格 {summary['dates_verified']}/6，"
        f"S30 {len(runs['S30'])}/12，E30 {len(runs['E30'])}/72。",
        "",
        "Lake Ontario 使用 HRRR 与 LOOFS，Hudson Bay 使用 GFS 与 HYCOM ESPC-D-V02。"
        "日期选择仅依据历史归档覆盖与模型适用性。LOOFS 历史 nowcast 的实时可获得性未验证。",
        "",
        "S30 沿用 H2 的 PT → paper_greedy 初始化和轴对齐桥接验证。"
        "C0 和 Lazy 使用同一条已核验的 S30 路线、同一粒子档案、八邻接、heading-square 和 30 秒上限。"
        "每条最终提交路线通过规划模型和独立标量评分器重放。C0/Lazy 的方法与评分器的文件指纹见协议。",
        "",
        "逐 seed 取三次 J 的中位运行，再读取同一条路径的 Pd。"
        "日期改善为两个 seed 的相对 J 改善中位数。日期是外推单位，seed 和计时重复嵌套在日期内。",
        "",
    ]
    if complete and screen["status"] != "incomplete":
        lines.extend([
            f"J 工程筛选 **{screen['status']}**。{screen['wins_0_1_pct']}/6 日期达到 0.1%，"
            f"{screen['wins_0_5_pct']}/6 达到 0.5%。日期改善中位数 {screen['median_J_gain']:+.4%}，"
            f"最差日期 {screen['worst_date_J_gain']:+.4%}，最差 seed {screen['worst_seed']} "
            f"（{screen['worst_seed_J_gain']:+.4%}）。",
            "",
            ("终点 Pd 下降超过 0.5 个百分点的 seeds 为 " + ", ".join(map(str, screen["pd_risk_seeds"])) + "。"
             if screen["pd_risk_seeds"] else "全部 seed 均通过终点 Pd 下降 0.5 个百分点的护栏。"),
            "",
        ])
    if screen["date_rows"]:
        lines.extend(["| 地区 | UTC 日期 | J 改善 |", "|---|---|---:|"])
        lines.extend(f"| {REGION[row['site']]} | {row['date']} | {row['J_gain']:+.4%} |" for row in screen["date_rows"])
        lines.append("")
    if resources:
        lines.extend(["| 方法 | 算法耗时中位数 s | CPU 中位数 s | RSS 中位数 MiB | RSS 最大值 MiB |",
                      "|---|---:|---:|---:|---:|"])
        for arm, r in resources.items():
            lines.append(f"| {arm} | {r['wall_median_s']:.3f} | {r['cpu_median_s']:.3f} | {r['rss_median_mib']:.2f} | {r['rss_max_mib']:.2f} |")
        lines.append("")
    lines.extend(["RSS 为独立进程轮询采样的峰值。数值结论适用于本协议的地速、时钟、"
                  "探测代理和同预算搜索。全局最优认证状态为 false。", ""])
    with (folder / "REPORT.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(lines))
    print(f"{status}: {summary['valid_runs']}; {folder}", flush=True)
    return summary
