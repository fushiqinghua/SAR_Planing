"""Build the stage 8 reports and portable planning bundle from recorded experiments."""

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re
import shutil
from tempfile import TemporaryDirectory
from uuid import uuid4

from matplotlib.figure import Figure
import numpy as np

from asar_repro.scenarios import config_digest, digest
from stage8_metrics import FIELDS, collect, read_json


ROOT = Path(__file__).resolve().parents[1]


def table(headings, records):
    def line(values):
        return "| " + " | ".join(str(v).replace("|", "\\|") for v in values) + " |"

    return "\n".join([line(headings), line(["---"] * len(headings)), *(line(r) for r in records)])


def bundle_inputs(missions, destination):
    destination.mkdir(parents=True)
    bundle = {"format_version": 1, "scenarios": {}}
    for name, mission in missions.items():
        m = mission["metadata"]
        checksum = m["archive_sha256"]
        filename = f"{name}_{checksum[:12]}.npz"
        shutil.copyfile(mission["archive"], destination / filename)
        if digest(destination / filename) != checksum:
            raise ValueError("particle archive changed while copying")
        start = mission["runs"][0]["start"]
        entry = {
            k: m[k]
            for k in (
                "name",
                "archive_sha256",
                "drift_config_hash",
                "drift_config",
                "special_bins",
                "object_resolved",
                "opendrift_version",
                "paper_source",
                "paper_url",
                "wind",
                "current",
                "data_availability",
                "search_limits",
                "q",
            )
        }
        entry.update(archive=filename, start_vertex=start)
        bundle["scenarios"][name] = dict(entry, metadata_sha256=config_digest(entry))
    (destination / "manifest.json").write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def performance_plot(missions, output):
    fig = Figure(figsize=(13, 4.5), layout="constrained")
    axes = fig.subplots(1, 3)
    for (name, mission), color in zip(
        missions.items(), ("#116997", "#bd5526", "#29836d", "#795799"), strict=True
    ):
        runs = [r for r in mission["runs"] if r["method"] == "ASAR_paper"]
        for ax, metric in zip(axes, ("J_over_PT", "planner_wall_s", "expanded"), strict=True):
            values = [r[metric] for r in runs]
            ax.plot(range(len(runs)), values, color=color, lw=1.3, label=mission["metadata"]["name"])
            for i, r in enumerate(runs):
                ax.plot(
                    i,
                    values[i],
                    "o",
                    ms=5,
                    mec=color,
                    mfc=color if r["status"] == "completed" else "white",
                )
            ax.set_xticks(range(len(runs)), [f"{r['epsilon']:g}" for r in runs], rotation=35)
    axes[0].axhline(1, color="#555", lw=0.7, ls="--")
    axes[1].set_yscale("log")
    axes[0].legend(fontsize=8)
    for ax, label in zip(
        axes, ("J / J(ParallelTrack)", "Planner wall time (s, log scale)", "Expanded nodes")
    ):
        ax.set(xlabel="Search weight ε", ylabel=label)
        ax.grid(axis="y", alpha=0.2)
    fig.suptitle(
        "Four constant-forcing missions  |  ASAR_paper\nFilled: completed   ·   Open: budget stop"
    )
    fig.savefig(output, dpi=155)


