"""Post-run, read-only replay and evidence audit of the registered progress P30 pilot.

Run from asar_repro with the recorded Python environment and one completed output
directory. Replays routes but does not rerun any search or generate particles.
Writes one audit JSON without changing existing results.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from math import isclose, isfinite
from pathlib import Path
from statistics import median
import json
import sys

METHODS = ("C0", "C0_PREFIX", "C0_PROGRESS")
PAIRS = (
    ("fixed_vs_control", "C0_PREFIX", "C0"),
    ("progress_vs_control", "C0_PROGRESS", "C0"),
    ("progress_vs_fixed", "C0_PROGRESS", "C0_PREFIX"),
)
RAW_TIMINGS = ("guide_s", "transition_s", "replay_s", "completion_s")
HISTORICAL_PREVIOUS_BEST = {
    "hudson_h2_d1_s4101": 28.448979882240007,
    "hudson_h2_d2_s4201": 58.5220872,
}
HISTORICAL_4201_ROLLING = 58.677655392


def require(check, detail):
    if not check:
        raise ValueError(detail)


def read(path):
    return json.loads(path.read_bytes())


def file_hash(path):
    with path.open("rb") as stream:
        h = sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
        return h.hexdigest()


def object_hash(value):
    body = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)
    return sha256(body.encode("utf-8")).hexdigest()


def same_score(actual, expected):
    return (
        actual["waypoints"] == expected["waypoints"]
        and actual["observation_times_s"] == expected["observation_times_s"]
        and len(actual["survival"]) == len(expected["survival"])
        and all(isclose(actual[k], expected[k], rel_tol=0, abs_tol=1e-8)
                for k in ("J", "pd_final", "physical_duration_s"))
        and all(isclose(a, b, rel_tol=0, abs_tol=1e-8)
                for a, b in zip(actual["survival"], expected["survival"]))
    )


def inspect_progress(inner, method, design):
    diag = inner["diagnostics"]
    history = inner["history"]
    budget = inner["max_seconds"]
    require(history and history[0]["source"] == "initial_route", "Missing S30 incumbent history")
    require(all(0 <= row["elapsed_s"] <= budget for row in history), "Invalid incumbent clock")
    require(all(a["elapsed_s"] <= b["elapsed_s"] and b["J"] < a["J"] - 1e-10
                for a, b in zip(history, history[1:])), "Noncausal or non-improving incumbent")
    first_terminal = diag["first_search_terminal_generated_s"]
    first = next((row["elapsed_s"] for row in history if row["source"] == "search"), None)
    require(first is None or (first_terminal is not None and first_terminal <= first),
            "Strict search improvement precedes the first generated search terminal")
    gate = design["progress_policy"]["activation"]
    cutoff = budget * gate["first_search_improvement_before_fraction"]
    order = diag.get("prefix_order") or {}
    progress = diag.get("progress_schedule")
    require((progress is not None) == (method == "C0_PROGRESS"), "Unexpected progress scheduler")
    reserved = order.get("reserved_early_pops", 0) + order.get("reserved_middle_pops", 0)
    events = []
    if progress is not None:
        require(progress["first_search_improvement_s"] == first, "Search gate history disagrees")
        require(reserved <= progress["active_decisions"] <= progress["checked_pops"]
                and progress["checked_pops"] == order["global_pops"] + reserved
                and 0 <= order["empty_band_fallback_pops"] <= order["global_pops"],
                "Inconsistent OPEN scheduling counts")
        active = False
        previous_event = -1.0
        for event in progress["events"]:
            at = event["elapsed_s"]
            fraction = event["tail_fraction"]
            require(previous_event <= at <= budget and 0 <= fraction <= 1
                    and (fraction * gate["window_expansions"]).is_integer(),
                    "Invalid scheduler event clock or tail fraction")
            require(first is not None and first <= cutoff and first <= at,
                    "Scheduler used ineligible or future search progress")
            latest = next(row for row in reversed(history) if row["elapsed_s"] <= at)
            since_best = at - latest["elapsed_s"]
            if event["event"] == "on":
                require(not active and fraction >= gate["tail_enter_fraction"]
                        and since_best >= gate["stagnation_seconds"], "Invalid activation")
                active = True
            else:
                require(event["event"] == "off" and active
                        and (fraction < gate["tail_exit_fraction"]
                             or since_best < gate["recent_improvement_pause_s"]), "Invalid deactivation")
                active = False
            events.append(dict(event, since_best_s=since_best))
            previous_event = at
        require(sum(e["event"] == "on" for e in events) == progress["activations"]
                and sum(e["event"] == "off" for e in events) == progress["deactivations"]
                and active == progress["active"] and (bool(events) or reserved == 0),
                "Scheduler event state differs from final record")
    return dict(
        first_search_improvement_s=first,
        first_search_terminal_s=first_terminal,
        first_search_cutoff_s=cutoff if progress else None,
        search_improved_early=(first is not None and first <= cutoff) if progress else None,
        first_accepted_incumbent_s=history[1]["elapsed_s"] if len(history) > 1 else None,
        best_inner_s=inner["best_elapsed_s"],
        best_source=history[-1]["source"],
        activations=sum(e["event"] == "on" for e in events),
        deactivations=sum(e["event"] == "off" for e in events),
        reserved_early_pops=order.get("reserved_early_pops", 0),
        reserved_middle_pops=order.get("reserved_middle_pops", 0),
        empty_band_fallback_pops=order.get("empty_band_fallback_pops", 0),
        events=events,
    )


def matrix_comparisons(rows, instances, thresholds, archive):
    groups = []
    representatives = {}
    for instance in instances:
        for method in METHODS:
            repeats = [r for r in rows if r["instance"] == instance and r["method"] == method]
            require(len(repeats) == 3, f"{instance} {method} does not have three repeats")
            selected = sorted(repeats, key=lambda r: (r["J"], r["repetition"]))[1]
            representatives[instance, method] = selected
            historical = HISTORICAL_PREVIOUS_BEST.get(instance)
            quantities = ("algorithm_wall_s", "algorithm_cpu_s", "process_wall_s",
                          "independent_audit_s", "peak_rss_mib", "expanded", "generated",
                          "peak_open", "terminal_candidates", "completion_calls",
                          "early_expanded", "middle_expanded", "last_two_tick_fraction", *RAW_TIMINGS)
            groups.append(dict(
                instance=instance, method=method, J=selected["J"], Pd=selected["Pd"],
                representative_id=selected["run_id"], representative_repetition=selected["repetition"],
                medians={key: median(row[key] for row in repeats) for key in quantities},
                max_peak_rss_mib=max(row["peak_rss_mib"] for row in repeats),
                max_peak_open=max(row["peak_open"] for row in repeats),
                stops=dict(Counter(row["stop_reason"] for row in repeats)),
                search_terminals_s=[row["first_search_terminal_s"] for row in repeats],
                search_improvements_s=[row["first_search_improvement_s"] for row in repeats],
                activation_counts=[row["activations"] for row in repeats],
                repeats=[row["run_id"] for row in repeats],
                archived_best_J=historical,
                gain_vs_archived_best=None if historical is None else (historical-selected["J"])/historical,
                archived_4201_rolling_J=(HISTORICAL_4201_ROLLING if instance.endswith("4201") else None),
            ))
    pairs, screens = [], []
    for name, candidate, control in PAIRS:
        comparison = []
        for instance in instances:
            a, b = representatives[instance, candidate], representatives[instance, control]
            gain = (b["J"] - a["J"]) / b["J"]
            dp = a["Pd"] - b["Pd"]
            comparison.append(dict(
                pair=name, instance=instance, region=instance.split("_")[0],
                candidate=candidate, control=control,
                candidate_run_id=a["run_id"], control_run_id=b["run_id"],
                candidate_J=a["J"], control_J=b["J"], candidate_Pd=a["Pd"], control_Pd=b["Pd"],
                relative_J_gain=gain, delta_Pd_pp=100 * dp,
                threshold_0p1=gain >= thresholds["minimum_relative_J_improvement"],
                threshold_0p5=gain >= thresholds["secondary_relative_J_improvement"],
                J_nonregression=gain >= -thresholds["relative_J_nonregression_tolerance"],
                Pd_guard=dp >= -thresholds["max_terminal_Pd_drop"],
            ))
        wins = [r for r in comparison if r["threshold_0p1"]]
        regional = Counter(row["region"] for row in wins)
        nonregression = all(r["J_nonregression"] for r in comparison)
        pd_guard = all(r["Pd_guard"] for r in comparison)
        screens.append(dict(
            pair=name, passed=(len(wins) >= thresholds["minimum_winning_instances"]
                               and all(regional[region] >= thresholds["minimum_wins_per_region"]
                                       for region in ("lake", "hudson")) and nonregression and pd_guard),
            threshold_0p1=len(wins), threshold_0p5=sum(r["threshold_0p5"] for r in comparison),
            all_J_nonregression=nonregression, all_Pd_guard=pd_guard, regions_with_0p1=sorted(regional),
        ))
        pairs.extend(comparison)
    require(screens == archive["screens"] and len(pairs) == len(archive["pairs"]),
            "Published decision differs from independent aggregation")
    for comparison, observed in zip(pairs, archive["pairs"]):
        require(all(observed[key] == value for key, value in comparison.items()),
                "Published representative route or metric differs from independent aggregation")
    primary = next(screen for screen in screens if screen["pair"] == "progress_vs_control")
    label = "progress_prefix_development_screen_" + ("passed" if primary["passed"] else "not_passed")
    require(archive["status"] == label and archive["primary_decision"] == "progress_vs_control"
            and archive["valid_runs"] == archive["expected_runs"] == len(rows)
            and archive["optimality_certified"] is False, "Published verdict is inconsistent")
    return groups, pairs, screens, label


def audit(out, root):
    sys.path[:0] = [str(root / "scripts"), str(root / "src")]
    import run_eight_neighbor_progress as runner
    from asar_repro.h2_inputs import load_h2_input
    from asar_repro.physical_search import independent_replay

    protocol, tasks = runner.verify(out)
    runner.require_validation(out)
    runner.check_protected_checkout()
    references = protocol["references"]
    design = protocol["design"]
    evidence = dict(
        protocol_sha256=file_hash(out / "protocol.json"),
        validation_sha256=file_hash(out / "validation" / "validation.json"),
        progress_policy_sha256=object_hash(design["progress_policy"]),
    )
    problems = {}
    for instance in design["instances"]:
        case = references["instances"][instance]
        problem, _, _, info = load_h2_input(
            root, case, root / protocol["config"]["source_root"] / "inputs" / instance, "heading_square",
        )
        source = references["archive_hashes"][instance]
        seed = references["references"][instance]
        require(info["manifest_sha256"] == source["manifest_sha256"]
                and info["particle_sha256"] == source["particle_sha256"]
                and info["forcing_kind"] == "historical_real"
                and info["opendrift_runs_in_search"] == 0, f"{instance} cache differs from freeze")
        require(object_hash(seed) == next(t["reference_sha256"] for t in tasks if t["instance"] == instance),
                f"{instance} seed differs from freeze")
        problems[instance] = problem

    runs = out / "runs"
    identities = {"P30_" + object_hash(task)[:20]: task for task in tasks}
    require(len(identities) == 36 and set(identities) == {p.name for p in runs.iterdir()},
            "Unexpected or missing frozen run directories")
    rows = []
    for identity, task in identities.items():
        folder = runs / identity
        record = read(folder / "record.json")
        result_path = folder / "result.json"
        payload = read(result_path)
        require(task == record["task"] == payload["task"] == read(folder / "task.json")
                and record["frozen_evidence"] == evidence
                and record["result_sha256"] == file_hash(result_path)
                and record["status"] == "completed" and record["returncode"] == 0
                and record["watchdog"] is None and record["verification_error"] is None
                and (folder / "stdout.log").is_file() and (folder / "stderr.log").is_file()
                and isinstance(record["peak_rss_bytes"], int) and record["peak_rss_bytes"] > 0,
                f"{identity}: invalid task, result, or budget evidence")
        result = payload["result"]
        runner.check_result(task, result, protocol)
        score = result["physical_replay"]
        problem = problems[task["instance"]]
        route = score["waypoints"]
        require(same_score(problem.replay(route, connectivity=8), score)
                and same_score(independent_replay(problem, route, connectivity=8), score),
                f"{identity}: dual route replay differs from the record")
        inner = result["raw"]["phases"][0]["inner"]
        verify = inspect_progress(inner, task["method"], design)
        histogram = {int(t): count for t, count in inner["diagnostics"]["histograms"]["expanded_tick"].items()}
        ticks = len(score["observation_times_s"])
        stats = inner["stats"]
        require(sum(histogram.values()) == inner["expanded"]
                and all(0 <= t < ticks and s > 0 for t, s in histogram.items()),
                f"{identity}: invalid expansion histogram")
        timings = {key: inner["timings"][key] for key in RAW_TIMINGS}
        require(all(isfinite(v) and v >= 0 for v in timings.values()), f"{identity}: invalid timing")
        rows.append(dict(
            **task, run_id=identity, J=score["J"], Pd=score["pd_final"],
            algorithm_wall_s=result["algorithm_wall_s"], algorithm_cpu_s=result["algorithm_cpu_s"],
            independent_audit_s=result["independent_audit_s"], process_wall_s=record["process_wall_s"],
            peak_rss_mib=record["peak_rss_bytes"] / 2**20,
            expanded=inner["expanded"], generated=inner["generated"], peak_open=inner["peak_open"],
            terminal_candidates=stats["terminal_candidates"], completion_calls=stats["completion_calls"],
            early_expanded=sum(n for t, n in histogram.items() if 4 * t < ticks),
            middle_expanded=sum(n for t, n in histogram.items() if ticks <= 4 * t < 3 * ticks),
            last_two_tick_fraction=sum(n for t, n in histogram.items() if t >= ticks-2) / max(1, inner["expanded"]),
            stop_reason=inner["stop_reason"], **timings, **verify,
        ))
    groups, pairs, screens, status = matrix_comparisons(
        rows, design["instances"], design["decision"], read(out / "summary.json"),
    )
    destination = out / "independent_verification.json"
    with destination.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(dict(status="verified", observed=36, protocol_evidence=evidence, decision=status,
                       dual_route_replay=True,
                       scheduler_scope="Recorded clocks and fractions only. Rolling-window membership is not exposed.",
                       runs=rows, method_instances=groups, pairs=pairs, screens=screens),
                  stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
    for row in groups:
        print(f"{row['instance']} {row['method']} J={row['J']:.9f} Pd={100*row['Pd']:.6f}% "
              f"RSSmed={row['medians']['peak_rss_mib']:.1f} MiB "
              f"activations={row['activation_counts']}")
    print(f"Verified 36 frozen tasks, dual replays and three independent median screens. {status}")
    print(destination)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage from asar_repro: python progress_batch_verify.py <completed-output-directory>")
    audit(Path(sys.argv[1]).resolve(), Path.cwd())
