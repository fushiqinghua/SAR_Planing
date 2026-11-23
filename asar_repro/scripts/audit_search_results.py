"""B4: small Oracle benchmarks and read-only reclassification of frozen v1.0 results."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import subprocess
from time import perf_counter

from matplotlib.figure import Figure
import numpy as np

from asar_repro.grid import GridGraph
from asar_repro.heuristic import Heuristic
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.oracle import enumerate_oracle
from asar_repro.scenario_baselines import parallel_track
from asar_repro.scenarios import config_digest, digest
from asar_repro.search import SearchResult, search_asar
from asar_repro.search_reporting import (
    REQUIRED_FIELDS,
    environment_versions,
    search_record,
    summarize_records,
)

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def write_csv(path, rows):
    fields = REQUIRED_FIELDS + sorted(set().union(*(r.keys() for r in rows)) - set(REQUIRED_FIELDS))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    k: (
                        json.dumps(v, ensure_ascii=False, allow_nan=False)
                        if isinstance(v, (dict, list)) or v is None
                        else v
                    )
                    for k, v in row.items()
                }
            )


def toy_case(name):
    if name == "appendix_b":
        with np.load(
            ROOT / "data/fixtures/heuristic_dynamic_counterexample.npz", allow_pickle=False
        ) as a:
            return GridGraph(3, 3), a["p"], a["P"], 4, 5
    if name == "dynamic_suboptimal":
        rng = np.random.default_rng(213)
        p = rng.dirichlet(np.full(4, 0.5))
        matrices = rng.dirichlet(np.full(4, 0.4), size=(4, 4))
        return GridGraph(2, 2), p, matrices, 0, 213
    if name == "static":
        return (
            GridGraph(2, 2),
            np.array([0.1, 0.2, 0.3, 0.4]),
            np.repeat(np.eye(4)[None], 4, axis=0),
            0,
            None,
        )
    raise ValueError(f"unknown audit case: {name}")


def benchmark(spec, config_path, output, provenance):
    rows, witnesses = [], {}
    for name in spec["cases"]:
        graph, p, matrices, start, seed = toy_case(name)
        archive = output / f"{name}_input.npz"
        np.savez_compressed(archive, p=p, P=matrices, start=start, T=4, q=0.78)
        args = dict(start=start, budget=4, p=p, q=0.78, motion=MatrixMotion.time_varying(matrices))
        oracle_started = perf_counter()
        exact = enumerate_oracle(graph, **args)
        oracle_s = perf_counter() - oracle_started
        h = Heuristic(graph, budget=4, q=0.78, motion=args["motion"], mode="paper_greedy")(
            start, 0, p
        )
        witnesses[name] = dict(
            oracle_J=exact.J,
            oracle_path=list(exact.path),
            root_paper_greedy=h,
            root_overestimate=h - exact.J,
            complete_paths=exact.complete_paths,
        )
        for mode in spec["heuristics"]:
            for epsilon in spec["epsilon"]:
                for profile, options in spec["profiles"].items():
                    limits = {
                        k: options.get(k) for k in ("max_expansions", "max_open", "max_seconds")
                    }
                    warm = options["warm_start"]
                    started = perf_counter()
                    initial = parallel_track(graph, **args) if warm else None
                    warm_s = perf_counter() - started if warm else 0.0
                    started = perf_counter()
                    result = search_asar(
                        graph,
                        **args,
                        heuristic=mode,
                        epsilon=epsilon,
                        initial_path=initial,
                        prune=options["prune"],
                        **limits,
                    )
                    elapsed = perf_counter() - started
                    identity = dict(
                        case=name,
                        profile=profile,
                        heuristic=mode,
                        epsilon=epsilon,
                        options=options,
                        input_sha256=digest(archive),
                        config=spec,
                    )
                    context = dict(
                        provenance,
                        scenario_id=name,
                        forcing_kind="toy",
                        source_manifest_sha256=digest(config_path),
                        seed=seed,
                        config_hash=config_digest(identity),
                    )
                    row = search_record(
                        result,
                        graph,
                        **args,
                        planner_wall_s=elapsed,
                        warm_start_s=warm_s,
                        limits=limits,
                        provenance=context,
                        initial_source="ParallelTrack",
                    )
                    error = None if row["J"] is None else row["J"] - exact.J
                    within = (
                        None
                        if row["J"] is None
                        else row["J"] <= epsilon * exact.J + spec["comparison_atol"]
                    )
                    if row["discrete_model_certified"] and not within:
                        raise AssertionError("certified result violates Oracle epsilon inequality")
                    row.update(
                        profile=profile,
                        prune=options["prune"],
                        oracle_J=exact.J,
                        J_minus_oracle=error,
                        observed_within_epsilon=within,
                        oracle_wall_s=oracle_s,
                        matrix_archive_sha256=digest(archive),
                        numerical_check_atol=spec["comparison_atol"],
                    )
                    rows.append(row)
    return rows, witnesses


def audit_legacy():
    """Replay all 32 saved searches; never rerun drift, search, or overwrite old reports."""
    rows, sources = [], []
    for file in sorted((ROOT / "outputs/stage7").glob("*/results.json")):
        report = json.loads(file.read_text(encoding="utf-8"))
        meta = report["metadata"]
        archive = ROOT / meta["archive"].replace("\\", "/")
        if digest(archive) != meta["archive_sha256"]:
            raise ValueError("legacy particle archive hash mismatch")
        graph = GridGraph(*meta["drift_config"]["grid_rows_cols"])
        with np.load(archive, allow_pickle=False) as data:
            motion = ParticleMotion(data["cell_ids"], graph.size, data["trajectory_id"])
            p = data["initial_weights"]
        pt = next(r for r in report["runs"] if r["method"] == "ParallelTrack")
        sources.append(
            dict(
                path=str(file.relative_to(ROOT)),
                sha256=digest(file),
                particle_archive_sha256=digest(archive),
            )
        )
        for old in report["runs"]:
            if old["method"] != "ASAR_paper":
                continue
            if old["forcing_kind"] != "constant_synthetic" or old["certified"]:
                raise ValueError("unexpected legacy forcing or certification")
            result = SearchResult(
                tuple(old["path"]),
                old["J"],
                old["expanded"],
                old["generated"],
                old["pruned"],
                old["peak_open"],
                "paper_greedy",
                old["epsilon"],
                False,
                old["status"],
                old["stop_reason"],
                old["incumbent_source"],
            )
            context = dict(
                scenario_id=old["scenario"],
                forcing_kind=old["forcing_kind"],
                particle_archive_sha256=digest(archive),
                config_hash=old["config_hash"],
                seed=old["drift_seed"],
                source_manifest_sha256=digest(file),
                environment_versions={
                    "opendrift": meta["opendrift_version"],
                    "other_versions": "not recorded per legacy run",
                },
            )
            row = search_record(
                result,
                graph,
                start=old["start"],
                budget=old["T"],
                p=p,
                q=old["q"],
                motion=motion,
                planner_wall_s=old["planner_wall_s"],
                warm_start_s=old["warm_start_s"],
                limits=meta["search_limits"],
                provenance=context,
            )
            if abs(row["Pd_T"] - old["Pd_T"]) > 1e-10 or abs(row["M_T"] - old["M_T"]) > 1e-10:
                raise AssertionError("legacy mass replay differs")
            if row["incumbent_source"] == "ParallelTrack" and (
                row["path"] != pt["path"] or row["J"] != pt["J"]
            ):
                raise AssertionError("legacy PT source does not match PT path/value")
            row.update(
                J_over_PT=row["J"] / pt["J"],
                reference_kind="local_dynamic_ParallelTrack",
                original_result_file=str(file.relative_to(ROOT)),
                source_manifest_kind="frozen_legacy_result_json",
                legacy_replay_error=abs(row["J"] - old["J"]),
                paper_cpp_m1pro_s=old["paper_cpp_s"],
                execution_git_commit_unrecorded=True,
            )
            rows.append(row)
    counts = Counter(r["search_status"] for r in rows)
    if len(rows) != 32 or counts["budget_exceeded"] != 17:
        raise AssertionError("frozen 17/32 history changed")
    return rows, sources


def status_plot(rows, output):
    fig = Figure(figsize=(9, 4.5), layout="constrained")
    axes = fig.subplots(1, 2)
    names = sorted({r["scenario_id"] for r in rows})
    labels = [n.replace("_", "\n") for n in names]
    for ax, state, color, title in zip(
        axes,
        ("completed_search", "aborted_feasible_incumbent"),
        ("#29836d", "#bd5526"),
        ("Completed search (15/32)", "Aborted incumbent (17/32)"),
        strict=True,
    ):
        counts = [
            sum(r["scenario_id"] == n and r["result_class"] == state for r in rows) for n in names
        ]
        bars = ax.bar(labels, counts, color=color)
        ax.bar_label(bars)
        ax.set(title=title, ylabel="Runs", ylim=(0, 9))
    fig.suptitle("Frozen v1.0 constant-synthetic runs | paper_greedy | no discrete certificate")
    fig.savefig(output, dpi=150)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/b4_search_audit.json")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/baseline_v1.1/b4")
    parser.add_argument("--heuristic", choices=("zero", "mass_lb", "paper_greedy"), nargs="+")
    opts = parser.parse_args()
    spec = json.loads(opts.config.read_text(encoding="utf-8"))
    if opts.heuristic:
        spec["heuristics"] = opts.heuristic
    output = opts.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    code_paths = [
        ROOT / "src/asar_repro" / f"{name}.py"
        for name in (
            "search",
            "heuristic",
            "search_reporting",
            "planner_adapter",
            "objective",
            "motion",
            "scenario_baselines",
        )
    ]
    code_paths += [Path(__file__).resolve(), opts.config.resolve()]
    provenance = dict(git_commit=commit, environment_versions=environment_versions())
    rows, witnesses = benchmark(spec, opts.config, output, provenance)
    legacy, sources = audit_legacy()
    audit = dict(
        stage="B4",
        status="passed",
        config=spec,
        git_commit=commit,
        git_commit_scope="base HEAD; exact executing source is identified by code_sha256",
        code_sha256={str(p.relative_to(ROOT)): digest(p) for p in code_paths},
        environment_versions=provenance["environment_versions"],
        toy_run_count=len(rows),
        toy_groups=summarize_records(rows),
        witnesses=witnesses,
        legacy_run_count=len(legacy),
        legacy_groups=summarize_records(legacy),
        legacy_sources=sources,
        legacy_stop_reasons=dict(Counter(r["stop_reason"] for r in legacy if r["stop_reason"])),
        legacy_max_replay_error=max(r["legacy_replay_error"] for r in legacy),
        new_historical_forcing_planning_runs=0,
        actual_timeout_tests="Deterministic injected clock in pytest; toy abort profiles use max_seconds=0",
        scope="B4 semantics only; B5 profile/budget sweep and B6 real comparisons not run",
    )
    write_json(output / "audit.json", audit)
    write_json(output / "toy_runs.json", rows)
    write_csv(output / "toy_metrics.csv", rows)
    write_json(output / "legacy_runs.json", legacy)
    write_csv(output / "legacy_metrics.csv", legacy)
    status_plot(legacy, output / "legacy_status.png")
    appendix = witnesses.get("appendix_b", {})
    lines = [
        "# B4 搜索结果语义核验",
        "",
        "状态：passed。只执行小规模 Oracle 对照与旧结果重放。",
        "",
        f"本次 toy 记录 {len(rows)} 条；历史 32 条：正常完成 15，中止 17（均 max_expansions）。",
        "17 条中止路线的来源均为 ParallelTrack，J 属于本地 PT，不能写成搜索改进。",
        "历史全部使用 constant_synthetic；本次没有新增真实历史 forcing 的规划成绩。",
        "",
        "| toy | heuristic | profile | ε | J | J−Oracle | status | source | certified |",
        "|---|---|---|---:|---:|---:|---|---|---|",
    ]
    for r in rows:
        lines.append(
            "| "
            + " | ".join(
                str(r[k])
                for k in (
                    "scenario_id",
                    "heuristic",
                    "profile",
                    "epsilon",
                    "J",
                    "J_minus_oracle",
                    "search_status",
                    "incumbent_source",
                    "discrete_model_certified",
                )
            )
            + " |"
        )
    lines += [
        "",
        "## 适用边界",
        "",
        f"3×3、T=4、q=.78 反例：paper_greedy 根启发值 {appendix.get('root_paper_greedy')}，Oracle {appendix.get('oracle_J')}。",
        "另一个动态 toy 的 ε=1 次优路径在 toy_metrics.csv 中保留。以上是当前离散约定下的证据，不能外推为原论文在所有海洋场景无效。",
        "zero/mass_lb 只有在离散模型前提成立且完成搜索时获得条件性 ε 界。浮点测试不是对所有实例的形式证明。",
        "paper_greedy 无论完成或与 Oracle 偶然一致，均不标记离散认证。",
        "",
        "本地 J_over_PT 的分母为本地动态 ParallelTrack，不能标成 % of optimum。",
        "legacy_metrics.csv 把原论文 C++ / M1 Pro 时间单列为 paper_cpp_m1pro_s；本地 Python/Windows 的 planner_wall_s 与 warm_start_s 分列。没有跨机器加速比。",
        "规划时间不含数据、OpenDrift、评分重放、Oracle 与作图；总计时间为 warm_start_s + planner_wall_s。旧环境未逐次记录的字段为未知，不用当前版本补造。",
        "真实环境阶段将使用论文任务参数的真实历史环境重建；原作者模式循环、地图、粒子与人工 PT 尚未逐点复现。",
        "",
        "![旧运行按完成状态分栏](legacy_status.png)",
        "",
        "源文件指纹、环境、输入配置及完整结果见 audit.json、toy_runs.json、legacy_runs.json。",
        "下一阶段 B5：冻结输入上的有限预算扫描与 profile，本轮未实施。",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: audit[k]
                for k in (
                    "status",
                    "toy_run_count",
                    "legacy_run_count",
                    "legacy_stop_reasons",
                    "legacy_max_replay_error",
                )
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
