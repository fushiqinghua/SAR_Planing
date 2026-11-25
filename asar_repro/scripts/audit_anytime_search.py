"""Global anytime search and every-prefix bound audit on 45 synthetic toys.

All 35 historical small_case seeds 15000..15034 remain unchanged. Five
stationary-matrix and five synthetic-particle derivatives are explicitly
additional inputs, shared with the earlier window-search audit. No real
forcing or particle archive is replaced by a synthetic case.

Paper-greedy values only order OPEN. Finite Oracle agreement is reported as
numerical evidence, never as an unconditional or epsilon certificate.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import sys
from time import perf_counter
import traceback

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from asar_repro.anytime_search import search_anytime
from asar_repro.heuristic import Heuristic
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from audit_window_search import cases, reference_path
from stdc_validation_guards import freeze_case


BOUND_MODES = ("zero", "mass_lb", "stdc_lb")
GUIDE_WEIGHTS = (1.0, 1.04, 1.1)
ATOL = 1e-10


def _require(condition, message):
    if not condition:
        raise AssertionError(message)


def _native(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _native(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_native(item) for item in value]
    return value


def _save(path, value):
    path.write_text(json.dumps(_native(value), ensure_ascii=False, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8")


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def independent_prefix_optima(grid, cfg):
    """Enumerate all full routes, then take full-replay minima by prefix.

    The DFS has no merging or pruning and uses no heuristic, state-update,
    suffix-coefficient, or search implementation. Remaining prefix costs are
    obtained later by subtracting a separate frozen prefix replay.
    """
    route = [cfg["start"]]
    best = {}
    best_paths = {}
    complete_count = 0

    def visit():
        nonlocal complete_count
        if len(route) == cfg["budget"] + 1:
            complete_count += 1
            path = tuple(route)
            score = score_path(grid, path, **cfg)
            for depth in range(cfg["budget"] + 1):
                prefix = path[:depth + 1]
                if score.J < best.get(prefix, math.inf):
                    best[prefix] = score.J
                    best_paths[prefix] = path
            return
        for vertex in grid.neighbors(route[-1]):
            route.append(vertex)
            visit()
            route.pop()

    visit()
    _require(complete_count > 0, "toy case has no complete path")
    return best, best_paths, complete_count


def verify_history(grid, cfg, result):
    previous = math.inf
    max_j_error = 0.0
    max_pd_error = 0.0
    for item in result.incumbent_history:
        score = score_path(grid, item["path"], **cfg)
        error_j = abs(score.J - item["J"])
        error_pd = abs(score.pd_final - item["Pd"])
        _require(error_j <= ATOL and error_pd <= ATOL, "incumbent history replay mismatch")
        _require(item["J"] < previous, "incumbent history did not strictly improve J")
        _require(item["source"] in ("initial_path", "search"), "unknown incumbent source")
        previous = item["J"]
        max_j_error = max(max_j_error, error_j)
        max_pd_error = max(max_pd_error, error_pd)
    _require(result.incumbent_history and abs(previous - result.J) <= ATOL,
             "last incumbent history entry differs from final result")
    return max_j_error, max_pd_error


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="new directory or an existing empty directory")
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FileExistsError(f"refusing to overwrite nonempty output: {output}")
    output.mkdir(parents=True, exist_ok=True)
    inputs = output / "inputs"
    inputs.mkdir()
    rows = []
    completed_cases = []
    current = None
    prefix_count = 0
    max_bound_overestimate = {mode: 0.0 for mode in BOUND_MODES}
    started = perf_counter()
    try:
        _save(output / "protocol.json", {
            "command": [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
            "historical_seeds": list(range(15000, 15035)),
            "derived_seeds": list(range(15000, 15005)),
            "expected_cases": 45, "expected_searches": 405,
            "case_counts": {"historical_dynamic_matrix": 35, "derived_stationary_matrix": 5,
                            "derived_synthetic_particle": 5},
            "bound_modes": BOUND_MODES, "guide_weights": GUIDE_WEIGHTS,
            "initial_path_policy": "same deterministic unoptimized route per seed for all 9 runs",
            "limits": None, "tolerance": ATOL, "data_type": "synthetic_toy",
            "guide_used_for_pruning": False, "guide_used_for_termination": False,
            "bound_is_unweighted": True, "global_epsilon_certified": False,
            "scope": "finite numerical global Oracle agreement on these toy inputs only",
            "source_sha256": {str(path.relative_to(ROOT)): _sha(path) for path in (
                Path(__file__).resolve(), ROOT / "scripts/audit_window_search.py",
                ROOT / "scripts/stdc_validation_guards.py", ROOT / "scripts/run_stdc_small_search.py",
                ROOT / "src/asar_repro/anytime_search.py", ROOT / "src/asar_repro/heuristic.py",
                ROOT / "src/asar_repro/stdc_heuristic.py", ROOT / "src/asar_repro/objective.py",
                ROOT / "src/asar_repro/oracle.py", ROOT / "src/asar_repro/motion.py",
            )},
        })
        with ((output / "prefixes.jsonl").open("w", encoding="utf-8", buffering=1) as prefix_stream,
              (output / "results.jsonl").open("w", encoding="utf-8", buffering=1) as search_stream):
            for kind, seed, grid, cfg, derivation in cases():
                current = {"kind": kind, "seed": seed}
                label = f"{kind}_{seed}"
                input_sha = freeze_case(inputs, label, grid, cfg)
                initial_path = reference_path(grid, cfg, seed)
                initial = score_path(grid, initial_path, **cfg)
                route_file = inputs / f"{label}_initial_path.json"
                _save(route_file, {"seed": seed, "kind": kind, "initial_path": initial_path,
                                   "derivation": derivation, "data_type": "synthetic_toy"})
                route_sha = _sha(route_file)
                _save(output / "last_checked.json", {"stage": "oracle_start", **current})
                oracle_started = perf_counter()
                oracle = enumerate_oracle(grid, **cfg)
                best, best_paths, complete_count = independent_prefix_optima(grid, cfg)
                oracle_wall = perf_counter() - oracle_started
                _require(abs(best[(cfg["start"],)] - oracle.J) <= ATOL,
                         f"independent DFS disagrees with frozen Oracle: {current}")
                _require(complete_count == oracle.complete_paths,
                         f"full-path enumeration count differs: {current}")
                bounds = {mode: Heuristic(grid, budget=cfg["budget"], q=cfg["q"],
                                          motion=cfg["motion"], mode=mode)
                          for mode in BOUND_MODES}
                paper = Heuristic(grid, budget=cfg["budget"], q=cfg["q"],
                                  motion=cfg["motion"], mode="paper_greedy")
                root_guide = float(paper(cfg["start"], 0, cfg["p"]))
                for prefix in sorted(best, key=lambda route: (len(route), route)):
                    depth = len(prefix) - 1
                    score = score_path(grid, prefix, **{**cfg, "budget": depth})
                    remaining = best[prefix] - score.J
                    estimates = {mode: float(bound(prefix[-1], depth, score.final_belief))
                                 for mode, bound in bounds.items()}
                    evidence = {**current, "stage": "prefix_admissibility", "input_sha256": input_sha,
                                "prefix": prefix, "prefix_J": score.J, "exact_remaining": remaining,
                                "best_full_path": best_paths[prefix], "bounds": estimates}
                    _save(output / "last_checked.json", evidence)
                    prefix_stream.write(json.dumps(_native(evidence), allow_nan=False) + "\n")
                    for mode, value in estimates.items():
                        _require(math.isfinite(value) and -ATOL <= value <= remaining + ATOL,
                                 f"{mode} bound failed: {current}, prefix={prefix}")
                        max_bound_overestimate[mode] = max(max_bound_overestimate[mode], value - remaining)
                    prefix_count += 1

                for guide_weight in GUIDE_WEIGHTS:
                    for mode in BOUND_MODES:
                        current = {"kind": kind, "seed": seed, "guide_weight": guide_weight,
                                   "bound_mode": mode}
                        _save(output / "last_checked.json", {"stage": "search_start", **current})
                        tic = perf_counter()
                        result = search_anytime(grid, **cfg, initial_path=initial_path,
                                                guide_weight=guide_weight, bound_mode=mode)
                        wall = perf_counter() - tic
                        _require(result.path is not None, f"missing complete incumbent: {current}")
                        score = score_path(grid, result.path, **cfg)
                        _save(output / "last_checked.json", {"stage": "history_check", **current,
                                                              "result": asdict(result)})
                        history_j_error, history_pd_error = verify_history(grid, cfg, result)
                        checks = {
                            "completed": result.status == "completed",
                            "normal_stop": result.stop_reason is None,
                            "not_certified": result.theory_certified is False,
                            "global_Oracle_J": abs(score.J - oracle.J) <= ATOL,
                            "J_replay": abs(score.J - result.J) <= ATOL,
                            "Pd_replay": abs(score.pd_final - result.Pd) <= ATOL,
                            "nonworsening_J": score.J <= initial.J + ATOL,
                            "initial_incumbent_source": result.incumbent_history[0]["source"] == "initial_path",
                            "guide_not_pruning": result.stats["guide_used_for_pruning"] is False,
                            "guide_not_termination": result.stats["guide_used_for_termination"] is False,
                            "unweighted_bound": result.stats["bound_is_unweighted"] is True,
                            "no_state_merging": result.stats["state_merging"] is False,
                            "full_path_horizon": len(result.path) == cfg["budget"] + 1,
                            "mass_nonincreasing": float(np.max(np.diff(score.survival), initial=0)) <= ATOL,
                            "t0_no_observation": score.g[0] == 0 and abs(score.survival[0] - 1) <= ATOL,
                        }
                        row = {**current, "input_sha256": input_sha, "initial_path_sha256": route_sha,
                               "data_type": "synthetic_toy", "derivation": derivation,
                               "initial_J": initial.J, "initial_Pd": initial.pd_final,
                               "oracle_J": oracle.J, "oracle_path": oracle.path,
                               "oracle_complete_paths": complete_count, "oracle_wall_s": oracle_wall,
                               "root_paper_guide": root_guide, "paper_root_overestimate": root_guide - oracle.J,
                               "result": asdict(result), "search_wall_s": wall,
                               "replay_J": score.J, "replay_Pd": score.pd_final,
                               "J_minus_oracle": score.J - oracle.J,
                               "J_replay_error": abs(score.J - result.J),
                               "Pd_replay_error": abs(score.pd_final - result.Pd),
                               "history_J_replay_error": history_j_error,
                               "history_Pd_replay_error": history_pd_error,
                               "checks": checks, "status": "passed" if all(checks.values()) else "blocked"}
                        _save(output / "last_checked.json", row)
                        search_stream.write(json.dumps(_native(row), allow_nan=False) + "\n")
                        _require(all(checks.values()), f"anytime search gate failed: {current}; {checks}")
                        rows.append(row)
                completed_cases.append(label)
                if len(completed_cases) % 5 == 0:
                    print(f"validated {len(completed_cases)}/45 anytime cases; searches={len(rows)}; "
                          f"prefixes={prefix_count}", flush=True)
        _require(len(completed_cases) == 45 and len(rows) == 405, "incomplete anytime audit")
        aggregates = []
        for kind in ("historical_dynamic_matrix", "derived_stationary_matrix", "derived_synthetic_particle"):
            for guide_weight in GUIDE_WEIGHTS:
                for mode in BOUND_MODES:
                    group = [row for row in rows if row["kind"] == kind
                             and row["guide_weight"] == guide_weight and row["bound_mode"] == mode]
                    aggregates.append({
                        "kind": kind, "guide_weight": guide_weight, "bound_mode": mode,
                        "searches": len(group),
                        "mean_expanded": float(np.mean([row["result"]["expanded"] for row in group])),
                        "mean_search_wall_s": float(np.mean([row["search_wall_s"] for row in group])),
                        "mean_bound_calls": float(np.mean([row["result"]["stats"]["bound_calls"] for row in group])),
                        "mean_guide_calls": float(np.mean([row["result"]["stats"]["guide_calls"] for row in group])),
                        "max_absolute_J_minus_oracle": max(abs(row["J_minus_oracle"]) for row in group),
                    })
        summary = {
            "status": "passed", "cases": len(completed_cases), "searches": len(rows),
            "case_counts": {"historical_dynamic_matrix": 35, "derived_stationary_matrix": 5,
                            "derived_synthetic_particle": 5},
            "bound_modes": BOUND_MODES, "guide_weights": GUIDE_WEIGHTS, "tolerance": ATOL,
            "prefix_evaluations": prefix_count, "max_bound_overestimate": max_bound_overestimate,
            "data_type": "synthetic_toy", "global_epsilon_certified": False,
            "scope": "finite numerical global Oracle agreement; paper guide remains nonadmissible",
            "independent_final_replays": len(rows),
            "max_absolute_J_minus_oracle": max(abs(row["J_minus_oracle"]) for row in rows),
            "max_J_replay_error": max(row["J_replay_error"] for row in rows),
            "max_Pd_replay_error": max(row["Pd_replay_error"] for row in rows),
            "max_history_J_replay_error": max(row["history_J_replay_error"] for row in rows),
            "max_history_Pd_replay_error": max(row["history_Pd_replay_error"] for row in rows),
            "aggregate": aggregates, "total_wall_s": perf_counter() - started,
        }
        _save(output / "summary.json", summary)
        print(json.dumps({key: summary[key] for key in ("status", "cases", "searches", "prefix_evaluations",
                                                       "max_absolute_J_minus_oracle")}, allow_nan=False), flush=True)
    except Exception as exc:
        _save(output / "summary.json", {
            "status": "blocked", "completed_cases": completed_cases,
            "completed_searches": len(rows), "prefix_evaluations": prefix_count,
            "current": current, "error_type": type(exc).__name__, "error": str(exc),
            "data_type": "synthetic_toy", "global_epsilon_certified": False,
        })
        (output / "failure_traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
        print(f"blocked: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise


if __name__ == "__main__":
    main()
