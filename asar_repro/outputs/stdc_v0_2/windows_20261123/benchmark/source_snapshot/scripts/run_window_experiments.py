"""Isolated, SHA-gated real-data experiments for fixed-suffix window search.

Run only after the new tests, historical tests and toy Oracle gates pass.  This
is a NEW research protocol: the frozen B7 protocol/results are read-only.  The
paper baseline receives the whole global budget; each window method pays for
its paper seed and every local search within the same global budget.  No
method in this experiment receives a global epsilon certificate.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import asdict
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
from statistics import median
import subprocess
import sys
from time import perf_counter
import traceback

import numpy as np
import psutil

from asar_repro.objective import score_path
from asar_repro.search import search_asar
from stdc_validation_guards import (
    ATOL, PARTICLE_SHA, PROTOCOL_SHA, ROOT, check_score, digest, load_real,
    read, require, save,
)


VARIANTS = {
    "paper_baseline": "paper_greedy",
    "window_zero": "zero",
    "window_mass_lb": "mass_lb",
    "window_stdc_lb": "stdc_lb",
    "window_stdc_endpoint_lb": "stdc_endpoint_lb",
}
LABELS = {
    "paper_baseline": "Paper baseline",
    "window_zero": "Window / zero",
    "window_mass_lb": "Window / mass",
    "window_stdc_lb": "Window / STDC",
    "window_stdc_endpoint_lb": "Window / endpoint STDC",
}
COLORS = dict(zip(VARIANTS, ("#0072B2", "#999999", "#E69F00", "#009E73", "#CC79A7")))
LIMITS = dict(max_expansions=5000, max_open=20000, max_seconds=30)
WINDOW_LENGTHS = (4, 6)
SEED_MAX_EXPANSIONS = 1500
WATCHDOG_S = 180
THREAD_VARIABLES = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                    "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS")
SOURCES = (
    "src/asar_repro/window_bounds.py", "src/asar_repro/window_search.py",
    "src/asar_repro/search.py", "src/asar_repro/heuristic.py",
    "src/asar_repro/motion.py", "src/asar_repro/objective.py",
    "src/asar_repro/belief.py", "src/asar_repro/grid.py",
    "scripts/run_window_experiments.py", "scripts/stdc_validation_guards.py",
)


def source_fingerprints():
    return {name: digest(ROOT / name) for name in SOURCES}


def json_ready(value):
    """Preserve dataclass diagnostics while keeping JSON strictly finite."""
    if isinstance(value, np.ndarray):
        return json_ready(value.tolist())
    if isinstance(value, np.generic):
        return json_ready(value.item())
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, float):
        require(np.isfinite(value), "non-finite value in experiment evidence")
    return value


def environment():
    versions = {}
    for name in ("numpy", "scipy", "psutil", "matplotlib", "opendrift", "pytest"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return dict(python=sys.version, interpreter=sys.executable,
                platform=platform.platform(), package_versions=versions,
                threads={key: os.environ.get(key) for key in THREAD_VARIABLES},
                python_hash_seed=os.environ.get("PYTHONHASHSEED"))


def snapshot(folder):
    """Record working-tree state, including exact copies of new source files."""
    git = ["git", "-c", f"safe.directory={ROOT.parent.as_posix()}"]
    commands = []
    for name, arguments in (("git_status", ["status", "--short"]),
                            ("git_diff", ["diff", "--no-ext-diff", "HEAD", "--"]),
                            ("git_head", ["rev-parse", "HEAD"])):
        command = git + arguments
        result = subprocess.run(command, cwd=ROOT, capture_output=True, check=False)
        suffix = ".patch" if name == "git_diff" else ".txt"
        (folder / (name + suffix)).write_bytes(result.stdout)
        (folder / (name + ".stderr.txt")).write_bytes(result.stderr)
        commands.append(dict(command=command, exit_code=result.returncode))
        require(result.returncode == 0, f"{name} evidence collection failed")
    fingerprints = source_fingerprints()
    for name in SOURCES:
        destination = folder / "source_snapshot" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / name).read_bytes())
    save(folder / "source_manifest.json", dict(
        sha256=fingerprints, git_commands=commands,
        diff_scope="tracked changes relative to HEAD; source_snapshot also captures new files",
        environment=environment()))
    return fingerprints


def input_evidence(protocol, pt, times, raw):
    return dict(status="passed", forcing_kind="historical_real",
                experiment_label=protocol["experiment_label"],
                protocol_sha256=PROTOCOL_SHA, particle_sha256=PARTICLE_SHA,
                particle_metadata_sha256=protocol["particle_metadata_sha256"],
                source_manifest_sha256=protocol["source_manifest_sha256"],
                particle_seed=protocol["mission"]["seed"], mission=protocol["mission"],
                verified_raw_sources=raw, PT_J=pt.J, PT_Pd=pt.pd_final,
                time_utc=[str(t) + "Z" for t in times],
                objective="J = sum(M[1:T+1]); Pd = 1 - M[T]; no sensing at t=0",
                synthetic_substitution=False, drift_rerun=False)


def validate_gate(path):
    require(path is not None, "--validation-evidence is required before real smoke")
    evidence = read(path)
    require(evidence.get("status") == "passed" and not evidence.get("not_run"),
            "new tests, historical tests and toy Oracle validation must all pass")
    validated_sources = evidence.get("source_sha256")
    require(isinstance(validated_sources, dict), "validation evidence lacks source fingerprints")
    for name, expected in validated_sources.items():
        source = (ROOT / name).resolve()
        require(source.is_relative_to(ROOT), "validation source path outside project")
        require(source.is_file() and digest(source) == expected,
                "source changed since tests/Oracle validation: " + name)
    require(all(validated_sources.get(name) == expected
                for name, expected in source_fingerprints().items()),
            "experiment source was not covered by the validated source snapshot")
    return dict(path=str(path.resolve()), sha256=digest(path), evidence=evidence)


def plan(stage, protocol, validation):
    epsilons = [float(eps) for eps in protocol["epsilon"]]
    require(len(epsilons) == 3 and len(set(epsilons)) == 3,
            "expected exactly three frozen epsilon settings")
    require(protocol["search_limits"] == LIMITS, "frozen reference limits changed")
    schedule = []
    if stage == "smoke":
        schedule = [(name, 1.1, 0) for name in VARIANTS]
        schedule.append(("window_stdc_endpoint_lb", 1.0, 0))
    else:
        for eps in epsilons:
            for repeat in range(3):
                # Rotate method order per repeat to reduce systematic warm-up bias.
                names = list(VARIANTS)
                names = names[repeat:] + names[:repeat]
                schedule.extend((name, eps, repeat) for name in names)
    return dict(
        protocol="stdc_fixed_suffix_window_research_v1", stage=stage,
        frozen_protocol_sha256=PROTOCOL_SHA, frozen_particle_sha256=PARTICLE_SHA,
        changes_frozen_protocol=False, objective_unchanged=True,
        planned_runs=len(schedule), epsilons=epsilons, repeats=1 if stage == "smoke" else 3,
        variants=VARIANTS, window_lengths=list(WINDOW_LENGTHS),
        window_schedule="same deterministic schedule for all four window controls",
        global_limits=LIMITS, seed_max_expansions=SEED_MAX_EXPANSIONS,
        seed_policy="paper_greedy seed paid within each method's global totals; expansion subquota may continue; global time/open stops do not",
        baseline_policy="direct paper_greedy search with the full global caps and the same frozen PT initial incumbent",
        watchdog_s=WATCHDOG_S, threads=1, particle_seed=protocol["mission"]["seed"],
        planner_randomness="none; repeated timing runs reuse identical frozen particles",
        epsilon_scope="paper seed and direct paper baseline only; local windows use unweighted lower bounds",
        guarantee="all full routes uncertified; completed windows are only endpoint/time/suffix neighborhood results up to numerical tolerance; no epsilon claim is made",
        validation=validation, schedule=[dict(variant=v, epsilon=e, repeat=r)
                                        for v, e, r in schedule])


def verify_accounting(result):
    require(result["expanded"] <= LIMITS["max_expansions"], "global expansion cap exceeded")
    require(result["peak_open"] <= LIMITS["max_open"], "global OPEN cap exceeded")
    parts = [result["seed"], *result["windows"]]
    require(isinstance(result["seed"], dict), "missing seed accounting")
    observed = {}
    for field in ("expanded", "generated", "pruned"):
        values = [part.get(field, 0) for part in parts]
        require(all(isinstance(value, int) and value >= 0 for value in values),
                f"invalid {field} part counters")
        observed[field] = sum(values)
        require(result[field] == observed[field], f"unpaid method work: {field} total mismatch")
    observed["peak_open"] = max((part.get("peak_open", 0) for part in parts), default=0)
    require(result["peak_open"] == observed["peak_open"], "peak OPEN total mismatch")
    seed = result["seed"]
    reason = seed.get("stop_reason")
    if reason in ("max_seconds", "max_open"):
        require(not result["windows"], "continued after a global seed stop")
    return dict(status="passed", recomputed_totals=observed,
                seed_status=seed.get("status"), seed_stop_reason=reason,
                continued_after_seed_expansion_subquota=(
                    reason == "max_expansions" and bool(result["windows"])),
                global_time_is_cooperative=True)


def worker(folder, variant, epsilon, repeat):
    started = perf_counter()
    require(variant in VARIANTS, "unknown experiment variant")
    require(not (folder / "result.json").exists(), "refusing worker result overwrite")
    protocol, graph, cfg, pt, times, raw = load_real()  # Each fresh process gates every real input.
    before_sources = source_fingerprints()
    preprocessing_s = perf_counter() - started
    tic = perf_counter()
    if variant == "paper_baseline":
        result = search_asar(graph, **cfg, heuristic="paper_greedy", epsilon=epsilon,
                             initial_path=tuple(protocol["initial_path"]), **LIMITS)
    else:
        from asar_repro.window_search import improve_with_windows
        result = improve_with_windows(
            graph, **cfg, initial_path=tuple(protocol["initial_path"]),
            epsilon=epsilon, mode=VARIANTS[variant], window_lengths=WINDOW_LENGTHS,
            seed_max_expansions=SEED_MAX_EXPANSIONS, **LIMITS)
    algorithm_wall_s = perf_counter() - tic  # Includes all seed generation and local work.
    raw_result = json_ready(asdict(result))
    save(folder / "raw_result.json", raw_result)
    require(result.status in ("completed", "budget_exceeded"), "unknown method status")
    require(not result.theory_certified, "full window route / paper baseline cannot be certified")
    require(result.path is not None, "method did not preserve a feasible incumbent")
    if result.status == "budget_exceeded":
        require(result.stop_reason is not None, "budget stop lacks a stop reason")
    if variant != "paper_baseline":
        accounting = verify_accounting(raw_result)
    else:
        require(result.expanded <= LIMITS["max_expansions"], "baseline expansion cap exceeded")
        require(result.peak_open <= LIMITS["max_open"], "baseline OPEN cap exceeded")
        accounting = dict(status="passed", scope="single full-budget paper search")
    replay_started = perf_counter()
    score = score_path(graph, result.path, **cfg)  # Also independently validates every edge.
    check_score(score)
    independent_replay_s = perf_counter() - replay_started
    require(abs(score.J - result.J) <= ATOL, "independent J replay failed")
    if variant != "paper_baseline":
        require(abs(score.pd_final - result.Pd) <= ATOL, "independent Pd replay failed")
    require(score.J <= pt.J + ATOL, "method returned a worse route than its initial PT")
    require(source_fingerprints() == before_sources, "source changed during worker execution")
    memory = psutil.Process().memory_info()
    row = dict(
        raw_result, variant=variant, mode=VARIANTS[variant], epsilon=epsilon, repeat=repeat,
        Pd_T=score.pd_final, replay_J=score.J, replay_error=abs(score.J - result.J),
        replay_Pd=score.pd_final, legal=True, replay_status="passed",
        forcing_kind="historical_real", experiment_label=protocol["experiment_label"],
        particle_sha256=PARTICLE_SHA, protocol_sha256=PROTOCOL_SHA,
        particle_seed=protocol["mission"]["seed"], planner_seed=None,
        PT_J=pt.J, PT_Pd=pt.pd_final, J_minus_PT=score.J - pt.J,
        Pd_minus_PT=score.pd_final - pt.pd_final,
        search_wall_s=algorithm_wall_s, algorithm_wall_s=algorithm_wall_s,
        independent_replay_s=independent_replay_s,
        algorithm_plus_independent_replay_s=algorithm_wall_s + independent_replay_s,
        preprocessing_s=preprocessing_s, worker_wall_s=perf_counter() - started,
        process_peak_memory_mib=getattr(memory, "peak_wset", memory.rss) / 2**20,
        memory_scope="isolated worker process peak working set; includes imports, SHA gate, method and independent replay; excludes controller plots",
        limits=LIMITS, seed_max_expansions=SEED_MAX_EXPANSIONS if variant != "paper_baseline" else None,
        window_lengths=list(WINDOW_LENGTHS) if variant != "paper_baseline" else [],
        accounting=accounting, source_sha256=before_sources,
        input_gate=input_evidence(protocol, pt, times, raw), environment=environment(),
        survival=score.survival.tolist(), cumulative_J=score.g.tolist(),
        guarantee="uncertified full route; completed fixed windows are neighborhood results up to numerical tolerance; no epsilon claim is made",
        timing_scope="external around method; includes all seed work and internal replay; independent final scorer reported separately",
        cooperative_time_cap_overrun_s=max(0.0, algorithm_wall_s - LIMITS["max_seconds"]))
    save(folder / "result.json", row)
    print(json.dumps({key: row[key] for key in (
        "variant", "epsilon", "repeat", "status", "stop_reason", "J", "Pd_T",
        "expanded", "search_wall_s", "process_peak_memory_mib", "theory_certified")},
        allow_nan=False), flush=True)


def launch_worker(folder, item, execution_order):
    folder.mkdir(exist_ok=False)
    command = [sys.executable, str(Path(__file__).resolve()), "worker",
               "--output-dir", str(folder), "--variant", item["variant"],
               "--epsilon", str(item["epsilon"]), "--repeat-index", str(item["repeat"])]
    env = os.environ.copy()
    env.update({key: "1" for key in THREAD_VARIABLES})
    env["PYTHONHASHSEED"] = "0"
    save(folder / "command.json", dict(command=command, cwd=str(ROOT), particle_seed=41,
         execution_order=execution_order, watchdog_s=WATCHDOG_S,
         environment_overrides={key: env[key] for key in (*THREAD_VARIABLES, "PYTHONHASHSEED")}))
    started = perf_counter()
    with (folder / "stdout.txt").open("w", encoding="utf-8") as stdout, \
            (folder / "stderr.txt").open("w", encoding="utf-8") as stderr:
        try:
            process = subprocess.run(command, cwd=ROOT, env=env, stdout=stdout, stderr=stderr,
                                     timeout=WATCHDOG_S, check=False)
        except subprocess.TimeoutExpired:
            save(folder / "watchdog.json", dict(
                **item, status="budget_exceeded", stop_reason="external_watchdog",
                watchdog_s=WATCHDOG_S, theory_certified=False, J=None, Pd_T=None,
                incumbent_source=None, artifact_status="blocked",
                explanation="Worker killed by watchdog; no unrecorded incumbent is inferred."))
            raise
    save(folder / "process.json", dict(exit_code=process.returncode,
         process_wall_s=perf_counter() - started, command=command))
    require(process.returncode == 0, f"worker failed: {folder.name}; inspect stderr and failure.json")
    row = read(folder / "result.json")
    require(all(row[key] == item[key] for key in ("variant", "epsilon", "repeat")),
            "worker identity mismatch")
    require(row["legal"] and row["replay_error"] <= ATOL and not row["theory_certified"],
            "worker replay/certification gate failed")
    row.update(run_id=folder.name, execution_order=execution_order,
               process_wall_s=read(folder / "process.json")["process_wall_s"])
    return row


def csv_file(path, rows, fields=None):
    require(bool(rows), "empty CSV evidence")
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields or list(rows[0]), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list))
                             else value for key, value in row.items()})


def aggregates(rows):
    result = []
    for epsilon in sorted({row["epsilon"] for row in rows}):
        for variant in VARIANTS:
            group = [row for row in rows if row["variant"] == variant and row["epsilon"] == epsilon]
            if not group:
                continue
            row = dict(variant=variant, epsilon=epsilon, runs=len(group),
                completed=sum(r["status"] == "completed" for r in group),
                budget_exceeded=sum(r["status"] == "budget_exceeded" for r in group),
                stop_reasons=dict(Counter(r["stop_reason"] or "none" for r in group)),
                incumbent_sources=dict(Counter(r["incumbent_source"] or "none" for r in group)),
                distinct_paths=len({tuple(r["path"]) for r in group}), theory_certified=False)
            for field in ("J", "Pd_T", "expanded", "generated", "pruned", "peak_open",
                          "search_wall_s", "independent_replay_s", "algorithm_plus_independent_replay_s",
                          "process_peak_memory_mib"):
                values = [r[field] for r in group]
                row[field + "_median"] = median(values)
                row[field + "_min"] = min(values)
                row[field + "_max"] = max(values)
            result.append(row)
    return result


def paired_rows(rows):
    pairs = []
    index = {(r["variant"], r["epsilon"], r["repeat"]): r for r in rows}
    for row in rows:
        if row["variant"] == "paper_baseline":
            continue
        references = ["paper_baseline"]
        if row["variant"] == "window_stdc_endpoint_lb":
            references += ["window_zero", "window_mass_lb", "window_stdc_lb"]
        for reference in references:
            baseline = index.get((reference, row["epsilon"], row["repeat"]))
            if baseline is None:
                continue  # Extra endpoint epsilon=1 smoke is not a paired claim.
            pairs.append(dict(variant=row["variant"], baseline=reference,
                epsilon=row["epsilon"], repeat=row["repeat"],
                delta_J=row["J"] - baseline["J"],
                J_reduction_percent=100 * (baseline["J"] - row["J"]) / baseline["J"]
                    if baseline["J"] > 0 else None,
                delta_Pd=row["Pd_T"] - baseline["Pd_T"],
                delta_Pd_percentage_points=100 * (row["Pd_T"] - baseline["Pd_T"]),
                J_improved=row["J"] < baseline["J"] - ATOL,
                J_worse=row["J"] > baseline["J"] + ATOL,
                Pd_improved=row["Pd_T"] > baseline["Pd_T"] + ATOL,
                Pd_worse=row["Pd_T"] < baseline["Pd_T"] - ATOL,
                delta_expanded=row["expanded"] - baseline["expanded"],
                time_ratio=row["search_wall_s"] / baseline["search_wall_s"],
                delta_peak_memory_mib=row["process_peak_memory_mib"] - baseline["process_peak_memory_mib"],
                variant_status=row["status"], variant_stop_reason=row["stop_reason"],
                baseline_status=baseline["status"], baseline_stop_reason=baseline["stop_reason"]))
    return pairs


def plots(folder, rows, aggregate):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    protocol, grid, cfg, _, _, _ = load_real()  # Gate before displaying any real particle-derived map.
    mass = cfg["motion"].cell_mass(cfg["p"], 0)[:grid.size].reshape(grid.rows, grid.cols)
    selected = [r for r in rows if r["epsilon"] == 1.1 and r["repeat"] == 0]
    require(len(selected) == len(VARIANTS), "missing epsilon=1.1 repeat=0 plot controls")
    fig, axes = plt.subplots(2, 3, figsize=(14, 9), constrained_layout=True)
    for ax, row in zip(axes.flat, selected):
        ax.imshow(mass, cmap="Blues", vmin=0, vmax=max(float(mass.max()), 1e-15))
        vertices = np.asarray(row["path"])
        ax.plot(vertices % grid.cols, vertices // grid.cols, "o-", ms=2, lw=1.2,
                color=COLORS[row["variant"]])
        ax.scatter(cfg["start"] % grid.cols, cfg["start"] // grid.cols,
                   marker="*", s=90, c="gold", edgecolors="black", zorder=5)
        ax.set_title(f"{LABELS[row['variant']]}\nJ={row['J']:.6f}, Pd={row['Pd_T']:.6f}\n"
                     f"{row['status']} / {row['stop_reason'] or 'none'}", fontsize=9)
        ax.set_xlabel("Grid column"); ax.set_ylabel("Grid row")
    axes.flat[-1].axis("off")
    axes.flat[-1].text(.03, .95, "Frozen real Lake Ontario particles\n"
        "epsilon=1.1, repeat 0; all full routes uncertified\n"
        "Background: initial searchable-cell mass\n"
        "Special-bin mass remains in every score\n"
        "All-water discrete approximation\n"
        "Same objective, forcing, PT and total caps\n"
        "Window seed generation is included", va="top", fontsize=10,
        transform=axes.flat[-1].transAxes)
    fig.savefig(folder / "paths.png", dpi=170); plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    for row in selected:
        ax.plot(np.arange(len(row["survival"])), row["survival"],
                color=COLORS[row["variant"]], label=LABELS[row["variant"]])
    ax.set(xlabel="Absolute step t (no observation at t=0)", ylabel="Remaining undetected mass M(t)",
           title="Independent replay; frozen real particles; epsilon=1.1, repeat 0")
    ax.grid(alpha=.25); ax.legend(fontsize=8)
    fig.savefig(folder / "survival.png", dpi=170); plt.close(fig)

    chosen = [r for r in aggregate if r["epsilon"] == 1.1]
    fig, axes = plt.subplots(2, 3, figsize=(15, 9), constrained_layout=True)
    for ax, (field, title) in zip(axes.flat, (
        ("J", "J (lower is better)"), ("Pd_T", "Pd(T) (higher is better)"),
        ("search_wall_s", "Method wall time including seed (s)"),
        ("expanded", "Total expanded nodes including seed"),
        ("process_peak_memory_mib", "Isolated process peak memory (MiB)"),
        ("independent_replay_s", "Final independent replay (s)"))):
        values = np.array([r[field + "_median"] for r in chosen])
        errors = np.array([[r[field + "_median"] - r[field + "_min"] for r in chosen],
                           [r[field + "_max"] - r[field + "_median"] for r in chosen]])
        ys = np.arange(len(chosen))
        ax.barh(ys, values, xerr=errors, capsize=2, color=[COLORS[r["variant"]] for r in chosen])
        ax.set_yticks(ys, [LABELS[r["variant"]] + (" *" if r["budget_exceeded"] else "") for r in chosen], fontsize=8)
        ax.invert_yaxis(); ax.grid(axis="x", alpha=.2); ax.set_axisbelow(True); ax.set_title(title, fontsize=10)
    fig.suptitle("Same total-budget protocol, epsilon=1.1; median and min-max\n"
                 "* Includes budget-stop results; no full-route epsilon certification", fontsize=11)
    fig.savefig(folder / "efficiency.png", dpi=170); plt.close(fig)


def generate_report(folder, data):
    rows, experiment_plan = data["rows"], data["plan"]
    require(len(rows) == experiment_plan["planned_runs"], "incomplete experiment cannot produce a passed report")
    for row in rows:
        require(row["legal"] and row["replay_error"] <= ATOL and not row["theory_certified"],
                "report replay/certificate gate failed")
    aggregate, pairs = aggregates(rows), paired_rows(rows)
    save(folder / "aggregate.json", dict(aggregate=aggregate, pairs=pairs))
    csv_file(folder / "metrics.csv", rows, fields=[
        "run_id", "variant", "mode", "epsilon", "repeat", "forcing_kind", "particle_seed",
        "J", "Pd_T", "J_minus_PT", "Pd_minus_PT", "expanded", "generated", "pruned", "peak_open",
        "search_wall_s", "independent_replay_s", "algorithm_plus_independent_replay_s",
        "preprocessing_s", "worker_wall_s", "process_wall_s", "process_peak_memory_mib",
        "status", "stop_reason", "completion_reason", "incumbent_source", "theory_certified",
        "replay_error", "legal", "particle_sha256", "protocol_sha256", "cooperative_time_cap_overrun_s"])
    csv_file(folder / "aggregate.csv", aggregate)
    csv_file(folder / "paired_comparisons.csv", pairs)
    plots(folder, rows, aggregate)
    comparisons = [pair for pair in pairs if pair["baseline"] == "paper_baseline"]
    endpoint = [pair for pair in comparisons if pair["variant"] == "window_stdc_endpoint_lb"]
    endpoint_improved = sum(pair["J_improved"] for pair in endpoint)
    endpoint_pd_improved = sum(pair["Pd_improved"] for pair in endpoint)
    lines = [
        "# 固定后缀窗口搜索：J/Pd 同预算验证", "",
        f"实验阶段：`{experiment_plan['stage']}`；计划/实际运行：{experiment_plan['planned_runs']}/{len(rows)}。",
        "本报告是新研究协议的本地数值结果；原 B7 配置、归档、评价器和历史结果保持只读。", "",
        f"endpoint STDC 相对 paper baseline：{len(endpoint)} 组配对中，J 改善 {endpoint_improved} 组，"
        f"Pd 改善 {endpoint_pd_improved} 组。",
        ("在本次配对实验中没有验证到 endpoint STDC 的 J 改善；不能宣称核心目标获得提升。"
         if not endpoint_improved else
         "本次数据验证到了部分 endpoint STDC 的 J 改善；须结合所有配对、预算状态与控制方法判断收益来源，不能外推到其他场景。"),
        "J 是唯一优化目标；Pd 独立报告。J 降低不自动意味着终点 Pd 上升；表中保留可能的取舍。",
        "Smoke 仅为运行与评分检查；三次重复使用同一冻结输入，主要用于观察时间变化，不是三个独立场景。", "",
        "## 同数据、同总预算与计时", "",
        f"每方法总 cap：expanded={LIMITS['max_expansions']}，OPEN={LIMITS['max_open']}，wall={LIMITS['max_seconds']} s。",
        f"paper baseline 直接使用全部 cap。四个窗口控制方法均先支付 paper seed（最多 {SEED_MAX_EXPANSIONS} 次展开），"
        f"再使用剩余共享预算，窗口长度为 {list(WINDOW_LENGTHS)}。",
        "冻结 PT 是各方法共用的已有输入；本实验不重新生成历史 PT。计入预算的种子成本指 paper A^SAR 搜索及其内部处理。",
        "ε 控制 paper A^SAR 种子/直接基线；局部窗口按未加权下界排序并在预算内求改进，不将 ε 解释为完整路线保证。",
        "seed 的展开子配额用完允许继续局部搜索；全局时间或 OPEN 中止则不能继续。所有 seed/window 节点计数逐项核对。",
        "方法时间从调用前到返回后外部测量，包含种子生成、内部评分和局部搜索；最终独立全路径重放另列。"
        "SHA 预检与进程启动另列。时间上限为合作式检查，超额时间如实记录。",
        "每条运行在新进程中执行，线程设为 1；峰值内存包含导入、预检、算法和重放。stdout/stderr、命令与退出码逐运行保存。", "",
        "## 输入与保证范围", "",
        f"输入标记：`historical_real`；粒子 SHA-256：`{PARTICLE_SHA}`。",
        f"冻结输入协议 SHA-256：`{PROTOCOL_SHA}`。每次 worker 重查 forcing、粒子、元数据、UTC 与评价器 SHA。",
        "使用已有 B3 真实历史粒子归档；未调用漂移模型重生成，未用合成粒子替换。场景仍采用冻结的 all-water 离散近似。",
        "paper_greedy 在动态场景无可采纳保证。全部完整路线 `theory_certified=false`。"
        "局部下界仅对应固定终点、固定时刻、固定后缀及相应模型假设；局部搜索正常结束不等于全路径 ε 最优。",
        "所有预算中止保留可行 incumbent、来源和 stop_reason。`completed` 表示该方法协议正常返回，不能解释为全局最优。", "",
        "## 核心指标（中位数；范围保存在 aggregate.csv）", "",
        "|方法|ε|次数|J ↓|Pd ↑|方法秒数|展开总数|正常/预算中止|",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in aggregate:
        lines.append(f"|{row['variant']}|{row['epsilon']:g}|{row['runs']}|{row['J_median']:.9f}|"
                     f"{row['Pd_T_median']:.9f}|{row['search_wall_s_median']:.4f}|"
                     f"{row['expanded_median']:g}|{row['completed']}/{row['budget_exceeded']}|")
    lines += ["", "## 收益归因限制", "",
        "`window_zero`、`window_mass_lb`、`window_stdc_lb` 与 `window_stdc_endpoint_lb` 使用相同窗口调度、初始 PT 和 seed 子预算。"
        "与 paper baseline 的差值反映整个窗口方法；endpoint 与其余窗口控制的差值更接近下界设计的贡献。"
        "不能将所有窗口改进归功于 STDC。", "",
        "|对照|J 改善/配对数|J 变差|Pd 改善|Pd 变差|", "|---|---:|---:|---:|---:|"]
    for baseline in ("paper_baseline", "window_zero", "window_mass_lb", "window_stdc_lb"):
        group = [p for p in pairs if p["variant"] == "window_stdc_endpoint_lb" and p["baseline"] == baseline]
        lines.append(f"|endpoint STDC vs {baseline}|{sum(p['J_improved'] for p in group)}/{len(group)}|"
                     f"{sum(p['J_worse'] for p in group)}|{sum(p['Pd_improved'] for p in group)}|"
                     f"{sum(p['Pd_worse'] for p in group)}|")
    lines += ["", "## 图与审计文件", "", "![路径](paths.png)", "", "![剩余质量](survival.png)", "",
              "![效率](efficiency.png)", "", "- `metrics.csv` / `results.json`：全部运行及完整轨迹、状态、来源。",
              "- `paired_comparisons.csv`：逐 ε、逐重复配对 J/Pd 和控制组差值。",
              "- `plan.json` / `input_gate.json`：新协议和真实输入 SHA。",
              "- `source_manifest.json` / `source_snapshot/` / `git_diff.patch`：源码和工作树证据。",
              "- `validation_evidence.json`：新测、历史测试及 toy Oracle 前置门槛证据。",
              "- 各 worker 目录：command、stdout、stderr、raw_result、独立 replay 与计数核对。", ""]
    (folder / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return dict(paired_endpoint_runs=len(endpoint), endpoint_J_improved=endpoint_improved,
                endpoint_Pd_improved=endpoint_pd_improved,
                any_window_J_improved=sum(pair["J_improved"] for pair in comparisons))


def artifact_manifest(folder):
    files = [path for path in sorted(folder.rglob("*")) if path.is_file()
             and path.name != "artifact_manifest.json"]
    save(folder / "artifact_manifest.json", dict(
        files=[dict(path=path.relative_to(folder).as_posix(), bytes=path.stat().st_size,
                    sha256=digest(path)) for path in files]))


def verify_artifacts(folder):
    manifest = read(folder / "artifact_manifest.json")
    require(bool(manifest.get("files")), "missing artifact fingerprints")
    for item in manifest["files"]:
        path = (folder / item["path"]).resolve()
        require(path.is_relative_to(folder), "artifact path outside experiment directory")
        require(path.is_file() and path.stat().st_size == item["bytes"]
                and digest(path) == item["sha256"], "artifact SHA mismatch: " + item["path"])


def controller(stage, folder, validation_path=None, smoke_folder=None):
    require(not folder.exists(), "refusing overwrite: output directory must be new")
    folder.mkdir(parents=True, exist_ok=False)
    summary = dict(status="running", stage=stage,
                   started_utc=datetime.now(timezone.utc).isoformat(), runs=0)
    rows = []
    started = perf_counter()
    save(folder / "summary.json", summary)
    save(folder / "invocation.json", dict(command=[sys.executable, *sys.argv], cwd=str(Path.cwd()),
         started_utc=summary["started_utc"]))
    try:
        fingerprints = snapshot(folder)
        protocol, _, _, pt, times, raw = load_real()
        save(folder / "input_gate.json", input_evidence(protocol, pt, times, raw))
        if stage == "smoke":
            validation = validate_gate(validation_path)
        else:
            require(smoke_folder is not None, "--smoke-dir is required before benchmark")
            verify_artifacts(smoke_folder)
            smoke = read(smoke_folder / "summary.json")
            require(smoke.get("status") == "passed" and smoke.get("runs") == 6,
                    "six smoke runs must pass before benchmark")
            smoke_plan = read(smoke_folder / "plan.json")
            require(smoke_plan["stage"] == "smoke", "invalid smoke protocol")
            require(read(smoke_folder / "source_manifest.json")["sha256"] == fingerprints,
                    "sources changed after smoke; rerun smoke")
            validation = read(smoke_folder / "validation_evidence.json")
            require(digest(Path(validation["path"])) == validation["sha256"],
                    "original validation evidence changed after smoke")
            require(validate_gate(Path(validation["path"])) == validation,
                    "validation source evidence changed after smoke")
            save(folder / "smoke_evidence.json", dict(path=str(smoke_folder),
                 summary=smoke, summary_sha256=digest(smoke_folder / "summary.json")))
        save(folder / "validation_evidence.json", validation)
        experiment_plan = plan(stage, protocol, validation)
        save(folder / "plan.json", experiment_plan)
        for item in experiment_plan["schedule"]:
            name = f"{item['variant']}_eps_{str(item['epsilon']).replace('.', 'p')}_rep_{item['repeat']}"
            row = launch_worker(folder / name, item, len(rows))
            require(row["source_sha256"] == fingerprints, "source identity changed between workers")
            rows.append(row)
            save(folder / "results.json", dict(status="running", plan=experiment_plan, rows=rows))
            print(f"[{len(rows):02d}/{experiment_plan['planned_runs']}] {name}: "
                  f"{row['status']} / {row['stop_reason']}; J={row['J']:.9f}; "
                  f"Pd={row['Pd_T']:.9f}; expanded={row['expanded']}; wall={row['search_wall_s']:.3f}s",
                  flush=True)
        require(len(rows) == experiment_plan["planned_runs"], "missing experiment runs")
        require(source_fingerprints() == fingerprints, "sources changed during experiment")
        data = dict(status="passed", plan=experiment_plan, rows=rows)
        save(folder / "results.json", data)
        conclusion = generate_report(folder, data)
        summary.update(status="passed", runs=len(rows),
                       completed=sum(r["status"] == "completed" for r in rows),
                       budget_exceeded=sum(r["status"] == "budget_exceeded" for r in rows),
                       certified_full_routes=0, conclusion=conclusion)
    except Exception as exc:
        summary.update(status="blocked", runs=len(rows), error=str(exc), traceback=traceback.format_exc())
        (folder / "blocked.md").write_text(
            f"blocked\n\n{exc}\n\n实验停止；保留已完成的运行，不生成完成结论。\n", encoding="utf-8")
        raise
    finally:
        summary["wall_s"] = perf_counter() - started
        save(folder / "summary.json", summary)
        artifact_manifest(folder)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("smoke", "benchmark", "worker"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--validation-evidence", type=Path)
    parser.add_argument("--smoke-dir", type=Path)
    parser.add_argument("--variant", choices=tuple(VARIANTS))
    parser.add_argument("--epsilon", type=float, default=1.1)
    parser.add_argument("--repeat-index", type=int, default=0)
    args = parser.parse_args()
    folder = args.output_dir.resolve()
    require(folder.is_relative_to(ROOT / "outputs/stdc_v0_2")
            and folder != ROOT / "outputs/stdc_v0_2", "new research output subdirectory required")
    if args.stage == "worker":
        require(folder.is_dir(), "worker output directory must be created by controller")
        require(not any((folder / name).exists() for name in
                        ("result.json", "raw_result.json", "failure.json", "watchdog.json")),
                "refusing to overwrite an attempted worker run")
        try:
            worker(folder, args.variant, args.epsilon, args.repeat_index)
        except Exception as exc:
            save(folder / "failure.json", dict(status="blocked", error=str(exc),
                 traceback=traceback.format_exc(), variant=args.variant, epsilon=args.epsilon,
                 repeat=args.repeat_index, theory_certified=False))
            raise
    else:
        controller(args.stage, folder, args.validation_evidence,
                   args.smoke_dir.resolve() if args.smoke_dir else None)


if __name__ == "__main__":
    main()