def comparison(missions, validity, rows, paper_tables):
    task_rows, time_rows, case_rows = [], [], []
    for name, mission in missions.items():
        m = mission["metadata"]
        published = paper_tables["scenarios"][name]
        for key, value in published.items():
            if m[key] != value:
                raise ValueError(f"{name}: archived {key}={m[key]!r} differs from local PDF {value!r}")
        cfg = m["drift_config"]
        runs = mission["runs"]
        task_rows.append(
            (
                m["name"],
                f"{m['object']} / {m['object_resolved']['key']}",
                f"{m['lkp_lon_lat']} · {m['incident_utc']}",
                f"{m['csp_lon_lat']} · {m['cst_utc']}",
                f"{m['wind']} / {m['current']}",
                f"{m['sweep_width_nm']} / {m['budget']}",
                f"{cfg['cell_width_m']:g} / {cfg['step_s']:g} / {m['predrift_hours']:g}",
            )
        )
        asar = [r for r in runs if r["method"] == "ASAR_paper"]
        for r, eps, paper in zip(asar, paper_tables["epsilon"], published["table_ii_s"], strict=True):
            if r["epsilon"] != eps or r["paper_cpp_s"] != paper:
                raise ValueError(f"{name}: mismatched Table II reference")
            time_rows.append(
                (
                    m["name"],
                    f"{r['epsilon']:g}",
                    f"{paper:.2f}",
                    f"{r['planner_wall_s']:.4f}",
                    r["expanded"],
                    r["status"],
                    r["stop_reason"] or "—",
                    r["incumbent_source"],
                )
            )
        ref = next(r for r in asar if r["epsilon"] == 1.1)
        pt = next(r for r in runs if r["method"] == "ParallelTrack")
        lo, hi = m["aco_median_J_ci99"]
        case_rows.append(
            (
                m["name"],
                f"{pt['J']:.6f}",
                f"{ref['J']:.6f}",
                f"{ref['Pd_T']:.4%}",
                f"{m['aco_median_J']:.6f} [{lo:.4f}, {hi:.4f}]",
                f"{sum(r['status']=='completed' for r in asar)}/{len(asar)}",
            )
        )
    witness = validity["counterexample"]
    case = next(
        r
        for r in rows
        if r["scenario_id"] == "dynamic_seed213"
        and r["heuristic_mode"] == "paper_greedy"
        and r["epsilon"] == 1
    )
    if witness["h"]["paper_greedy"] <= witness["exact_remaining"] or case["J"] <= case["J_reference"]:
        raise ValueError("archived dynamic witnesses disagree with the documented finding")
    return f"""# 论文对照 · A^SAR

以工作区 8 页 PDF（arXiv v2）为准。生成器将独立转录的第 7 页 Table I 的四个任务和 Table II 的 32 个时间值逐项与阶段 7 采用的 v1 表格核对。以下本地数值由已保存的实验逐条生成。[本地 PDF 表格转录与指纹](../data/fixtures/paper_tables_v2.json) · [论文 v2](https://arxiv.org/abs/2511.10792v2) · [阶段 7 来源记录](stage7_scenarios.md)

## 数学复现成功的范围

| 原文 | 实现与可复验事实 |
| --- | --- |
| Eq. (1) | 令 b₀=p，按 Pₜ 的行源列目的约定先传播，再仅将访问格的质量乘以 1−q。粒子后验权重沿轨迹 ID 承接。 |
| Eq. (5)–(7) | 第一次探测在第 1 步。Mₜ 为联合未探测质量之和，J=Σₜ₌₁ᵀ Mₜ，以步计；g 累积至当前深度。初始质量为 1 时 Pd(T)=1−M_T。 |
| Algorithm 1 | 用堆按 g+εh 排序；同位置、同深度的不同路径分别保留信念。静态和时变 toy 的零启发式搜索与完整 DFS 对照。 |
| Algorithm 2 | 深度 d 处的第 k 个未来动作按绝对时刻 d+k 传播，在距当前顶点 ≤k 的集合内逐步贪心，允许两次模拟选择之间跳格。代码另保留绝对时间半径作诊断。 |

论文 Theorem 1 对其贪心启发式提出下界与 ε 界主张。按上述离散约定，zero 的依据是余下代价非负；在运动守恒、单格探测且 0≤q≤1 时，第 k 步余下质量至少为 M·(1−q_max)ᵏ，给出 mass_lb。适用性还要求满足搜索终止条件。有限 toy 对照的精度与普遍推导分别记录。[阶段 3 逐前缀审计](../outputs/metrics/heuristic_validity_report.json)

在本地 3×3、T=4、q=0.78 的时变反例中，DFS 枚举 {witness['feasible_completions']} 条合法路径，根处 h_paper={witness['h']['paper_greedy']:.10f}，最优余下代价为 {witness['exact_remaining']:.10f}，高估 {witness['h_minus_exact']:.10f}。另一时变 toy（seed 213）在 ε=1 时确实返回次优路线，J={case['J']:.10f}，Oracle 为 {case['J_reference']:.10f}。静态 toy 的检查仅覆盖该输入。四个海域的 paper_greedy 结果均标记为未认证。

## Table I · 任务与本地输入

经纬度按 [经度, 纬度] 给出，Z 表示 UTC。扫宽单位为海里，T 为边数。最后一列依次为本地格宽（米）、步长（秒）、预漂移（小时）。

{table(("场景","论文对象 / Leeway 映射","LKP / 事故 UTC","CSP / CST","论文风 / 流","扫宽 / T","格宽 / 步长 / 预漂移"),task_rows)}

各场景均采用 500 粒子、恒风（东、北）=(4, 0) m/s、恒流=(0.15, 0.05) m/s、全水域掩膜，按扫宽和 20 m/s 换算步时，q=0.78。四组标记为 `constant_synthetic`。历史产品目录及本次本地访问记录、岸线与海冰偏差见[逐场景可得性表](../outputs/stage7/deviations.csv)。

## Fig. 2–4 · 可逐项核对的图像

- **Fig. 2**　按论文思想重建同一起点、完美传感器、T=30 的 toy。1、5、15、30 步展示访问高质量格后剩余质量的变化。作者的具体先验矩阵缺失，像素与路径坐标均无逐点参照。[静态 toy](../outputs/figures/stage4_toy_static.png) · [自建时变对照](../outputs/figures/stage4_toy_dynamic.png)
- **Fig. 3**　论文以其最优参考值归一化。本地以各场景动态 PT 的 J 为分母。图上空心点表示计算预算已触发。ACO_inspired 各 100 次，本地带状区间为同粒子集上 J 中位数的 99% bootstrap 区间。[相对代价](../outputs/stage7/relative_cost.png)
- **Fig. 4**　Lake Ontario 在同一 UTC 的第 19 步并列显示漂移、ASAR_paper、动态 PT 与 ACO_inspired。路径叠加在各自的剩余质量上。作者的风流、手工 PT 和文献 [4] 的原版 ACO 均缺少本地等价输入或实现。[湖区路径与质量曲线](../outputs/stage7/lake_ontario/paths.png)

{table(("常量场景","PT 的 J","A^SAR 的 J（ε=1.10）","A^SAR Pd(T)","ACO_inspired 中位 J [99% CI]","正常结束 / ε 数"),case_rows)}

## Table II · 逐 ε 的运行记录

原文列为 3.2 GHz M1 Pro 上的 C++ 秒数。本地列为 Windows/Python 的 `planner_wall_s`，包括初始上界评分，PT 构造耗时另存。各 ε 从同一 PT 独立启动。处理器、实现、输入、初始上界与计算预算均影响时间，表中保留了提前中止的运行。[J、运行时间与扩展数](../outputs/figures/stage8_search_comparison.png)

{table(("场景","ε","论文 s","本地 s","扩展数","状态","停止原因","返回路径来源"),time_rows)}
"""


