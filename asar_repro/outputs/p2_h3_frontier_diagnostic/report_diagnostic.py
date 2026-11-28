"""Summarize the matched trials and keep extended witnesses separate."""
from collections import Counter
import csv
from statistics import median

import run_diagnostic as run
from frontier_probe import MODES
from h3_protocol import save


def read_samples(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return [(int(row["monotonic_ns"]),int(row["rss_bytes"])) for row in csv.DictReader(stream)]


def mb(size):
    return None if size is None else size / 2**20


def compact(record,result,folder,protocol):
    t=result["task"]; i=result["inner"]; s=result["replay"]
    d=i["diagnostics"]; stats=i["stats"]; q=result["probe"] or {}
    handoff=q.get("handoff") or {}; split=q.get("split") or {}
    order=d.get("prefix_order") or {}; progress=d.get("progress_schedule") or {}
    reference=protocol["reference"][str(t["seed"])]
    baseline=reference["E30"]["C0"]
    values=read_samples(folder/"rss.csv")
    during=[rss for stamp,rss in values if result["start_ns"]<=stamp<=result["end_ns"]]
    after=[rss for stamp,rss in values if handoff.get("monotonic_ns",result["start_ns"])<=stamp<=result["end_ns"]]
    lineage=q.get("incumbent_lineage",[])
    latest=lineage[-1] if lineage else {}
    moved=d.get("lazy_frontier",{}) or {}
    phase={} if result["outer"] is None else result["outer"]["phases"][0]
    return dict(
        **t, run_id=folder.name, exact_work=result["exact_work"], stop=i["stop_reason"],
        solver_status=i["status"], J=s["J"], Pd=s["pd_final"], initial_J=reference["S30"]["J"],
        gain_vs_E30_C0_pct=100*(baseline["J"]-s["J"])/baseline["J"],
        gain_vs_best_E30_C0_pct=100*(reference["best_C0_J"]-s["J"])/reference["best_C0_J"],
        Pd_delta_vs_E30_C0_pp=100*(s["pd_final"]-baseline["Pd"]),
        wall_s=result["algorithm_wall_s"],
        outer_budget_met=result["algorithm_wall_s"]<=t["seconds"],
        outer_disposition=phase.get("reason"),outer_accepted=phase.get("accepted"),
        inner_return_s=phase.get("inner_return_compute_s"),inner_J=i["J"],inner_Pd=i["pd_final"],
        rss_peak_mib=mb(record["process_peak_rss_bytes"]), search_rss_peak_mib=mb(max(during,default=None)),
        post_checkpoint_rss_peak_mib=mb(max(after,default=None)), checkpoint_rss_mib=mb(handoff.get("rss_bytes")),
        split_before_mib=mb(split.get("rss_before")), split_during_mib=mb(split.get("rss_both_heaps")),
        split_after_mib=mb(split.get("rss_after_swap")), split_ms=moved.get("migration_s",0)*1000,
        expanded=i["expanded"], generated=i["generated"], peak_open=i["peak_open"], end_open=i["open_count"],
        terminal=stats["terminal_candidates"], first_terminal_s=d["first_search_terminal_generated_s"],
        first_search_improvement_s=next((x["elapsed_s"] for x in i["history"] if x["source"]=="search"),None),
        best_s=i["best_elapsed_s"], best_source=i["history"][-1]["source"],
        first_gate_on_s=next((row["elapsed_s"] for row in progress.get("events",[]) if row["event"]=="on"),None),
        reserved_pops=order.get("reserved_early_pops",0)+order.get("reserved_middle_pops",0),
        winning_reserved_ancestors=len(latest.get("reserved_ancestors",[])),
        strict_improvements_with_reserved_ancestor=sum(bool(c["reserved_ancestors"]) for c in lineage),
        lineage_bytes=q.get("lineage_bookkeeping_bytes",0),
        guide_s=stats["guide_s"], completion_s=stats["completion_s"], route_length=len(s["waypoints"]),
    )


def write_csv(path,rows):
    with path.open("x",encoding="utf-8",newline="") as stream:
        fields=list(dict.fromkeys(key for row in rows for key in row))
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def med(rows,key):
    values=[row[key] for row in rows if row[key] is not None]
    return median(values) if values else None


def group_fixed(fixed):
    metrics=("J","Pd","peak_open","rss_peak_mib","search_rss_peak_mib","expanded",
             "wall_s","terminal","first_terminal_s","reserved_pops","winning_reserved_ancestors",
             "strict_improvements_with_reserved_ancestor","split_ms","guide_s")
    view={}
    pairs=[]
    for seed in run.CAPS:
        case=[row for row in fixed if row["seed"]==seed]
        groups={mode:[row for row in case if row["mode"]==mode] for mode in MODES}
        view[str(seed)]={mode:{key:med(group,key) for key in metrics} for mode,group in groups.items()}
        for mode,group in groups.items():
            representative=sorted(group,key=lambda row:(row["J"],row["rep"]))[len(group)//2]
            view[str(seed)][mode].update(
                J=representative["J"],Pd=representative["Pd"],metric_run_id=representative["run_id"],
            )
        for rep in range(run.REPS):
            single,three,quota=(next(row for row in groups[mode] if row["rep"]==rep) for mode in MODES)
            for mode,compare in (("split_only",three),("quota_vs_three_global",quota)):
                base=single if mode=="split_only" else three
                pairs.append(dict(seed=seed,rep=rep,contrast=mode,
                                  base=base["run_id"],candidate=compare["run_id"],
                                  delta_J=compare["J"]-base["J"],delta_Pd_pp=100*(compare["Pd"]-base["Pd"]),
                                  delta_peak_open=compare["peak_open"]-base["peak_open"],
                                  delta_peak_RSS_MiB=compare["rss_peak_mib"]-base["rss_peak_mib"],
                                  candidate_reserved=compare["reserved_pops"],candidate_winning_lineage=compare["winning_reserved_ancestors"]))
    return view,pairs


def plot(fixed,output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors=dict(single_global="#266b91",three_global="#53a392",three_quota="#bd6440")
    fig,axes=plt.subplots(1,2,figsize=(11,4.2),constrained_layout=True)
    for seed,ax in zip((4501,4601),axes,strict=True):
        for mode in MODES:
            choice=next(row for row in fixed if row["seed"]==seed and row["mode"]==mode and row["rep"]==0)
            directory=run.OUT/"runs"/choice["run_id"]
            raw=run.read(directory/"result.json")
            start,end=raw["start_ns"],raw["end_ns"]
            samples=[((t-start)/1e9,mb(size)) for t,size in read_samples(directory/"rss.csv") if start<=t<=end]
            if samples:
                t,rss=zip(*samples)
                ax.plot(t,rss,label=mode.replace("_"," "),color=colors[mode],alpha=.86)
        ax.set_title(f"Hudson Bay {seed} · repetition 0")
        ax.set_xlabel("Seconds from search start")
        ax.set_ylabel("Process RSS (MiB)")
        ax.grid(alpha=.2)
    axes[0].legend(frameon=False)
    fig.savefig(output,dpi=145)
    plt.close(fig)


def main():
    p=run.lock()
    rows=run.load_results(p,"fixed")
    run.check_fixed(rows)
    fixed=[compact(*r,p) for r in rows]
    extension=[compact(*r,p) for r in run.load_results(p,"extended")]
    def optional_run(folder):
        if not (folder/"record.json").is_file():
            return None
        record=run.read(folder/"record.json")
        if (record["status"]=="valid"
                and all(run.digest(folder/n)==sha for n,sha in record["files"].items())):
            return compact(record,run.read(folder/"result.json"),folder,p)
        return None

    capacity=optional_run(run.OUT/"capacity_4601/runs/extended_4601_r0_C0_capacity")
    delivery=optional_run(run.OUT/"capacity_4601_delivery/runs/extended_4601_r0_C0_capacity_reserve")
    witness_path=run.OUT/"capacity_4601_delivery/first_inner_route_replay.json"
    witness=run.read(witness_path) if witness_path.is_file() else None
    view,pairs=group_fixed(fixed)
    directory=run.OUT/("analysis_final" if (run.OUT/"analysis").exists() else "analysis")
    directory.mkdir(exist_ok=False)
    write_csv(directory/"fixed_work.csv",fixed)
    write_csv(directory/"fixed_work_pairs.csv",pairs)
    write_csv(directory/"extended.csv",extension)
    if capacity:
        write_csv(directory/"capacity_4601.csv",[row for row in (capacity,delivery) if row])
    plot(fixed,directory/"hudson_rss.png")
    output=dict(status="complete" if all(r["exact_work"] for r in fixed) else "matched_work_incomplete",
                fixed_verified=len(fixed),fixed_exact=sum(r["exact_work"] for r in fixed),
                extended_verified=len(extension),toy_tests=p["tests"]["count"], extended=extension,
                capacity_4601=capacity, capacity_delivery=delivery,
                first_inner_witness_sha256=run.digest(witness_path) if witness else None,
                fixed_medians=view, fixed_stop_counts=dict(Counter(r["stop"] for r in fixed)),
                extended_stop_counts=dict(Counter(r["stop"] for r in extension)),
                protocol_sha256=run.digest(run.OUT/"protocol.json"), certificate=False)
    save(directory/"summary.json",output)
    lines=[
        "# P2/H3 同前缀搜索诊断",
        "",
        f"完成 {len(fixed)} 次固定展开量诊断及 {len(extension)} 次延长预算诊断。"
        f"固定展开量符合要求 {output['fixed_exact']}/{len(fixed)}，toy/Oracle 与专项测试 {output['toy_tests']} 项。",
        "",
        "各 seed 的三组先进行 1,024 次原生全局展开。交接时的完整 OPEN、此前取点序列指纹一致。"
        "三堆组在交接点迁移结构，原配额的资格与启停仍由原规则决定。"
        "延长预算独立列示，两组沿用冻结 S30，Lazy 的资格截止维持在 5.95 秒。",
        "",
        "| Seed | 模式 | 有效展开数 | J 中位数 | Pd 中位数 | OPEN 峰值中位数 | RSS 峰值中位数 MiB | 配额取点中位数 |",
        "|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for seed,case in view.items():
        for mode,v in case.items():
            lines.append(f"| {seed} | {mode} | {v['expanded']:g} | {v['J']:.9f} | {v['Pd']:.5%} | "
                         f"{v['peak_open']:g} | {v['rss_peak_mib']:.2f} | {v['reserved_pops']:g} |")
    control,quota=(view["4501"][mode] for mode in ("three_global","three_quota"))
    lines.extend(["",
                  f"4501 在三堆全局下的 OPEN、RSS 峰值中位数分别为 {control['peak_open']:g} 和 "
                  f"{control['rss_peak_mib']:.2f} MiB。原配额组分别为 {quota['peak_open']:g} 和 {quota['rss_peak_mib']:.2f} MiB。"
                  f"相对原配额，改为全局取点的降幅分别为 {1-control['peak_open']/quota['peak_open']:.1%} 和 "
                  f"{1-control['rss_peak_mib']/quota['rss_peak_mib']:.1%}。"])
    lines.extend(["","## Hudson 延长预算","",
                  "| Seed | 方法 | J | Pd | 相对 30 秒 C0 中位 J 改善 | 主搜索终点 | 终止原因 |",
                  "|---:|---|---:|---:|---:|---:|---|"])
    for r in extension:
        lines.append(f"| {r['seed']} | {r['mode']} | {r['J']:.9f} | {r['Pd']:.5%} | {r['gain_vs_E30_C0_pct']:+.4f}% "
                     f"| {r['terminal']} | {r['stop']} |")
    if capacity:
        lines.extend(["",
                      "## 4601 单独容量诊断",
                      "",
                      f"两组原上限的延长预算求解均在 100,000 OPEN 处中止且主搜索终点为 0。"
                      f"把 OPEN 上限调为 200,000 后，首个主搜索终点出现在 {capacity['first_terminal_s']:.2f} 秒。"
                      f"首次容量诊断的内层最优候选于 {capacity['best_s']:.2f} 秒找到，"
                      f"内层 J 为 {capacity['inner_J']:.9f}，Pd 为 {capacity['inner_Pd']:.5%}。"
                      f"外层返回时刻为 {capacity['inner_return_s']:.6f} 秒，"
                      f"处置为 {capacity['outer_disposition']}，实际交付路线 J 为 {capacity['J']:.9f}。"])
    if witness:
        lines.append("首次容量诊断的内层候选另做了双重物理重放。该记录用于证实可行路线空间。")
    if delivery:
        lines.extend(["",f"随后将外层交付预留从 0.25 秒增至 2 秒，仍使用 120 秒总预算。"
                      f"实际耗时 {delivery['wall_s']:.6f} 秒，外层处置为 {delivery['outer_disposition']}。"
                      f"交付 J 为 {delivery['J']:.9f}，Pd 为 {delivery['Pd']:.5%}，"
                      f"相对原 30 秒 C0 的 J 改善为 {delivery['gain_vs_E30_C0_pct']:+.4f}%，"
                      f"Pd 变化为 {delivery['Pd_delta_vs_E30_C0_pp']:+.4f} 个百分点。"
                      f"OPEN 峰值 {delivery['peak_open']:,}，RSS 峰值 {delivery['rss_peak_mib']:.2f} MiB。"])
    lines.extend(["",
                  "RSS 为独立子进程 50 ms 轮询的采样峰值。逐运行记录另包含分堆调用点的直接 RSS 读数。"
                  "配额祖先关系来自原始路径前缀，记录其先于可行解重放的证据。延长时限结果用于诊断改善空间，认证字段为 false。",""])
    (directory/"REPORT.md").write_text("\n".join(lines),encoding="utf-8")
    print(directory,output["status"])


if __name__=="__main__":
    main()
