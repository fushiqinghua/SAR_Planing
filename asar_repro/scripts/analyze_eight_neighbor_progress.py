#!/usr/bin/env python3
"""Audit and summarize a frozen 3-arm progress-aware search study."""
from __future__ import annotations
from collections import Counter
from pathlib import Path
from statistics import median
import argparse
import json
import math

import analyze_eight_neighbor_prefix_order as inherited

METHODS = ("C0", "C0_PREFIX", "C0_PROGRESS")
INSTANCES = ("lake_h2_d1_s3101", "lake_h2_d2_s3201",
             "hudson_h2_d1_s4101", "hudson_h2_d2_s4201")
PAIRS = (("fixed_vs_control", "C0_PREFIX", "C0"),
         ("progress_vs_control", "C0_PROGRESS", "C0"),
         ("progress_vs_fixed", "C0_PROGRESS", "C0_PREFIX"))
MIN_GAIN, SECONDARY_GAIN, J_TOL, MAX_PD_DROP = 0.001, 0.005, 1e-8, 0.005


def representative(rows, instance, method):
    values = sorted((r for r in rows if r["instance"] == instance and r["method"] == method),
                    key=lambda r: (r["J"], r["repetition"]))
    if len(values) != 3:
        raise ValueError("Three independent repeats required")
    return values[1]


def compare(rows):
    comparisons = []
    for pair, candidate, control in PAIRS:
        for instance in INSTANCES:
            a, b = representative(rows, instance, candidate), representative(rows, instance, control)
            gain = (b["J"] - a["J"]) / b["J"]
            delta = a["pd_final"] - b["pd_final"]
            comparisons.append(dict(
                pair=pair, instance=instance, region=a["region"], candidate=candidate, control=control,
                candidate_run_id=a["run_id"], control_run_id=b["run_id"],
                candidate_J=a["J"], control_J=b["J"], relative_J_gain=gain,
                candidate_Pd=a["pd_final"], control_Pd=b["pd_final"], delta_Pd_pp=100*delta,
                threshold_0p1=gain >= MIN_GAIN, threshold_0p5=gain >= SECONDARY_GAIN,
                J_nonregression=gain >= -J_TOL, Pd_guard=delta >= -MAX_PD_DROP,
                candidate_rss_mib=median(r["peak_rss_mib"] for r in rows
                    if r["instance"] == instance and r["method"] == candidate),
                control_rss_mib=median(r["peak_rss_mib"] for r in rows
                    if r["instance"] == instance and r["method"] == control),
                candidate_expanded=median(r["expanded"] for r in rows
                    if r["instance"] == instance and r["method"] == candidate),
                control_expanded=median(r["expanded"] for r in rows
                    if r["instance"] == instance and r["method"] == control),
            ))
    return comparisons


def screen(pairs, pair):
    sample = [p for p in pairs if p["pair"] == pair]
    if len(sample) != 4:
        raise ValueError("Four comparison rows required for each pair")
    win = [p for p in sample if p["threshold_0p1"]]
    return dict(
        pair=pair, passed=(len(win) >= 3 and len({p["region"] for p in win}) == 2
                          and all(p["J_nonregression"] and p["Pd_guard"] for p in sample)),
        threshold_0p1=len(win), threshold_0p5=sum(p["threshold_0p5"] for p in sample),
        all_J_nonregression=all(p["J_nonregression"] for p in sample),
        all_Pd_guard=all(p["Pd_guard"] for p in sample),
        regions_with_0p1=sorted({p["region"] for p in win}),
    )


def scheduler_evidence(out, rows):
    reports = []
    for row in rows:
        payload = inherited.read_json(out / "runs" / row["run_id"] / "result.json")
        task, inner = payload["task"], payload["result"]["raw"]["phases"][0]["inner"]
        if task["method"] != row["method"]:
            raise ValueError("Method mismatch in raw run")
        progress = inner["diagnostics"].get("progress_schedule")
        frontier = inner["diagnostics"].get("prefix_order")
        if row["method"] == "C0_PROGRESS":
            if not progress or not frontier or not isinstance(progress["events"], list):
                raise ValueError("Missing progress scheduler evidence")
            if progress["activations"] != sum(e["event"] == "on" for e in progress["events"]):
                raise ValueError("Mismatched activation events")
            if progress["deactivations"] != sum(e["event"] == "off" for e in progress["events"]):
                raise ValueError("Mismatched deactivation events")
            first = progress["first_search_improvement_s"]
            if first is not None and not 0 <= first <= 30:
                raise ValueError("Out-of-budget search improvement")
            if progress["events"] and first is None:
                raise ValueError("An activation occurred without a search improvement")
            if first is not None and any(e["elapsed_s"] < first for e in progress["events"]):
                raise ValueError("Lookahead in progress policy")
        elif progress is not None:
            raise ValueError("Progress logic used by a control arm")
        reports.append(dict(
            instance=row["instance"], method=row["method"], repetition=row["repetition"],
            run_id=row["run_id"],
            first_search_improvement_s=(progress or {}).get("first_search_improvement_s"),
            activations=(progress or {}).get("activations", 0),
            deactivations=(progress or {}).get("deactivations", 0),
            active_decisions=(progress or {}).get("active_decisions", 0),
            reserved_early_pops=(frontier or {}).get("reserved_early_pops", 0),
            reserved_middle_pops=(frontier or {}).get("reserved_middle_pops", 0),
            first_search_terminal_s=inner["diagnostics"].get("first_search_terminal_generated_s"),
            first_improvement_s=row.get("first_improvement_s"),
            terminal_candidates=row["terminal_candidates"],
            tail_expanded_fraction=row["tail_expanded_fraction"],
            guide_s=row["guide_s"],
        ))
    return reports