def final_report(root, rows, missions, validity):
    counts = Counter(r["stage"] for r in rows)
    env = read_json(root / "outputs/logs/environment.json")
    mdir = root / "outputs/metrics"
    st2 = read_json(mdir / "stage2_comparison.json")
    st4 = read_json(mdir / "stage4_toy.json")["order_control"]
    drift = read_json(mdir / "stage5_drift.json")
    s6 = [r for r in rows if r["stage"] == 6 and r["timing_scope"] == "solver"]
    searches = [r for r in rows if r["stage"] == 7 and r["algorithm"] == "ASAR_paper"]
    stops = Counter(r["stop_reason"] for r in searches if r["stop_reason"])
    witness = validity["counterexample"]
    errors = [m["replay_error"] for m in missions.values()]
    configs = [
        (f"[`{p.name}`](../configs/{p.name})", f"`{digest(p)}`")
        for p in sorted((root / "configs").iterdir())
        if p.is_file()
    ]
    o = {r["scenario_id"]: r for r in rows if r["stage"] == 1}
    config_table = table(("输入配置", "文件 SHA-256"), configs)
    maxerr = max(r["abs_error"] for r in st2["results"])
    tests = root / "outputs/logs/stage8_regression.txt"
    verification = "尚无本次全量 pytest 日志"
    if tests.is_file():
        # Stage 8 writes UTF-8. Read the last pytest summary, including failures if any.
        lines = tests.read_text(encoding="utf-8-sig").splitlines()
        verification = next(
            (s.strip() for s in reversed(lines) if re.search(r"\b(passed|failed|errors?)\b", s)),
            "日志中未找到 pytest 汇总",
        )
    return f"""# A^SAR 论文复现最终报告

## 数学复现成功

在已实现的有限离散模型内，信念递推、累积目标和小图搜索通过了手算及独立路径枚举核验。相同三步预算下，先搜高质量格得 J={o['A_first']['J']:g}，交换顺序得 J={o['B_first']['J']:g}，两者 Pd(T) 均为 1；无检测案例 J={o['no_detection']['J']:g}、Pd(T)=0。阶段 2 的 {len(st2['inputs'])} 组输入分别比较 DFS、无剪枝堆和剪枝堆，J 对 Oracle 的最大绝对误差为 {maxerr:.3g}。[阶段 1 手算](../outputs/metrics/stage1_toy.json) · [阶段 2 对照](../outputs/metrics/stage2_comparison.csv)

阶段 3 在 {len(validity['cases'])} 个 toy 上逐前缀核验。动态反例的 paper_greedy 高估余下最优代价 {witness['h_minus_exact']:.10f}。本文对数学复现的判定覆盖定义、实现和上述实例；论文的一般动态 ε 界不能从这些实验推出。[定理适用条件与反例](paper_comparison.md)

阶段 4 的静态 toy 按论文思想重建。交换两段同长往返路径后，最终 Pd(T) 同为 {st4['common_Pd_T']:.6f}，J 分别为 {st4['east_first_J']:.6f} 和 {st4['north_first_J']:.6f}。这是路径顺序改变截断代价的独立对照。[顺序实验](../outputs/figures/stage4_order.png)

## OpenDrift 场景近似

四组 Table I 任务采用 OpenDrift {drift['opendrift_version']} 的 Leeway 预漂移，CST 对齐第 0 帧。Lake Ontario 的质量账本最大绝对残差为 {drift['max_abs_residual']:.3g}。特殊格继续持有不可搜索粒子的质量。离散时钟仅在每条边结束时探测一次。[粒子账本](../outputs/metrics/stage5_mass.csv) · [粒子图](../outputs/figures/stage5_particles.png)

阶段 6 在冻结的湖区轨迹上扫描 {len(s6)} 个 ε，{sum(r['status']=='budget_exceeded' for r in s6)} 次触及预算。进程峰值工作集为 {min(r['peak_process_MiB'] for r in s6):.2f}–{max(r['peak_process_MiB'] for r in s6):.2f} MiB，另存一次 cProfile 运行。阶段 6 初始上界来自固定审计路线；阶段 7 使用动态 PT，并有单独的计算上限。[阶段 6 全部测量](../outputs/metrics/stage6_epsilon.csv) · [profile](../outputs/logs/stage6_profile.txt)

阶段 7 同输入比较覆盖 {counts[7]} 条可行路径。按 ID 独立重放 M、J 与 Pd(T) 的最大绝对误差为 {max(errors):.3g}。{len(searches)} 次 ASAR_paper 中 {sum(r['status']=='completed' for r in searches)} 次正常结束；按停止原因计数为 {', '.join(f'{reason} × {n}' for reason,n in stops.items())}。预算中止行保留当时的可行路径及其来源，全部四场景的 paper_greedy 实验均未认证。[逐 ε 状态及数值](paper_comparison.md) · [逐时刻路径与评分](../outputs/stage7/step_metrics.csv)

## 原论文真实 forcing/原作者手工 PT 未复现

Table I 指定的历史风流产品与实际 reader 分列记录。当前缺少经过变量、区域和对应 UTC 窗口验证的原始 forcing 文件对，也缺少作者当次粒子集、地图边界和认证搜救规划员的原始 PT 路径。本地使用全水域恒风恒流、规则生成的动态 ParallelTrack 和 ACO_inspired。海岸、潮汐变化、海冰及作者现场飞行未纳入结果。结论限于同一合成输入上的算法对照。[数据来源与缺口](stage7_scenarios.md) · [逐场景复现偏差](../outputs/stage7/deviations.csv)

## 配置、指标与复跑

{config_table}

[统一指标 CSV](../outputs/metrics/summary.csv) 共 {len(rows)} 条；阶段 1 至 7 的条数依次为 {', '.join(str(counts[i]) for i in range(1,8))}。阶段 0 保存环境与 smoke 证据。每条记录以 config_hash、seed、algorithm、epsilon 区分，source_file 指向原始证据。input_seed 描述输入，algorithm_seed 描述随机规划。确定性输入的 seed 留空。阶段 1–3 对固化输入取配置摘要；阶段 6 将粒子摘要、搜索配置及 profile 标志联合取哈希，阶段 7 沿用每个场景的实验配置摘要。无适用参考解或未测量的列留空。max_open 为实测队列峰值，限制值保存于实验配置。工作区无 Git 历史，git_commit 留空。

逐步序列及诊断继续保存在[阶段 1–6 指标目录](../outputs/metrics/)和[阶段 7 归档](../outputs/stage7/)；[四场景输入清单](../data/processed/manifest.json)及同目录 NPZ 足以离线调用规划器。生成报告时重新核对粒子 SHA-256 和阶段 7 全部路径。Python {env['python'].split()[0]}，指定解释器为 `{env['executable']}`。本轮全量测试日志记录为 **{verification}**。[测试日志](../outputs/logs/) · [环境快照](../outputs/logs/environment.json)

## 接入现有仿真的边界

独立 Python 接口返回原始格号路径、对应的格心 WGS84 经纬度和 UTC、逐步 M、J、Pd(T)、停止原因及解来源。调用方可以传入自己的预分格轨迹，或加载已固化的场景。航迹平滑、最小转弯半径、速度约束及返航由宿主另行评估；改变路径或采样时刻后应重新计算探测与目标值。离散格路径的结果仅适用于给定 T 和时钟。[接口与复跑命令](../README.md) · [模型假设](assumptions.md) · [阶段日志](reproduction_log.md)
"""


