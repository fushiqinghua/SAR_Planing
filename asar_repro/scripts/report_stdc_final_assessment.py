#!/usr/bin/env python3
"""Render the completed frozen STDC batch; never run an experiment.

Read summary/protocol, immutable raw results and validation evidence.  Write
FINAL_REPORT.md, comparison.csv, and one performance figure in PNG and SVG.
No imported search module, solver, raw log, protocol, or result is modified.
Run only after the serial measurement stages and their final summary finish.
Integrity or admissibility violations remain visible and cause exit code 2.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs/stdc_final_assessment_20261125_r1"
DEFAULT_PRIOR = ROOT / "outputs/stdc_final_assessment_20261125"
SCENES = {
    "lake_ontario": "Lake Ontario",
    "arctic_ocean": "Hudson（arctic_ocean）",
    "bay_of_fundy": "Fundy†",
}
PLOT_SCENES = {
    "lake_ontario": "Lake Ontario",
    "arctic_ocean": "Hudson (arctic_ocean)",
    "bay_of_fundy": "Fundy [direction unverified]",
}
ARMS = {"zero": "zero", "mass_lb": "mass", "stdc_lb": "STDC"}
COLORS = {"zero": "#737373", "mass_lb": "#0072B2", "stdc_lb": "#D55E00"}
PAIR_TOLERANCE = 1e-10


def read_json(path):
    with Path(path).open(encoding="utf-8") as stream:
        return json.load(stream)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def median(values):
    values = [float(v) for v in values if finite(v)]
    return statistics.median(values) if values else None


def fmt(value, digits=6):
    if not finite(value):
        return "—"
    return f"{value:.{digits}f}"


def pct(value, digits=2):
    return f"{100*value:.{digits}f}%" if finite(value) else "—"


def spread(values, digits=4):
    values = [float(v) for v in values if finite(v)]
    if not values:
        return "—"
    return f"{fmt(median(values), digits)} [{fmt(min(values), digits)}, {fmt(max(values), digits)}]"


def table(headers, rows):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    lines = ["| " + " | ".join(map(cell, headers)) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(map(cell, row)) + " |" for row in rows)
    return "\n".join(lines) if rows else "暂无可用记录。"


def task_key(task):
    return json.dumps(task, sort_keys=True, separators=(",", ":"))


def good(row, require_j=True):
    result = row.get("result", {})
    return (row["record"].get("status") == "recorded"
            and result.get("status") != "blocked"
            and (finite(result.get("J")) if require_j else bool(result)))


def group_rows(rows):
    groups = defaultdict(list)
    for row in rows:
        task = row["task"]
        groups[(task["phase"], task["scene"], task.get("bound"), task["seconds"])].append(row)
    return groups


def expected_tasks(config, followup):
    search = config["search"]
    for scene in config["scenes"]:
        for seconds in search["wall_budgets_s"]:
            for bound in search["bounds"]:
                for rep in range(search["repetitions"]):
                    yield dict(phase="wall", scene=scene, bound=bound, seconds=seconds, rep=rep)
        for bound in search["bounds"]:
            for rep in range(search["fixed_work_repetitions"]):
                yield dict(phase="work", scene=scene, bound=bound,
                           seconds=search["fixed_work_safety_seconds"],
                           expansions=search["fixed_work_expansions"], rep=rep)
        for initial in config["events"]["initial_routes"]:
            for rep in range(config["events"]["repetitions"]):
                yield dict(phase="events", scene=scene, initial=initial,
                           seconds=config["events"]["seconds"], rep=rep)
        for fraction in config["pairs"]["prefix_fractions"]:
            yield dict(phase="pairs", scene=scene,
                       depth=int(config["scenes"][scene]["mission"]["budget"]*fraction),
                       seconds=config["pairs"]["seconds_per_node"], rep=0)
        if followup:
            for rep in range(config["events"]["formal_followup_repetitions"]):
                yield dict(phase="event_followup", scene=scene,
                           bound=config["events"]["formal_followup_continuation_bound"],
                           seconds=config["events"]["formal_followup_seconds"], rep=rep)
    for arm in config["mip"]["arms"]:
        for rep in range(config["mip"]["repetitions"]):
            yield dict(phase="mip", scene=config["mip"]["scene"], arm=arm,
                       seconds=config["mip"]["seconds_per_run"], rep=rep)


def junit_evidence(folder):
    root = ET.parse(folder / "junit.xml").getroot()
    suites = [s for s in root.iter("testsuite") if not list(s.iterfind("testsuite"))]
    counts = {key: sum(int(s.attrib.get(key, 0)) for s in suites)
              for key in ("tests", "failures", "errors", "skipped")}
    counts["testcase_elements"] = len(list(root.iter("testcase")))
    text = (folder / "pytest.log").read_text(encoding="utf-8", errors="replace")
    passed = re.findall(r"(?<!\w)(\d+) passed\b", text)
    subtests = re.findall(r"(?<!\w)(\d+) subtests? passed\b", text)
    counts["pytest_passed"] = int(passed[-1]) if passed else None
    counts["subtests_passed"] = int(subtests[-1]) if subtests else None
    return counts


def read_prior(folder, config):
    if folder is None or not (folder / "protocol.json").exists():
        return dict(available=False)
    protocol = read_json(folder / "protocol.json")
    paths = sorted((folder / "runs").glob("*/record.json"))
    records = [read_json(path) for path in paths]
    return dict(available=True, directory=folder, records=len(records),
                blocked=sum(r.get("status") == "blocked" for r in records),
                raw_results=sum((p.parent / "raw_result.json").exists() for p in paths),
                config_equal=protocol.get("config") == config,
                executable=protocol.get("environment", {}).get("executable"))


def read_evidence(output, prior):
    # A final summary is a required input: never silently consume an interim
    # benchmark_summary with still-empty events/pairs/MIP lists.
    summary = read_json(output / "summary.json")
    protocol = read_json(output / "protocol.json")
    config = protocol["config"]
    fatal, incomplete, notices = [], [], []
    protocol_hash = digest(output / "protocol.json")
    for name, expected in protocol.get("validation_sha256", {}).items():
        path = output / "validation" / name
        if not path.is_file() or digest(path) != expected:
            fatal.append(f"冻结验证证据发生变化：validation/{name}")
    for name, expected in protocol.get("source_sha256", {}).items():
        path = ROOT / name
        if not path.is_file() or digest(path) != expected:
            fatal.append(f"冻结代码或配置发生变化：{name}")
    for scene_name, scene in config["scenes"].items():
        for path_key, hash_key in (("particle_path", "particle_sha256"),
                                   ("metadata_path", "metadata_sha256")):
            path = ROOT / scene[path_key]
            if not path.is_file() or digest(path) != scene[hash_key]:
                fatal.append(f"冻结输入或 metadata 哈希不匹配：{scene_name}/{path_key}")
    rows, seen = [], set()
    for path in sorted((output / "runs").glob("*/record.json")):
        record = read_json(path)
        relative = str(path.parent.relative_to(output))
        task = record["task"]
        key = task_key(task)
        if key in seen:
            fatal.append(f"重复实验任务：{relative}")
        seen.add(key)
        if record.get("protocol_sha256") != protocol_hash:
            fatal.append(f"protocol 哈希不匹配：{relative}")
        raw = path.parent / "raw_result.json"
        row = dict(task=task, record=record, result={}, run_directory=relative)
        if raw.exists():
            if digest(raw) != record.get("raw_result_sha256"):
                fatal.append(f"raw_result 哈希不匹配：{relative}")
            payload = read_json(raw)
            if payload.get("task") != task:
                fatal.append(f"raw/record 任务不匹配：{relative}")
            if payload.get("worker_environment") != protocol.get("expected_worker_environment"):
                fatal.append(f"worker 环境不匹配：{relative}")
            row["result"] = payload.get("result", {})
        elif record.get("status") == "recorded":
            fatal.append(f"标记 recorded 但缺少 raw_result：{relative}")
        for name in ("task.json", "stdout.log", "stderr.log"):
            if not (path.parent / name).exists():
                fatal.append(f"原始追踪文件缺失：{relative}/{name}")
        rows.append(row)
    for taskfile in (output / "runs").glob("*/task.json"):
        if not (taskfile.parent / "record.json").exists():
            incomplete.append(f"任务尚无完成 record：{taskfile.parent.name}")
    if summary.get("total_runs") != len(rows):
        fatal.append("summary.total_runs 与实际 record 数不一致；需重新生成最终 summary")
    tests = junit_evidence(output / "validation")
    if any(tests[k] for k in ("failures", "errors", "skipped")):
        fatal.append("JUnit 存在失败、错误或跳过，冻结验证未全部通过")
    audit = read_json(output / "validation/theory_audit.json")
    if audit.get("status") != "passed" or audit.get("violation_count") != 0:
        fatal.append("独立理论审计未通过")
    toy_path = output / "validation/pair_toy.json"
    toy = read_json(toy_path) if toy_path.exists() else None
    if toy is None:
        notices.append("未提供 validation/pair_toy.json，toy 的实测数值暂不报告")
    elif toy.get("status") != "passed":
        fatal.append("追加 toy 验证未通过")
    preservation_path = output / "final_preservation.json"
    preservation = read_json(preservation_path) if preservation_path.exists() else None
    if preservation is not None and (preservation.get("status") != "passed"
            or preservation.get("original_source_changed")
            or not preservation.get("input_particles_unchanged")):
        fatal.append("最终源文件/输入保全检查未通过")
    data = dict(output=output, summary=summary, protocol=protocol, config=config,
                rows=rows, groups=group_rows(rows), fatal=fatal, incomplete=incomplete,
                notices=notices, tests=tests, audit=audit, toy=toy,
                preservation=preservation,
                prior=read_prior(prior, config))
    audit_evidence(data)
    return data


def audit_evidence(data):
    config, rows = data["config"], data["rows"]
    fatal, incomplete = data["fatal"], data["incomplete"]
    tolerance = config["tolerance"]
    witnesses = []
    for row in rows:
        task, result = row["task"], row["result"]
        label = row["run_directory"]
        scene = config["scenes"][task["scene"]]
        if not good(row, require_j=False):
            incomplete.append(f"任务阻塞或没有算法结果：{label}")
            continue
        if task["phase"] != "pairs":
            if not result.get("final_original_replay", {}).get("passed"):
                fatal.append(f"缺少原目标最终路径复算通过记录：{label}")
        if task["phase"] in ("wall", "work", "events", "event_followup"):
            if not result.get("strict_budget_selection"):
                fatal.append(f"未使用截止时间以内的 incumbent：{label}")
            seed_key = "reference_J" if task.get("initial") == "historical_reference" else "PT_J"
            available = [(0., scene[seed_key])]
            for item in result.get("incumbent_history", []):
                if finite(item.get("elapsed_s")) and finite(item.get("J")):
                    if item["elapsed_s"] < 0:
                        fatal.append(f"incumbent 时间为负：{label}")
                    if item["elapsed_s"] <= task["seconds"]:
                        available.append((item["elapsed_s"], item["J"]))
            if not finite(result.get("J")) or abs(min(j for _, j in available)-result["J"]) > tolerance:
                fatal.append(f"最终 J 与截止时间内的 history 不一致：{label}")
            for name, factor in config["search"]["quality_targets"].items():
                reached = [t for t, j in available if j <= scene["reference_J"]*factor+tolerance]
                actual = min(reached) if reached else None
                saved = result.get("time_to_targets_s", {}).get(name)
                if ((actual is None) != (saved is None)
                        or (actual is not None and (not finite(saved) or abs(actual-saved) > tolerance))):
                    fatal.append(f"实际 time-to-target 与 history 不一致：{label}/{name}")
        if task["phase"] == "events":
            if result.get("J", math.inf) < scene["reference_J"]-tolerance:
                witnesses.append(label)
            archive = result.get("candidate_archive", [])
            paths = [tuple(item["path"]) for item in archive]
            stats = result.get("stats", {})
            if (stats.get("complete_candidates") != len(archive)
                    or stats.get("unique_complete_candidates") != len(set(paths))
                    or stats.get("duplicate_candidates") != len(paths)-len(set(paths))):
                fatal.append(f"事件候选计数与原始路径不一致：{label}")
            initial = scene["reference_path"] if task.get("initial") == "historical_reference" else scene["initial_path"]
            for item in archive:
                first = next((i for i, (a, b) in enumerate(zip(item["path"], initial)) if a != b), None)
                if first != item.get("first_divergence"):
                    fatal.append(f"事件首次分歧记录与原始路径不一致：{label}")
            if len(archive) > config["events"]["max_candidates"]:
                fatal.append(f"事件候选数超过冻结上限：{label}")
        if task["phase"] == "pairs":
            audit_pair(row, fatal)
    data["event_witnesses"] = witnesses
    primary_witnesses = [r for r in rows if r["run_directory"] in witnesses
                         and r["task"]["scene"] in config["primary_scenes"]]
    data["event_followup_required"] = bool(primary_witnesses)
    expected = {task_key(t) for t in expected_tasks(config, bool(primary_witnesses))}
    actual = {task_key(r["task"]) for r in rows}
    incomplete.extend("缺少冻结任务：" + key for key in sorted(expected-actual))
    if actual-expected:
        fatal.append("出现未由冻结规则触发的额外任务：" + "; ".join(sorted(actual-expected)))
    gate_path = data["output"] / "event_followup_gate.json"
    if gate_path.exists():
        gate = read_json(gate_path)
        if gate.get("status") != ("triggered" if primary_witnesses else "not_triggered"):
            fatal.append("事件 follow-up gate 文件与原始严格改善记录不一致")
        data["event_gate"] = gate
    else:
        incomplete.append("缺少 event_followup_gate.json，需完成正式触发判定")
    for entry in data["summary"].get("comparisons", []):
        key = tuple(entry[k] for k in ("phase", "scene", "bound", "seconds"))
        group = data["groups"].get(key, [])
        valid = [r for r in group if good(r)]
        if entry.get("total_runs") != len(group) or entry.get("valid_runs") != len(valid):
            fatal.append("summary 运行数与 raw records 不一致：" + str(key))
        for metric in ("J", "Pd", "expanded", "pruned", "measured_algorithm_wall_s"):
            computed = median(r["result"].get(metric) for r in valid)
            saved = entry.get(metric, {}).get("median")
            if (computed is None) != (saved is None) or (computed is not None
                    and (not finite(saved) or abs(computed-saved) > 1e-10*max(1., abs(computed)))):
                fatal.append(f"summary 中位数与 raw 不一致：{key}/{metric}")
    data["screen"] = screening(data)
    if data["screen"]["complete"]:
        for key in ("quality_screen_pass", "runtime_screen_pass"):
            if data["screen"][key] != data["summary"].get("decision", {}).get(key):
                fatal.append(f"summary 决策与原始数据独立计算不一致：{key}")


def audit_pair(row, fatal):
    result, label = row["result"], row["run_directory"]
    upper = result.get("reference_suffix_J")
    if not finite(upper):
        fatal.append(f"pair 缺少可行后缀原目标上界：{label}")
        return
    for name in ("original_stdc_bound", "full_stdc_bound", "grouped_bound", "bound"):
        lower = result.get(name)
        if lower is not None and (not finite(lower) or lower < -PAIR_TOLERANCE
                                  or lower > upper+PAIR_TOLERANCE):
            fatal.append(f"FATAL 下界越过可行后缀或非有限：{label}/{name}={lower}, U={upper}")
    if result.get("status") == "completed":
        lower, original = result.get("bound"), result.get("original_stdc_bound")
        if not finite(lower) or not finite(original):
            fatal.append(f"pair completed 但缺少有效 bound：{label}")
        elif lower < original-PAIR_TOLERANCE:
            fatal.append(f"max 聚合低于原 STDC：{label}")
        else:
            closure = max(0., lower-original)/(upper-original) if upper > original else None
            recorded = result.get("interval_closure_fraction")
            if ((closure is None) != (recorded is None)
                    or (closure is not None and (not finite(recorded) or abs(closure-recorded) > PAIR_TOLERANCE))):
                fatal.append(f"pair interval closure 与原始上下界不一致：{label}")
    elif result.get("bound") is not None:
        fatal.append(f"pair 未完成却发布了下界：{label}")
    weights = result.get("group_weights", [])
    if abs(math.fsum(weights)-result.get("current_mass", math.inf)) > PAIR_TOLERANCE:
        fatal.append(f"未来轨迹合并改变当前总质量：{label}")
    indices = [i for item in result.get("pair_selection", []) for i in item["pair"]]
    if len(indices) != len(set(indices)):
        fatal.append(f"pair 共享同一质量组，出现重复计数：{label}")
    if any(i < 0 or i >= len(weights) for i in indices):
        fatal.append(f"pair 选择下标越界：{label}")
    elif abs(math.fsum(weights[i] for i in indices)-result.get("selected_current_mass", math.inf)) > PAIR_TOLERANCE:
        fatal.append(f"pair 所选质量与 group_weights 不一致：{label}")


def target_data(group, name, expected):
    valid = [r for r in group if good(r)]
    reached = [r["result"].get("time_to_targets_s", {}).get(name) for r in valid]
    reached = [t for t in reached if finite(t)]
    return dict(reached=len(reached), expected=expected, valid=len(valid),
                censored=len(valid)-len(reached), missing=max(0, expected-len(valid)),
                median_reached=median(reached), all_reached=len(reached) == expected)


def target_text(group, name, expected):
    item = target_data(group, name, expected)
    value = fmt(item["median_reached"], 4)
    if not item["reached"]:
        value = "—"
    return (f"{item['reached']}/{expected}; {value}; 删失{item['censored']}"
            + (f"/缺测{item['missing']}" if item["missing"] else ""))


def screening(data):
    config, groups = data["config"], data["groups"]
    expected = config["search"]["repetitions"]
    screen = dict(complete=True, per_scene={}, quality_screen_pass=False,
                  runtime_screen_pass=False)
    for scene in config["primary_scenes"]:
        selected = {arm: [r for r in groups.get(("wall", scene, arm, 5.), []) if good(r)]
                    for arm in config["search"]["bounds"]}
        if any(len(group) != expected for group in selected.values()):
            screen["complete"] = False
            continue
        values = {arm: median(r["result"]["J"] for r in group) for arm, group in selected.items()}
        cheap = min(values["zero"], values["mass_lb"])
        gain = (cheap-values["stdc_lb"])/cheap if cheap > 0 else 0.
        times = {arm: target_data(group, config["decision"]["time_target"], expected)
                 for arm, group in selected.items()}
        all_reached = all(t["all_reached"] for t in times.values())
        ratios = {}
        if all_reached:
            for arm in ("zero", "mass_lb"):
                baseline = times[arm]["median_reached"]
                ratios[arm] = times["stdc_lb"]["median_reached"]/baseline if baseline > 0 else None
        runtime = (all_reached and all(finite(ratios.get(arm)) and ratios[arm] <=
                       1-config["decision"]["time_relative_reduction"] for arm in ("zero", "mass_lb"))
                   and gain >= -1e-8)
        screen["per_scene"][scene] = dict(gain=gain, no_regression=gain >= -1e-8,
                                          all_reached=all_reached, ratios=ratios, runtime_pass=runtime)
    if screen["complete"]:
        values = list(screen["per_scene"].values())
        screen["quality_screen_pass"] = (all(v["no_regression"] for v in values)
            and any(v["gain"] >= config["decision"]["quality_relative_improvement"] for v in values))
        screen["runtime_screen_pass"] = all(v["runtime_pass"] for v in values)
    return screen


def bound_fraction(row):
    result = row["result"]
    wall = result.get("measured_algorithm_wall_s")
    bound = result.get("stats", {}).get("bound_wall_s")
    return bound/wall if finite(wall) and wall > 0 and finite(bound) else None


def write_csv(data):
    targets = list(data["config"]["search"]["quality_targets"])
    fields = ["run_directory", "phase", "scene", "bound", "arm", "initial", "depth", "seconds", "rep",
              "record_status", "result_status", "stop_reason", "exit_code", "protocol_sha256", "raw_result_sha256",
              "J", "returned_J", "Pd", "reference_J", "strict_reference_improvement", "final_original_replay_passed",
              "measured_algorithm_wall_s", "measured_cpu_s", "worker_wall_s", "peak_process_rss_bytes", "budget_overshoot_s",
              "expanded", "work_expanded", "generated", "pruned", "cheap_pruned", "bound_pruned",
              "bound_calls", "bound_wall_s", "bound_wall_fraction", "guide_calls", "guide_wall_s", "post_deadline_incumbents",
              "complete_candidates", "unique_complete_candidates", "unique_new_routes", "duplicate_candidates",
              "early_divergence_candidates", "first_divergence_steps", "group_count", "current_mass", "selected_current_mass",
              "selected_mass_fraction", "original_stdc_bound", "grouped_bound", "bound_value", "reference_suffix_J",
              "interval_closure_fraction", "model_build_s", "solve_s", "solver_status", "restricted_lower_bound",
              "restricted_gap", "candidate_accepted", "mip_start_submitted", "mip_start_roundtrip_verified",
              "solver_mip_node_count"]
    fields += [f"{target}__{metric}" for target in targets
               for metric in ("reached", "time_s", "right_censored", "censor_time_s")]
    with (data["output"] / "comparison.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in data["rows"]:
            task, record, result = row["task"], row["record"], row["result"]
            stats = result.get("stats", {})
            reference = data["config"]["scenes"][task["scene"]]["reference_J"]
            values = {k: task.get(k) for k in ("phase", "scene", "bound", "arm", "initial", "depth", "seconds", "rep")}
            values.update(run_directory=row["run_directory"], record_status=record.get("status"),
                          result_status=result.get("status"), stop_reason=result.get("stop_reason"),
                          exit_code=record.get("exit_code"), protocol_sha256=record.get("protocol_sha256"),
                          raw_result_sha256=record.get("raw_result_sha256"), reference_J=reference,
                          worker_wall_s=record.get("worker_wall_s"), peak_process_rss_bytes=record.get("peak_process_rss_bytes"),
                          final_original_replay_passed=result.get("final_original_replay", {}).get("passed"),
                          bound_wall_fraction=bound_fraction(row), bound_value=result.get("bound"))
            for key in fields:
                if key not in values:
                    values[key] = result.get(key, stats.get(key))
            if good(row):
                values["strict_reference_improvement"] = result["J"] < reference-data["config"]["tolerance"]
            mass, selected = result.get("current_mass"), result.get("selected_current_mass")
            values["selected_mass_fraction"] = selected/mass if finite(mass) and mass > 0 and finite(selected) else None
            if "first_divergence_steps" in stats:
                values["first_divergence_steps"] = json.dumps(stats["first_divergence_steps"], separators=(",", ":"))
            for target in targets:
                times = result.get("time_to_targets_s", {})
                if target in times and good(row):
                    reached = finite(times[target])
                    values[f"{target}__reached"] = reached
                    values[f"{target}__time_s"] = times[target]
                    values[f"{target}__right_censored"] = not reached
                    wall = result.get("measured_algorithm_wall_s", task["seconds"])
                    values[f"{target}__censor_time_s"] = min(task["seconds"], wall) if not reached else None
            writer.writerow(values)


def plot_performance(data):
    # Import plotting only at report-generation time, never during measurements.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    config = data["config"]
    scenes = list(config["scenes"])
    seconds = 5.
    fig, axes = plt.subplots(1, len(scenes), figsize=(4.6*len(scenes), 4.8),
                             squeeze=False, constrained_layout=True, sharey=True)
    target = config["decision"]["time_target"]
    factor = config["search"]["quality_targets"][target]
    expected = config["search"]["repetitions"]
    plt.rcParams.update({"svg.fonttype": "none"})
    largest = 0.
    any_censored = False
    for c, scene in enumerate(scenes):
        ax = axes[0][c]
        for index, arm in enumerate(config["search"]["bounds"]):
            group = sorted((row for row in data["groups"].get(("wall", scene, arm, seconds), []) if good(row)),
                           key=lambda row: row["task"]["rep"])
            values = [row["result"].get("time_to_targets_s", {}).get(target) for row in group]
            reached = [float(value) for value in values if finite(value)]
            color = COLORS.get(arm, "#333333")
            if reached:
                value = median(reached)
                ax.bar(index, value, width=.62, color=color, alpha=.82, edgecolor=color, linewidth=.8)
                ax.errorbar(index, value, yerr=[[value-min(reached)], [max(reached)-value]],
                            fmt="none", ecolor="#222222", capsize=6, elinewidth=1.1, capthick=1.1)
                largest = max(largest, max(reached))
                label = f"{value:.3f} s\n{len(reached)}/{expected} reached"
                if len(reached) < expected:
                    label += "\nconditional median"
                ax.text(index, max(reached)+.08, label, ha="center", va="bottom", fontsize=9)
            else:
                ax.text(index, .04, "No target reached" if group else "No valid runs",
                        rotation=90, ha="center", va="bottom", fontsize=9)
            for point, (row, value) in enumerate(zip(group, values)):
                jitter = (point-(len(group)-1)/2)*.13
                if finite(value):
                    ax.scatter(index+jitter, value, s=27, facecolors="white", edgecolors="#222222",
                               linewidths=.9, zorder=4)
                else:
                    censor = min(seconds, row["result"].get("measured_algorithm_wall_s", seconds))
                    ax.scatter(index+jitter, censor, marker="^", s=38, facecolors="none",
                               edgecolors=color, linewidths=1.2, zorder=4)
                    largest = max(largest, censor)
                    any_censored = True
        title = PLOT_SCENES.get(scene, scene).replace(" [", "\n[")
        ax.set_title(title, fontsize=12)
        ax.set_xticks(range(len(config["search"]["bounds"])), [ARMS[a] for a in config["search"]["bounds"]])
        ax.set_axisbelow(True)
        ax.grid(axis="y", alpha=.2, linewidth=.7)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_xlim(-.6, len(config["search"]["bounds"])-.4)
        if data["fatal"]:
            ax.text(.5, .5, "INVALID: evidence audit failed", color="#B00020",
                    transform=ax.transAxes, ha="center", va="center", fontsize=10)
    ymax = max(1., math.ceil((largest+.65)*2)/2)
    for ax in axes[0]:
        ax.set_ylim(0., ymax)
    axes[0][0].set_ylabel(f"Time to J <= {factor:g} x reference J (s)", fontsize=11)
    legend = [Line2D([0], [0], color="#222222", marker="o", markerfacecolor="white", ls="none", label="Actual repetition"),
              Line2D([0], [0], color="#222222", marker="_", lw=1, label="Observed min-max (not a confidence interval)")]
    if any_censored:
        legend.append(Line2D([0], [0], color="#222222", marker="^", markerfacecolor="none", ls="none",
                             label="Right-censored at termination; not a reached time"))
    fig.legend(handles=legend, loc="outside lower center", ncol=2, fontsize=9)
    fig.suptitle("Time to the predeclared 0.1% quality target | 5 s search budget\nBars: median of reached runs; dots: individual runs", fontsize=13)
    for extension in ("png", "svg"):
        fig.savefig(data["output"] / f"performance.{extension}", dpi=200,
                    metadata={"Title": "STDC final assessment: actual time to fixed quality target"})
    plt.close(fig)


def wall_table(data, seconds, detailed):
    config = data["config"]
    rows = []
    for scene in config["scenes"]:
        for arm in config["search"]["bounds"]:
            group = data["groups"].get(("wall", scene, arm, seconds), [])
            valid = [r for r in group if good(r)]
            line = [SCENES.get(scene, scene), ARMS.get(arm, arm),
                    f"{len(valid)}/{config['search']['repetitions']}",
                    spread(r["result"].get("J") for r in valid),
                    fmt(median(r["result"].get("Pd") for r in valid), 6)]
            if detailed:
                line += [pct(median(bound_fraction(r) for r in valid)),
                         fmt(median(r["result"].get("expanded") for r in valid), 0),
                         fmt(median(r["result"].get("pruned") for r in valid), 0)]
            else:
                line += [target_text(group, config["decision"]["time_target"], config["search"]["repetitions"])]
            rows.append(line)
    headers = ["场景", "下界", "有效/计划", "J 中位数 [最小, 最大]", "Pd 中位数"]
    headers += ["bound 占时", "expanded", "pruned"] if detailed else ["0.1%目标：达到数; 已达中位秒; 删失"]
    return table(headers, rows)


def divergence_text(steps):
    counts = Counter(steps)
    return ", ".join(f"{'同初始' if step is None else step}×{count}"
                     for step, count in sorted(counts.items(), key=lambda item: (item[0] is None, item[0] or 0))) or "—"


def toy_text(data):
    toy = data["toy"]
    if toy is None:
        return "验证集合含 1×4、起点 1、静止粒子位于 0/3、各权重 0.5、H=2、q=0.78 的严格增强构造；未保存 toy JSON，本文不将测试断言伪装为额外实测记录。"
    def lookup(*names):
        for parent in (toy, toy.get("result", {}), toy.get("pair", {}), toy.get("stats", {})):
            if isinstance(parent, dict):
                for name in names:
                    if finite(parent.get(name)):
                        return parent[name]
        return None
    pair = lookup("pair_bound", "shared_pair_bound", "raw_pair_value", "bound")
    independent = lookup("independent_bound", "singleton_bound", "raw_independent_value")
    stdc = lookup("stdc_bound", "STDC", "full_stdc_bound")
    oracle = lookup("oracle_pair", "oracle_pair_bound", "pair_oracle", "oracle_J", "exact_DFS")
    return (f"保存的 1×4 toy（起点1、粒子0/3、各0.5、H=2、q=0.78）给出："
            f"独立粒子下界 {fmt(independent, 2)}、STDC {fmt(stdc, 2)}、共享路径 pair {fmt(pair, 2)}"
            f"，独立枚举 {fmt(oracle, 2)}。这是耦合路线约束能严格增强下界的存在性见证，"
            "不说明大场景每秒求解收益。来源：[pair_toy.json](validation/pair_toy.json)。")


def build_report(data):
    config, protocol, summary = data["config"], data["protocol"], data["summary"]
    screen = data["screen"]
    safe = not data["fatal"] and not data["incomplete"]
    passed = screen["quality_screen_pass"] or screen["runtime_screen_pass"]
    if data["fatal"]:
        headline = "**FATAL：证据或下界检查存在违例，暂停性能结论及路线决策。**"
    elif data["incomplete"]:
        headline = "**实验或触发流程尚不完整，暂不作继续投入/停止投入结论。**"
    elif passed:
        headline = "**STDC 达到预注册的筛选条件；下一步需要独立档案验证，尚不能宣称可外推的优势。**"
    else:
        headline = "**STDC 未达到预注册的质量或时间收益门槛；建议暂停以 STDC 为中心的性能微调，保留其下界和审计价值。**"
    sections = ["# STDC 最后一批评估报告", headline]
    sections.append(f"本报告从最终 [summary.json](summary.json)、冻结 [protocol.json](protocol.json) 与 runs 内原始结果生成。"
                    f"批次 `{config['batch']}`，基线 `{config['base_commit'][:12]}`；正式目录 `{data['output'].name}`。"
                    "数值按记录显示，不把接近门槛视为通过。当前研究问题是：更强的 STDC 下界能否在相同搜索框架内，"
                    "抵消自身计算代价并产生可重复的原目标收益，以及少量早期事件和共享路径约束是否值得继续研究。")
    sections += ["## 1. 冻结问题、对照和继续投入门槛"]
    scene_rows = []
    for name, scene in config["scenes"].items():
        mission = scene["mission"]
        scene_rows.append([SCENES.get(name, name), "×".join(map(str, mission["grid_rows_cols"])),
                           mission["budget"], mission["particles"], fmt(scene["PT_J"]), fmt(scene["reference_J"]),
                           "附条件" if scene["physical_direction_unverified"] else "主要场景"])
    sections.append(table(["场景", "网格", "T", "粒子", "共同 PT J", "历史参考 J", "解释范围"], scene_rows))
    sections.append("目标始终是探测后未发现质量之和 $J=\\sum_{t=1}^{T}M_t$，越小越好；Pd 是同一路径的另一项结果。"
                    "四邻接、无等待、t=0 不探测、粒子列身份和绝对时刻不变，前缀后质量不归一化，特殊 bins 保留质量。"
                    "† Fundy 的物理方向问题仍未解决，只作为带标签的算法回放；主要决策基于 Lake Ontario 与 Hudson 档案。"
                    "本批继承档案来源记录，没有重新审计原始 forcing；固定的500粒子重复运行不是独立验证集。")
    sections.append(f"**质量门槛：**5s 下，STDC 相对 zero/mass 中较好的 J 中位数，在至少一个主要场景改善 ≥{pct(config['decision']['quality_relative_improvement'], 1)}，"
                    "另一场景相对退化不得超过 $10^{-8}$，且重复完整。"
                    f"**时间门槛：**到历史参考 J×{config['search']['quality_targets'][config['decision']['time_target']]:g} 的实际 time-to-target，"
                    f"在两个主要场景均比每一个廉价对照降低 ≥{pct(config['decision']['time_relative_reduction'], 0)}；所有重复必须达到目标，且最终质量不退化。"
                    "二者任一通过才进入新档案验证。pair 根节点只关闭原 U−L 区间 ≥"
                    f"{pct(config['decision']['pair_gap_closure_fraction'], 0)} 时才触发有限接入探索；局部前缀不能替代根节点。")
    sections += ["## 2. 相同框架和墙钟预算的结果", "### 5s 主比较", wall_table(data, 5., True),
                 "### 1s 辅助比较", wall_table(data, 1., False)]
    sections.append(f"每个场景/方法/预算 {config['search']['repetitions']} 次，顺序轮换，统一 PT 起点和 guide 设置；只改变下界。"
                    "表内 J 已排除截止时间后才完成的改善，原返回值和超时 history 仍保留。计时包含任务内部准备、guide、bound 与搜索，"
                    "进程启动、输入读取和环境核验另存 worker_wall_s。范围是观测最小—最大，不是置信区间；仅三次重复不能支持宽泛统计外推。")
    decision_rows = []
    for name in config["primary_scenes"]:
        item = screen["per_scene"].get(name, {})
        decision_rows.append([SCENES.get(name, name), pct(item.get("gain"), 4),
                              fmt(item.get("ratios", {}).get("zero"), 4),
                              fmt(item.get("ratios", {}).get("mass_lb"), 4),
                              "是" if item.get("all_reached") else "否/缺测",
                              "通过" if item.get("runtime_pass") else "未通过"])
    sections.append(table(["主要场景", "STDC质量相对收益", "时间比 STDC/zero", "时间比 STDC/mass", "全部达标", "时间门槛"], decision_rows))
    gate_status = "（仅描述，FATAL/不完整时不生效）" if not safe else ""
    sections.append(f"按原始记录独立复算：质量筛选 {'通过' if screen['quality_screen_pass'] else '未通过'}，"
                    f"时间筛选 {'通过' if screen['runtime_screen_pass'] else '未通过'}{gate_status}。"
                    "时间比大于1表示 STDC 更慢；单纯减少展开数不能替代同质量到达时间。"
                    "这里只比较本机同批结果，旧 Windows 上的绝对时间不参与任何速度比。")
    sections += ["### 实际到达时间与删失"]
    target_rows = []
    for scene in config["scenes"]:
        for arm in config["search"]["bounds"]:
            group = data["groups"].get(("wall", scene, arm, 5.), [])
            target_rows.append([SCENES.get(scene, scene), ARMS[arm]] +
                               [target_text(group, name, config["search"]["repetitions"])
                                for name in config["search"]["quality_targets"]])
    sections.append(table(["场景", "下界", *config["search"]["quality_targets"]], target_rows))
    sections.append("每格依次为达到数/计划数、已达到运行的中位秒、有效运行中的删失数。时间中位数仅对达到者计算，未全部达到时不能视为完整样本中位数；"
                    "未达到不填成5s，也不记成0。CSV 另存真实截止/终止删失时刻；缺测与有效删失分开。"
                    "更难的 reference 目标未达不等于算法失败，但不能据此声称已有速度优势。")
    sections += ["![同质量实际到达时间](performance.png)",
                 "图：5s预算下达到预声明 0.1% 质量目标的实际耗时，纵轴从0起。柱为达到者中位数，圆点为三次真实记录，"
                 "须线为观测最小—最大，不是置信区间；若有未达到者，以空心上三角标明终止删失时刻，不冒充达到时间。"
                 "PNG 与 [SVG](performance.svg) 同图，历史参考只是已知可行解，不是已证明最优值。"]
    sections += ["## 3. bound 计算开销和固定工作量诊断"]
    work_rows = []
    for scene in config["scenes"]:
        for arm in config["search"]["bounds"]:
            group = data["groups"].get(("work", scene, arm, config["search"]["fixed_work_safety_seconds"]), [])
            valid = [r for r in group if good(r)]
            work_rows.append([SCENES.get(scene, scene), ARMS[arm],
                fmt(median(r["result"].get("stats", {}).get("work_expanded") for r in valid), 0),
                fmt(median(r["result"].get("measured_algorithm_wall_s") for r in valid), 4),
                fmt(median(r["result"].get("stats", {}).get("bound_wall_s") for r in valid), 4),
                "/".join(fmt(median(r["result"].get("stats", {}).get(k) for r in valid), 0)
                         for k in ("cheap_pruned", "bound_pruned")),
                fmt(median(r["result"].get("J") for r in valid)),
                ", ".join(sorted({str(r["result"].get("stop_reason")) for r in valid})) or "—"])
    sections.append(table(["场景", "下界", "work expanded", "总秒", "bound秒", "cheap/bound剪枝", "J", "停止原因"], work_rows))
    sections.append(f"冻结工作上限为 {config['search']['fixed_work_expansions']} 次、保护墙钟 {config['search']['fixed_work_safety_seconds']:g}s，"
                    "此组每方法只有一次，只用于定位成本。若实际工作量未齐，不能称为等工作比较；即使齐，"
                    "不同搜索树的工作也不必等价。主表 bound 占时是逐次 bound_wall_s/算法总时长的中位数。"
                    "CSV 同时给出 guide/bound 调用、各类剪枝、generated、展开和实际 RSS；只有剪枝收益足以抵消每次下界求值成本，时间优势才成立。")
    sections += ["## 4. 最多24条早期事件候选"]
    event_rows = []
    events = [r for r in data["rows"] if r["task"]["phase"] == "events"]
    for row in events:
        task, result = row["task"], row["result"]
        stats = result.get("stats", {})
        reference = config["scenes"][task["scene"]]["reference_J"]
        event_rows.append([SCENES.get(task["scene"], task["scene"]), task["initial"],
                           stats.get("complete_candidates", "—"), stats.get("unique_complete_candidates", "—"),
                           stats.get("duplicate_candidates", "—"), divergence_text(stats.get("first_divergence_steps", [])),
                           fmt(result.get("J")),
                           "是" if row["run_directory"] in data["event_witnesses"] else "否" if good(row) else "不可用",
                           fmt(result.get("measured_algorithm_wall_s"), 3)])
    sections.append(table(["场景", "初始路线", "完整", "unique", "duplicates", "首次分歧步×条数", "预算内J", "突破参考", "秒"], event_rows))
    primary_witnesses = [r for r in events if r["task"]["scene"] in config["primary_scenes"]
                         and r["run_directory"] in data["event_witnesses"]]
    early = sum(r["result"].get("stats", {}).get("early_divergence_candidates", 0) for r in events)
    unique_new = sum(r["result"].get("stats", {}).get("unique_new_routes", 0) for r in events)
    sections.append(f"记录中的早期分歧候选合计 {early} 条，各运行 unique_new_routes 合计 {unique_new}（不同初始路线的运行之间不去重）。"
                    f"主要场景严格突破历史参考的运行 {len(primary_witnesses)} 个，正式 follow-up "
                    f"{'被触发' if data['event_followup_required'] else '未被触发'}。"
                    "完整候选计数包括协作截止边界上完成的复算，正式胜出只看预算内选定 J；duplicates 不冒充新搜索方向。"
                    "相对较弱 PT 的改善只说明构造有效，突破历史参考才触发后续。事件顺序是约束设计，实际探测顺序另存 archive；本批有限候选不构成所有早期结构的穷尽否定。")
    follow = [r for r in summary.get("comparisons", []) if r["phase"] == "event_followup"]
    if follow:
        sections.append(table(["follow-up 场景", "有效/计划", "J中位数", "原mass 5s J", "相对改善"], [
            [SCENES.get(item["scene"], item["scene"]), f"{item['valid_runs']}/{item['expected_runs']}",
             fmt(item.get("J", {}).get("median")),
             fmt(median(r["result"]["J"] for r in data["groups"].get(("wall", item["scene"], "mass_lb", 5.), []) if good(r))),
             pct((median(r["result"]["J"] for r in data["groups"].get(("wall", item["scene"], "mass_lb", 5.), []) if good(r))
                  -item["J"]["median"])/median(r["result"]["J"] for r in data["groups"].get(("wall", item["scene"], "mass_lb", 5.), []) if good(r)), 4)
             if item.get("J") and any(good(r) for r in data["groups"].get(("wall", item["scene"], "mass_lb", 5.), [])) else "—"]
            for item in follow]))
    sections += ["## 5. 共享路径 pair 下界的数学信号与成本"]
    sections.append("仅在根和三个预声明前缀做诊断。每个节点先把整段未来 cell-id 序列完全相同的列精确合并，并求当前权重之和；"
                    "不按相近轨迹近似聚类。再从当前质量较大的组中按冻结规则选最多4个互斥 pair，其余质量整体使用 STDC。"
                    "分组各自选路线是原问题的松弛，最终取 $\\max(h_{STDC}(b),\\sum_G h_G+h_{STDC}(b_{rest}))$；"
                    "不能把 pair 增量直接加到 full STDC，也不能宣称混合剩余组必然支配全粒子 singleton DP。")
    pair_rows = []
    pairs = [r for r in data["rows"] if r["task"]["phase"] == "pairs"]
    improved, root_passes = [], []
    for row in pairs:
        task, result = row["task"], row["result"]
        mass, selected = result.get("current_mass"), result.get("selected_current_mass")
        original, lower = result.get("original_stdc_bound"), result.get("bound")
        positive = finite(lower) and finite(original) and lower-original > PAIR_TOLERANCE
        if positive:
            improved.append(row)
        closure = result.get("interval_closure_fraction")
        if (task["depth"] == 0 and task["scene"] in config["primary_scenes"] and result.get("status") == "completed"
                and finite(closure) and closure >= config["decision"]["pair_gap_closure_fraction"]):
            root_passes.append(row)
        pair_rows.append([SCENES.get(task["scene"], task["scene"]), task["depth"], result.get("group_count", "—"),
                          fmt(mass, 4), fmt(selected, 4)+" / "+pct(selected/mass if finite(mass) and mass > 0 and finite(selected) else None, 1),
                          fmt(original), fmt(lower), pct(closure, 4),
                          fmt(result.get("measured_algorithm_wall_s"), 3), result.get("status", "—")])
    sections.append(table(["场景", "depth", "组数", "当前质量", "选中质量/占比", "原STDC", "组合bound", "关闭U−L", "总秒", "状态"], pair_rows))
    sections.append(f"严格超过 $10^{{-10}}$ 的增强发生在 {len(improved)}/{len(pairs)} 个节点；"
                    f"达到根节点 {pct(config['decision']['pair_gap_closure_fraction'], 0)} 筛选门槛的主要场景为 "
                    f"{', '.join(SCENES[r['task']['scene']] for r in root_passes) or '无'}。"
                    "表内区间关闭率为 $(L_{pair}-L_{STDC})/(U-L_{STDC})$，U 是同一固定前缀的已知可行后缀原目标；"
                    "仅浮点噪声的差异不计增强。前缀深处即使比例较大，也只是条件子问题的数学信号。"
                    "总秒包含原 STDC、分组、选对与 DP；有限选中质量限制可能收益，未过门槛不能否定所有耦合下界。"
                    "每个 ordinary/full/grouped/final bound 均独立检查 ≤该 U+1e−10，任何违例均在报告顶部标为 FATAL。")
    sections.append(toy_text(data))
    audit = data["audit"]
    sections += ["## 6. STDC 下界的数学价值及证明边界"]
    sections.append("数学价值与速度收益分开判断。可采纳下界为任一真实合法后缀提供保守代价，根节点可与独立复算的可行 U 构成"
                    " $L_0\\le J^*\\le U$；$U-L_0$ 给出加性次优上界，$L_0>0$ 时 $U/L_0-1$ 给出相对上界。"
                    "更强的 STDC 在理论上能排除更多不可能改善的分支；实现上的求值开销是否值得，必须由上述同框架实验回答。"
                    "中途截断的 OPEN、受限 MILP 的 dual、候选路线的 primal，都不能冒充全局下界证书。")
    sections.append(f"独立标量 DFS 审计状态 `{audit.get('status')}`：{audit.get('model_count')} 个小模型，"
                    f"{audit.get('prefix_evaluations')} 个不同前缀，{audit.get('oracle', {}).get('enumerated_suffix_leaves')} 条枚举后缀；"
                    f"不等式最大正违例 {audit.get('maximum_positive_inequality_violation')}，容差 {audit.get('tolerance')}。"
                    "审计检查可采纳性、非负性、STDC→stepwise→reach/capacity→mass 的支配关系和根区间，覆盖动态轨迹、"
                    "q=0/1/0.78/非均匀 q、未归一化前缀质量和特殊 bins。有限枚举支持实现正确性，普遍命题仍依赖"
                    "[数学推导](../../docs/stdc_final_assessment/theory.md)；pair 的向下浮点 guard 是工程保护，不是形式化区间证明。")
    sections += ["## 7. MILP 四臂受限修复检查"]
    mip_rows = []
    for arm in config["mip"]["arms"]:
        group = [r for r in data["rows"] if r["task"]["phase"] == "mip" and r["task"].get("arm") == arm]
        valid = [r for r in group if good(r)]
        reference = config["scenes"][config["mip"]["scene"]]["reference_J"]
        statuses = Counter((r["record"].get("status"), r["result"].get("status"), r["result"].get("stop_reason")) for r in group)
        status = "; ".join(f"{'/'.join(str(x) for x in key)}×{n}" for key, n in sorted(statuses.items(), key=lambda x: str(x[0]))) or "—"
        mip_rows.append([arm, status, f"{len(valid)}/{config['mip']['repetitions']}",
                         spread(r["result"].get("J") for r in valid),
                         sum(r["result"]["J"] < reference-config["tolerance"] for r in valid),
                         fmt(median(r["result"].get("model_build_s") for r in valid), 3)+" / "+fmt(median(r["result"].get("solve_s") for r in valid), 3),
                         spread((r["result"].get("restricted_lower_bound") for r in valid), 5),
                         pct(median(r["result"].get("restricted_gap") for r in valid), 3)])
    sections.append(table(["臂", "记录/算法/停止原因", "有效/计划", "J中位数 [范围]", "改善次数", "建模/求解秒", "restricted dual [范围]", "restricted gap"], mip_rows))
    sections.append(f"在 {SCENES.get(config['mip']['scene'], config['mip']['scene'])} 固定 depth={config['mip']['prefix_depth']}、"
                    f"corridor radius={config['mip']['corridor_radius']}，warm start 与 objective cutoff 构成2×2；"
                    f"每臂 {config['mip']['repetitions']} 次、每次 {config['mip']['seconds_per_run']:g}s，presolve按冻结设置关闭。"
                    "budget_exceeded 表示预算停止，不等于已证最优；blocked 单列且不伪装成零改善。dual/gap仅属于该受限子问题、"
                    "还是求解器数值估计，不能与全空间 STDC 区间拼接。改善都须原目标复算；候选被接受、solver status、超时及警告原样保留在 raw JSON/日志。")
    mip_all = [r for r in data["rows"] if r["task"]["phase"] == "mip"]
    warm = [r for r in mip_all if r["result"].get("stats", {}).get("warm_start_requested")]
    roundtrips = sum(bool(r["result"].get("stats", {}).get("mip_start_roundtrip_verified")) for r in warm)
    submitted = sum(bool(r["result"].get("stats", {}).get("mip_start_submitted")) for r in warm)
    zero_nodes = sum(r["result"].get("stats", {}).get("solver_mip_node_count") == 0 for r in mip_all)
    overtime = [r["result"].get("budget_overshoot_s") for r in mip_all]
    sections.append(f"warm start 请求 {len(warm)} 次，原生提交 {submitted}/{len(warm)}、读回验证 {roundtrips}/{len(warm)}；"
                    f"记录中 node_count=0 的运行 {zero_nodes}/{len(mip_all)}，不能把它们解释为已经充分探索分支树。"
                    f"合作式30s停止的实测超额秒为 {spread(overtime, 3)}（中位数[范围]），已单独保存；"
                    "不同的停止超额不能作为更快求解的证据。")
    sections += ["## 8. 验证、环境阻塞与证据保存"]
    tests, env = data["tests"], protocol["expected_worker_environment"]
    sections.append(f"冻结验证：pytest 日志 {tests['pytest_passed']} passed、{tests['subtests_passed']} subtests passed；"
                    f"JUnit 实际 tests={tests['tests']}、testcase元素={tests['testcase_elements']}、failures={tests['failures']}、"
                    f"errors={tests['errors']}、skipped={tests['skipped']}。数字直接读取日志/XML，不把子测试重复加成主测试。"
                    f"正式环境：{env.get('platform')}，CPU {env.get('cpu_model')}，Python {env.get('python', '').splitlines()[0]}，"
                    f"NumPy {env.get('numpy')} / SciPy {env.get('scipy')} / HiGHS {env.get('native_highs')}；"
                    "数值库线程数固定1，任务使用新进程串行执行。")
    prior = data["prior"]
    if prior.get("available"):
        sections.append(f"首轮目录保留 {prior['records']} 条启动记录，其中 {prior['blocked']} 条 blocked、{prior['raw_results']} 份算法 raw_result；"
                        "解释器路径中 `asar_repro/../.venv` 与规范化 `.venv` 被严格环境检查误判不一致，失败发生在算法计时前。"
                        "修复解释器路径规范化与首错停止后，重新验证/冻结于 r1。"
                        f"两轮 protocol.config 比较为 {'完全相同' if prior['config_equal'] else '不同，需进一步解释'}；"
                        "旧启动阻塞不纳入 J、Pd 或性能统计，不删除或覆盖。详见"
                        "[首轮记录](../stdc_final_assessment_20261125/RUN_BLOCKED.md)。")
    sections.append(f"本目录实际记录 {len(data['rows'])} 条；证据审计发现 fatal {len(data['fatal'])} 项、不完整 {len(data['incomplete'])} 项。"
                    "每次运行的 task、record、raw_result、stdout.log、stderr.log 均保留；脚本复核 protocol/raw/验证和冻结源码哈希。"
                    "[comparison.csv](comparison.csv) 一行对应一次运行，包含原始路径、状态、删失和成本，可追溯表格。"
                    "正式计时结束后生成本报告与图，不重跑算法、不改写结果；toy为追加验证证据，原有冻结验证文件不变。")
    preservation = data.get("preservation")
    if preservation is not None:
        sections.append(f"[最终保全记录](final_preservation.json) 状态 `{preservation.get('status')}`："
                        f"基点原有 {preservation.get('original_source_files_checked')} 个源文件逐个 git blob 比对，"
                        f"修改 {len(preservation.get('original_source_changed', []))} 个；"
                        f"输入粒子保持不变={preservation.get('input_particles_unchanged')}，"
                        f"正式 blocked={len(preservation.get('formal_blocked_runs', []))}。本报告还重新核对了三个输入及 metadata 的 SHA256。")
    if data["fatal"] or data["incomplete"] or data["notices"]:
        sections.append("### 自动审计明细")
        sections.append("\n".join(f"- **{kind}**：{message}" for kind, messages in
                                   (("FATAL", data["fatal"]), ("不完整", data["incomplete"]), ("说明", data["notices"]))
                                   for message in messages))
    sections += ["## 9. 下一步策略"]
    independent = summary.get("decision", {}).get("independent_validation")
    sections.append(f"**F阶段（独立档案验证）状态：`{independent}`。**"
                    + ("本批未触发进入F阶段，没有实施新的独立档案实验；" if independent == "not_triggered" else
                       "当前独立档案验证尚未完成；")
                    + "同一500粒子的重复计时只检查运行波动，从未记作 holdout。")
    if not safe:
        sections.append("先处理上述证据违例或未完成任务，重新汇总并运行报告；在此之前不使用任何自动 gate 推动路线决定。"
                        "若下界超过已知可行后缀，应优先核查绝对时刻、当前质量、分组互斥与数值处理，不能以放宽容差掩盖。")
    elif passed:
        sections.append("冻结筛选支持下一步投入独立验证：取得新的固定粒子档案和预先确定测试集，再复用同质量/同预算对照。"
                        "当前未提供独立档案，因此不以重复500粒子调参代替外推检验。STDC 的数学审计和可重复基线继续保留；"
                        "先验证收益稳定性，再决定扩展算法复杂度。")
    else:
        sections.append("执行冻结止损规则：暂停继续围绕 STDC 做细碎性能调整，保留它作为安全下界、研究基线和根区间工具。"
                        "后续研究优先要求新的可观测机制：能改变早期访问结构的候选，或在更大质量上显著缩紧的共享路线约束；"
                        "都先以有限成本产生严格参考改善或足够根区间缩紧，再接入搜索并检验净时间收益。"
                        "本批没有达到门槛的数学信号仍应保存，但不能以接近门槛或条件前缀改善为由事后改变通过标准。")
    if safe and root_passes:
        sections.append("pair 根门槛已被实际记录触发，可安排预先限额的搜索接入试验；此次诊断还未测得端到端搜索收益，不能直接升级为性能结论。")
    if safe and summary.get("decision", {}).get("event_formal_screen_pass"):
        sections.append("事件+后续搜索已通过其独立预注册筛选，进入新档案验证队列；它与 STDC 本身是否获益分开记账。")
    return "\n\n".join(sections) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--prior-output", type=Path, default=DEFAULT_PRIOR)
    args = parser.parse_args()
    output = args.output.resolve()
    data = read_evidence(output, args.prior_output.resolve())
    write_csv(data)
    plot_performance(data)
    (output / "FINAL_REPORT.md").write_text(build_report(data), encoding="utf-8")
    print(json.dumps(dict(report=str(output / "FINAL_REPORT.md"), csv=str(output / "comparison.csv"),
                          figure=[str(output / "performance.png"), str(output / "performance.svg")],
                          fatal=len(data["fatal"]), incomplete=len(data["incomplete"])), ensure_ascii=False))
    return 2 if data["fatal"] else 1 if data["incomplete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