def analyze(out: Path):
    out = Path(out).resolve()
    tasks = inherited.read_json(out / "tasks.json")
    expected = Counter((i,m,r) for i in INSTANCES for m in METHODS for r in range(3))
    if Counter((t["instance"], t["method"], t["repetition"]) for t in tasks) != expected:
        raise ValueError("Missing or extra registered formal task")
    inherited.METHODS = METHODS
    inherited.INSTANCES = INSTANCES
    rows, survival, history = inherited.collect(out / "runs")
    if len(rows) != 36:
        raise ValueError("Expected 36 valid and independently replayed runs")
    progress = scheduler_evidence(out, rows)
    pairs = compare(rows)
    screens = [screen(pairs, p) for p,_,_ in PAIRS]
    primary = next(x for x in screens if x["pair"] == "progress_vs_control")
    status = ("progress_prefix_development_screen_passed" if primary["passed"]
              else "progress_prefix_development_screen_not_passed")
    inherited.write_json(out / "summary.json", dict(
        status=status, valid_runs=36, expected_runs=36, stage="P30",
        pairs=pairs, screens=screens, primary_decision="progress_vs_control",
        data_role="seen_H2_development", optimality_certified=False))
    inherited.write_csv(out / "comparison.csv", rows)
    inherited.write_csv(out / "instance_comparison.csv", pairs)
    inherited.write_csv(out / "progress_diagnostics.csv", progress)
    inherited.write_csv(out / "survival.csv", survival)
    inherited.write_csv(out / "incumbent_history.csv", history)
    lines = [
        "# 进展感知前缀调度：三组同预算筛选", "",
        f"**结果：{status}**。36/36 有效运行；每方法 3 次重复，算法预算各 30 s。",
        "本批仅使用已见 H2 开发实例，不作为新天气独立验证。",
        "每例取 J 中位代表的完整路线，Pd 不跨路线拼接。", "",
        "## 核心比较：C0_PROGRESS 对 C0", "",
        "| 实例 | C0 J | Progress J | J 改善 | Pd 变化（百分点） | 0.1% | 非退化 |",
        "|---|---:|---:|---:|---:|---|---|"
    ]
    for p in pairs:
        if p["pair"] == "progress_vs_control":
            lines.append(f"| {p['instance']} | {p['control_J']:.9f} | {p['candidate_J']:.9f} | "
                         f"{100*p['relative_J_gain']:+.4f}% | {p['delta_Pd_pp']:+.4f} | "
                         f"{p['threshold_0p1']} | {p['J_nonregression']} |")
    lines += ["", "## 三组配对判定", "",
              "| 配对 | 通过 | ≥0.1% | ≥0.5% | J 全部非退化 | Pd 护栏 |",
              "|---|---|---:|---:|---|---|"]
    for p in screens:
        lines.append(f"| {p['pair']} | {p['passed']} | {p['threshold_0p1']}/4 | "
                     f"{p['threshold_0p5']}/4 | {p['all_J_nonregression']} | {p['all_Pd_guard']} |")
    lines += ["", "## 归因与边界", "",
              "固定配额为同时重跑的机制对照，主结论仅来自进展感知与原 C0 的对照。",
              "新增方法仅修改搜索前缀的展开顺序，未接入新的实时传感器或风流信息。",
              "所有时间与内存、候选重放及排序开销都属于每任务 30 秒的预算。",
              "未通过不能删除不利实例或事后更改门槛。",
              "明细见 comparison.csv、progress_diagnostics.csv、survival.csv 与 runs/。",
              ""]
    (out / "REPORT.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(status, flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args=parser.parse_args()
    analyze(args.out)


if __name__ == "__main__":
    main()