def build(root):
    rows, missions, validity = collect(root)
    # Validate and finish rendering before replacing any published report.
    with TemporaryDirectory(dir=root) as tmp:
        stage = Path(tmp)
        metrics, docs, figures = stage / "outputs/metrics", stage / "docs", stage / "outputs/figures"
        for folder in (metrics, docs, figures):
            folder.mkdir(parents=True)
        bundle_inputs(missions, stage / "data/processed")
        with (metrics / "summary.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        performance_plot(missions, figures / "stage8_search_comparison.png")
        paper_tables = read_json(root / "data/fixtures/paper_tables_v2.json")
        (docs / "paper_comparison.md").write_text(
            comparison(missions, validity, rows, paper_tables), encoding="utf-8"
        )
        (docs / "final_reproduction_report.md").write_text(
            final_report(root, rows, missions, validity), encoding="utf-8"
        )
        # Publish the manifest after its content-addressed payloads.
        for src in sorted(stage.rglob("*"), key=lambda p: p.name == "manifest.json"):
            if src.is_file():
                target = root / src.relative_to(stage)
                target.parent.mkdir(parents=True, exist_ok=True)
                # Create in the final directory to inherit the workspace read
                # permissions. A move from a private Windows tmpdir keeps its ACL.
                sibling = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
                try:
                    shutil.copyfile(src, sibling)
                    sibling.replace(target)
                finally:
                    sibling.unlink(missing_ok=True)
    print(f"{len(rows)} experiment records, {len(missions)} portable missions. Reports in {root/'docs'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "outputs/metrics")
    results = parser.parse_args().results.resolve()
    if results.parts[-2:] != ("outputs", "metrics") or not results.is_dir():
        parser.error("pass the project's existing outputs/metrics directory")
    build(results.parents[1])
