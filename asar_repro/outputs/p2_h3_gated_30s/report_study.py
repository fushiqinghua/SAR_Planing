"""Report the predeclared 30 s paired experiment from its archived evidence."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from hashlib import file_digest, sha256
import json
from math import isfinite
from pathlib import Path
from statistics import median


SEEDS = (3401, 4401, 4402, 4501, 4601)
ARMS = ("C0", "Lazy", "Gated")
REPS = (0, 1, 2)
DEFAULT_OUT = Path(__file__).resolve().parent / "results/local_r1"
ACCEPTANCE = {
    "J_4601_max": 55.828347528,
    "Pd_4601_min": .1968046,
    "rss_4501_factor_max": 1.10,
    "J_3401_max": 11.343163824,
    "Pd_loss_3401_pp_max": .5,
    "numerical_tolerance": 1e-8,
}


def read(path):
    with path.open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def key(task):
    return task["seed"], task["rep"], task["arm"]


def number(value):
    return value if type(value) in (int, float) and isfinite(value) else None


def as_object(value):
    return value if isinstance(value, dict) else {}


def plan(protocol):
    expected = {(seed, rep, arm) for seed in SEEDS for rep in REPS for arm in ARMS}
    tasks = protocol["tasks"]
    if (protocol["status"] != "frozen_before_gated_trials" or len(tasks) != len(expected)
            or {key(task) for task in tasks} != expected):
        raise ValueError("The frozen file does not register the 45 prescribed seed/rep/arm tasks")
    if protocol["total_seconds"] != 30 or protocol["solver_reserve_s"] != 2 or protocol["lazy_cutoff_s"] != 5.95:
        raise ValueError("The frozen time envelope differs from the study design")
    if any(protocol["acceptance"][name] != value for name, value in ACCEPTANCE.items()):
        raise ValueError("The frozen acceptance gates differ from the study design")
    return tasks


def load_run(out, protocol, task):
    seed, rep, arm = key(task)
    run_id = f"s{seed}_r{rep}_{arm}"
    folder = out / "runs" / run_id
    record_path = folder / "record.json"
    result_path = folder / "result.json"
    row = dict(task, run_id=run_id, eligible=False, status="missing", evidence_error=None,
               record_path=record_path.relative_to(out).as_posix(),
               result_path=result_path.relative_to(out).as_posix(), result_sha256=None)
    if not record_path.is_file():
        row["status"] = "unrecorded" if folder.exists() else "missing"
        return row
    try:
        record = read(record_path)
        if record["task"] != task:
            raise ValueError("Task identity differs from the frozen plan")
        row.update(status=record["status"], returncode=record.get("returncode"), watchdog=record.get("watchdog"))
        files = record["files"]
        for name, sha in files.items():
            if Path(name).name != name or digest(folder / name) != sha:
                raise ValueError(f"Run file hash mismatch for {name}")
        peak = number(record.get("process_peak_rss_bytes"))
        row["rss_peak_mib"] = peak / 2**20 if peak is not None and peak > 0 else None
        row["process_wall_s"] = number(record.get("process_wall_s"))
        for name, field in (("rejected_result.json", "rejected_result_path"), ("stderr.log", "stderr_path")):
            if name in files:
                row[field] = (folder / name).relative_to(out).as_posix()
        if not result_path.is_file():
            if record["status"] in {"valid", "overbudget"}:
                raise ValueError("Run status requires a retained result")
            return row
        sha = digest(result_path)
        if files.get("result.json") != sha or record["result_sha256"] != sha:
            raise ValueError("Result hash mismatch")
        row["result_sha256"] = sha
        result = read(result_path)
        if result["task"] != task or result["status"] != record["status"]:
            raise ValueError("Result task or status differs from the run record")
        compact(row, result, protocol["reference"][str(seed)]["S30"], protocol["total_seconds"])
    except (OSError, ValueError, TypeError, KeyError) as exc:
        row.update(status="invalid_evidence", evidence_error=str(exc), eligible=False)
    return row


def compact(row, result, reference, budget):
    outer = result["outer"]
    if len(outer["phases"]) != 1:
        raise ValueError("The study must deliver one full-mission route")
    phase = outer["phases"][0]
    inner = as_object(result.get("inner"))
    delivery = result["delivery"]
    replay, scalar = result["replay"], result["independent_replay"]
    vertices = replay["waypoints"]
    J, Pd = number(replay["J"]), number(replay["pd_final"])
    scalar_J, scalar_Pd = number(scalar["J"]), number(scalar["pd_final"])
    tol = ACCEPTANCE["numerical_tolerance"]
    if (not vertices or vertices != outer["waypoints"] or vertices != scalar["waypoints"]
            or None in (J, Pd, scalar_J, scalar_Pd)
            or abs(J - scalar_J) > tol or abs(Pd - scalar_Pd) > tol
            or abs(J - outer["J"]) > tol or abs(Pd - outer["pd_final"]) > tol):
        raise ValueError("The recorded delivery differs from its physical replays")
    fallback = vertices == reference["waypoints"]
    if fallback != delivery["fallback_s30"] or delivery["accepted"] != phase["accepted"]:
        raise ValueError("The delivery ledger contradicts its recorded route")
    wall = number(result["algorithm_wall_s"])
    if wall is None or wall < 0 or type(delivery["within_budget"]) is not bool:
        raise ValueError("The algorithm wall time or delivery budget value is invalid")
    start = number(phase.get("inner_start_compute_s"))
    returned = number(phase.get("inner_return_compute_s"))
    inner_wall = number(inner.get("wall_s"))
    overhead = None if None in (start, returned, inner_wall) else max(0.0, returned - start - inner_wall)
    diagnostics = as_object(inner.get("diagnostics"))
    gate = as_object(diagnostics.get("gated"))
    stats = as_object(inner.get("stats"))
    attempts = gate.get("attempts", [])
    side_wall = [value for attempt in attempts if (value := number(attempt.get("wall_s"))) is not None]
    side_terminal = [value for attempt in attempts if (value := number(attempt.get("terminal_candidates"))) is not None]
    history = inner.get("history", [])
    best_source = as_object(history[-1]).get("source") if history else None
    selected_source = gate.get("selected_source", best_source)
    schema = {
        "J": J, "Pd": Pd, "S30_J": reference["J"], "S30_Pd": reference["Pd"],
        "route_sha256": sha256(json.dumps(vertices, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "route_vertices": len(vertices), "fallback_s30": fallback,
        "algorithm_wall_s": wall, "algorithm_cpu_s": number(result.get("algorithm_cpu_s")),
        "input_load_s": number(result.get("input_load_s")), "audit_wall_s": number(result.get("audit_wall_s")),
        "wall_within_30s": wall <= budget, "delivery_within_budget": delivery["within_budget"],
        "deadline_overshoot_s": number(delivery.get("deadline_overshoot_s")),
        "accepted": delivery["accepted"], "disposition": delivery["disposition"],
        "acceptance_s": number(delivery.get("acceptance_s")),
        "inner_return_s": returned, "inner_wall_s": inner_wall,
        "inner_call_overhang_s": overhead, "finalization_s": number(outer.get("finalization_compute_s")),
        "inner_stop": inner.get("stop_reason"), "inner_J": number(inner.get("J")),
        "inner_Pd": number(inner.get("pd_final")), "expanded": number(inner.get("expanded")),
        "generated": number(inner.get("generated")), "peak_open": number(inner.get("peak_open")),
        "end_open": number(inner.get("open_count")), "terminal": number(stats.get("terminal_candidates")),
        "first_terminal_s": number(diagnostics.get("first_search_terminal_generated_s")),
        "best_inner_s": number(inner.get("best_elapsed_s")), "best_inner_source": best_source,
        "gate_mode": gate.get("mode"), "gate_attempts": len(attempts) if gate else None,
        "gate_attempt_wall_s": sum(side_wall) if side_wall else None,
        "gate_terminal_candidates": sum(side_terminal) if side_terminal else None,
        "gate_first_attempt_s": number(attempts[0].get("opened_elapsed_s")) if attempts else None,
        "gate_side_improvements": len(gate.get("side_improvements", [])) if gate else None,
        "gate_coverage_ratio": number(gate.get("initial_coverage_ratio")),
        "gate_first_main_terminal_s": number(gate.get("first_main_terminal_s")),
        "gate_selected_source": gate.get("selected_source"),
        "delivered_source": "S30" if fallback else selected_source,
    }
    row.update(schema)
    row["eligible"] = (
        row["status"] == "valid" and row["returncode"] == 0 and row["watchdog"] is None
        and schema["wall_within_30s"] and schema["delivery_within_budget"]
    )


def pairs_for(rows):
    indexed = {key(row): row for row in rows}
    pairs = []
    for seed in SEEDS:
        for rep in REPS:
            c0 = indexed[(seed, rep, "C0")]
            for arm in ("Lazy", "Gated"):
                alt = indexed[(seed, rep, arm)]
                pair = dict(seed=seed, rep=rep, arm=arm, c0_run=c0["run_id"], other_run=alt["run_id"],
                            eligible=c0["eligible"] and alt["eligible"])
                if pair["eligible"]:
                    ratio = None
                    if c0.get("rss_peak_mib") and alt.get("rss_peak_mib"):
                        ratio = alt["rss_peak_mib"] / c0["rss_peak_mib"]
                    pair.update(
                        J=alt["J"], Pd=alt["Pd"], delta_J=alt["J"] - c0["J"],
                        delta_Pd_pp=100 * (alt["Pd"] - c0["Pd"]), paired_RSS_ratio=ratio,
                        same_route=alt["route_sha256"] == c0["route_sha256"],
                        delta_wall_s=alt["algorithm_wall_s"] - c0["algorithm_wall_s"],
                        delta_peak_open=None if None in (alt["peak_open"], c0["peak_open"])
                        else alt["peak_open"] - c0["peak_open"],
                    )
                pairs.append(pair)
    return pairs


def case_gates(rows, pairs, limits):
    gated = [row for row in rows if row["arm"] == "Gated"]
    qualified = [row for row in gated if row["seed"] == 4601 and row["eligible"]]
    witnesses = [
        row["run_id"] for row in qualified
        if row["accepted"] and not row["fallback_s30"]
        and row["J"] <= limits["J_4601_max"] and row["Pd"] >= limits["Pd_4601_min"]
    ]
    gates = {"4601": dict(eligible=len(qualified), passing=len(witnesses), witness_run_ids=witnesses,
                          any_hit=bool(witnesses), all_three_hit=len(witnesses) == 3,
                          pass_gate=None if len(qualified) != 3 else len(witnesses) == 3)}

    equal = []
    ratios = []
    tol = limits["numerical_tolerance"]
    focus = [pair for pair in pairs if pair["seed"] == 4501 and pair["arm"] == "Gated" and pair["eligible"]]
    for pair in focus:
        equal.append(abs(pair["delta_J"]) <= tol and abs(pair["delta_Pd_pp"]) <= 100 * tol)
        if pair["paired_RSS_ratio"] is not None:
            ratios.append(pair["paired_RSS_ratio"])
    ratio = median(ratios) if ratios else None
    gates["4501"] = dict(
        eligible_pairs=len(focus), equal_J_Pd_pairs=sum(equal), measured_RSS_pairs=len(ratios),
        median_paired_RSS_ratio=ratio,
        pass_gate=None if len(focus) != 3 or len(ratios) != 3 else all(equal) and ratio <= limits["rss_4501_factor_max"],
    )

    focus = [pair for pair in pairs if pair["seed"] == 3401 and pair["arm"] == "Gated" and pair["eligible"]]
    passing = [
        pair["other_run"] for pair in focus
        if pair["J"] <= limits["J_3401_max"] + tol
        and pair["delta_Pd_pp"] >= -limits["Pd_loss_3401_pp_max"]
    ]
    gates["3401"] = dict(eligible_pairs=len(focus), passing=len(passing), passing_run_ids=passing,
                         pass_gate=None if len(focus) != 3 else len(passing) == 3)
    return gates


def median_value(rows, name):
    values = [row[name] for row in rows if row.get(name) is not None]
    return median(values) if values else None


def counts(rows, name):
    return dict(Counter(str(row.get(name) or "unavailable") for row in rows))


def arm_summary(rows):
    scope = {}
    for seed in SEEDS:
        for arm in ARMS:
            group = [row for row in rows if row["seed"] == seed and row["arm"] == arm]
            eligible = [row for row in group if row["eligible"]]
            # Report Pd from the same physical route as the representative J.
            by_J = sorted(eligible, key=lambda row: (row["J"], row["rep"]))
            representative = by_J[1] if len(by_J) == 3 else None
            scope[f"{seed}_{arm}"] = dict(
                seed=seed, arm=arm, eligible=len(eligible), statuses=counts(group, "status"),
                median_J_run_id=representative["run_id"] if representative else None,
                median_J=representative["J"] if representative else median_value(eligible, "J"),
                Pd_on_median_J_route=representative["Pd"] if representative else None,
                median_wall_s=median_value(eligible, "algorithm_wall_s"),
                median_peak_RSS_MiB=median_value(eligible, "rss_peak_mib"),
                median_peak_open=median_value(eligible, "peak_open"),
                within_budget=sum(bool(row.get("wall_within_30s")) for row in group),
                accepted=sum(row["eligible"] and bool(row.get("accepted")) for row in group),
                fallback_s30=sum(bool(row.get("fallback_s30")) for row in group),
                stop_reasons=counts(group, "inner_stop"), dispositions=counts(group, "disposition"),
                gate_modes=counts(group, "gate_mode"),
            )
    return scope


def stringify(value, spec):
    return "—" if value is None else format(value, spec)


def brief(kv):
    return "，".join(f"{key} × {value}" for key, value in sorted(kv.items()))


def table_row(row):
    return [
        row["seed"], row["arm"], f"{row['eligible']}/3", stringify(row["median_J"], ".9f"),
        stringify(row["Pd_on_median_J_route"], ".6%"), stringify(row["median_wall_s"], ".3f"),
        stringify(row["median_peak_open"], "g"), stringify(row["median_peak_RSS_MiB"], ".2f"),
        row["accepted"], row["fallback_s30"],
    ]


def md_row(fields):
    return "| " + " | ".join(str(field) for field in fields) + " |"


def render(summary, rows):
    g = summary["acceptance_gates"]
    labels = {True: "通过", False: "未通过", None: "证据未齐备"}
    lines = [
        "# H3 门控限宽续接的 30 秒对照",
        "",
        f"计划 45 次独立试验，已有 {summary['recorded']} 份记录，"
        f"其中 {summary['eligible']} 次满足交付和计时条件。"
        f"外层计时超过 30 秒 {summary['measured_outer_overbudget']} 次。"
        f"总体判定为 **{labels[summary['campaign_pass']]}**。",
        "",
        "各臂沿用冻结的 H3 目标、物理评分器、forcing 和 S30 初始路线。"
        "物理问题采用八邻接、原航向方形探测覆盖、速度 20 米每秒和探测概率 q=0.78。"
        "J 为完整任务时域内各次观测后的剩余质量之和。",
        "正式窗口为 30 秒，交付预留 2 秒，原 Lazy 资格截止固定在 5.95 秒。"
        "独立标量重放和输入加载另行计时。峰值 RSS 来自对子进程的轮询采样。",
        "",
        "## 预先约定的验收",
        "",
        f"- **4601** 同一条按时交付的改进路线同时满足 J ≤ 55.828347528 和 Pd ≥ 19.68046%。"
        f"门控组命中 {g['4601']['passing']}/3，计时合格 {g['4601']['eligible']}/3。"
        f"三次均达标的判定为 {labels[g['4601']['pass_gate']]}。",
        f"- **4501** 配对 J/Pd 持平 {g['4501']['equal_J_Pd_pairs']}/3。"
        f"门控组相对 C0 的配对峰值 RSS 比值中位数为 "
        f"{stringify(g['4501']['median_paired_RSS_ratio'], '.4f')}，上限为 1.10。"
        f"判定为 {labels[g['4501']['pass_gate']]}。",
        f"- **3401** 在同次结果保住 J ≤ 11.343163824 并满足相对配对 C0 的 Pd 下降不超过 "
        f"0.5 个百分点，门控组命中 {g['3401']['passing']}/3。判定为 {labels[g['3401']['pass_gate']]}。",
        "",
        "## 结果与资源",
        "",
        "| 实例 | 方法 | 合格次数 | J 中位数 | 对应路线 Pd | 耗时中位数 s | OPEN 峰值中位数 | RSS 峰值中位数 MiB | 采用改进 | S30 交付 |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    lines.extend(md_row(table_row(row)) for row in summary["arms"].values())
    lines.extend([
        "",
        "同一实例的重复按冻结顺序配对。程序为齐备的三个结果选 J 居中的试验并显示该路线的 Pd。"
        "[配对 CSV](paired.csv) 保留 4401、4402 的所有观察及任何未完成或失败的配对。",
        "",
        "## 停止与交付",
        "",
        f"- 运行状态 {brief(summary['run_statuses'])}。",
        f"- 内层停止 {brief(summary['inner_stops'])}。",
        f"- 外层处置 {brief(summary['dispositions'])}。",
        "[逐次 CSV](runs.csv) 记录采用时钟、是否交付 S30、实际交付的路线指纹和内层计时之外的开销。"
        "该开销可能含门控准备、结果构造和清理等工作。",
        "",
    ])
    if g["4601"]["witness_run_ids"]:
        lines.append("4601 达标路线的原始记录")
        lines.append("")
        for row in rows:
            if row["run_id"] in g["4601"]["witness_run_ids"]:
                lines.append(f"- [{row['run_id']}](../{row['result_path']})，"
                             f"J {row['J']:.9f}，Pd {row['Pd']:.6%}，外层耗时 {row['algorithm_wall_s']:.6f} 秒。")
        lines.append("")
    lines.append("这些是预定实例和重复的经验结果。终点 Pd 作为验收指标，优化目标仍为冻结 J。")
    return "\n".join(lines) + "\n"


def write_text(path, data):
    pending = path.with_suffix(path.suffix + ".tmp")
    pending.write_text(data, encoding="utf-8")
    pending.replace(path)


def write_csv(path, rows):
    columns = list(dict.fromkeys(name for row in rows for name in row))
    pending = path.with_suffix(".csv.tmp")
    with pending.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    pending.replace(path)


def report(out):
    protocol = read(out / "protocol.json")
    rows = [load_run(out, protocol, task) for task in plan(protocol)]
    pairs = pairs_for(rows)
    gates = case_gates(rows, pairs, protocol["acceptance"])
    recorded = sum(row["status"] not in {"missing", "unrecorded"} for row in rows)
    eligible = sum(row["eligible"] for row in rows)
    campaign = None if recorded != 45 else eligible == 45 and all(gate["pass_gate"] is True for gate in gates.values())
    summary = dict(
        registered=len(rows), recorded=recorded, eligible=eligible, campaign_pass=campaign,
        measured_outer_overbudget=sum(row.get("delivery_within_budget") is False for row in rows),
        run_statuses=counts(rows, "status"), inner_stops=counts(rows, "inner_stop"),
        dispositions=counts(rows, "disposition"),
        protocol_sha256=digest(out / "protocol.json"), preflight=protocol["preflight"],
        order_seed=protocol["order_seed"], gated_settings=protocol["gated_settings"],
        total_seconds=protocol["total_seconds"], solver_reserve_s=protocol["solver_reserve_s"],
        lazy_cutoff_s=protocol["lazy_cutoff_s"],
        acceptance_limits=protocol["acceptance"], acceptance_gates=gates, arms=arm_summary(rows),
        empirical_only=True, optimality_certificate=False,
    )
    directory = out / "analysis"
    directory.mkdir(exist_ok=True)
    write_csv(directory / "runs.csv", rows)
    write_csv(directory / "paired.csv", pairs)
    write_text(directory / "REPORT.md", render(summary, rows))
    summary["report_sha256"] = {
        name: digest(directory / name) for name in ("runs.csv", "paired.csv", "REPORT.md")
    }
    write_text(directory / "summary.json", json.dumps(summary, ensure_ascii=False, allow_nan=False, indent=2) + "\n")
    print(f"report: {directory}; records={recorded}/45; eligible={eligible}/45; campaign_pass={campaign}")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    report(parser.parse_args().out.resolve())
