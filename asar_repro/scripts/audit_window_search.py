"""Fail-fast fixed-window search audit against independent full-path DFS.

The 35 historical small_case inputs (seeds 15000..15034) are unchanged.
Five stationary-matrix and five synthetic-particle derivatives are explicitly
additional cases. No real archive or forcing is substituted by these toys.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
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

from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.window_search import solve_window
from stdc_validation_guards import freeze_case, small_case


MODES = ("zero", "mass_lb", "stdc_lb", "stdc_endpoint_lb")
ATOL = 1e-10
HISTORICAL_SEEDS = tuple(range(15000, 15035))
DERIVED_SEEDS = tuple(range(15000, 15005))


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


def cases():
    """Retain all 35 original inputs, then add labelled motion derivatives."""
    for seed in HISTORICAL_SEEDS:
        grid, cfg = small_case(seed)
        yield "historical_dynamic_matrix", seed, grid, cfg, "unchanged small_case(seed)"
    for seed in DERIVED_SEEDS:
        grid, cfg = small_case(seed)
        derived = {**cfg, "motion": MatrixMotion.stationary(cfg["motion"]._matrices[0])}
        yield ("derived_stationary_matrix", seed, grid, derived,
               "repeat the historical first transition kernel; retain grid, p, q, start and T")
    for seed in DERIVED_SEEDS:
        grid, cfg = small_case(seed)
        rng = np.random.default_rng(seed + 2_000_000)
        count = 8
        cells = rng.integers(0, grid.size, size=(cfg["budget"] + 1, count))
        cells[:, -4:] = grid.size + np.arange(4)
        ids = seed * 100 + np.array([31, 4, 77, 2, 91, 8, 65, 19])
        derived = {**cfg, "p": rng.dirichlet(np.ones(count)),
                   "motion": ParticleMotion(cells, grid.size, ids)}
        yield ("derived_synthetic_particle", seed, grid, derived,
               "eight synthetic ID trajectories with four persistent special bins; retain grid, q, start and T")


def reference_path(grid, cfg, seed):
    """An unoptimized deterministic route; no objective-dependent selection."""
    rng = np.random.default_rng(seed + 1_000_000)
    route = [cfg["start"]]
    for _ in range(cfg["budget"]):
        route.append(int(rng.choice(grid.neighbors(route[-1]))))
    return tuple(route)


def independent_window_oracle(grid, cfg, path, a, b):
    """Exhaust all legal same-endpoint routes, replaying each full candidate.

    The enumerator never calls production reachability, bounds, coefficients,
    window search, or search-state merging. It preserves original absolute
    times by splicing each candidate into the full original path.
    """
    grid.validate_path(path, start=cfg["start"], budget=cfg["budget"])
    _require(0 <= a <= b <= cfg["budget"], "invalid Oracle window")
    route = list(path[:a + 1])
    best_J = math.inf
    best_path = None
    candidates = 0

    def visit():
        nonlocal best_J, best_path, candidates
        if len(route) - 1 == b:
            if route[-1] != path[b]:
                return
            candidate = tuple(route) + path[b + 1:]
            score = score_path(grid, candidate, **cfg)
            candidates += 1
            if score.J < best_J:
                best_J, best_path = score.J, candidate
            return
        for vertex in grid.neighbors(route[-1]):
            route.append(vertex)
            visit()
            route.pop()

    visit()
    _require(candidates > 0 and best_path is not None,
             "the valid reference must be a feasible Oracle candidate")
    return {"J": best_J, "path": best_path, "candidate_count": candidates}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="a new directory or an existing empty directory")
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FileExistsError(f"refusing to overwrite nonempty output: {output}")
    output.mkdir(parents=True, exist_ok=True)
    inputs = output / "inputs"
    inputs.mkdir()
    _save(output / "protocol.json", {
        "command": [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
        "historical_seeds": HISTORICAL_SEEDS, "derived_seeds": DERIVED_SEEDS,
        "expected_case_count": 45, "expected_searches": 360,
        "historical_input_policy": "35 original small_case(seed) configurations unchanged",
        "derived_case_counts": {"stationary_first_kernel": 5, "synthetic_particle": 5},
        "windows": "[0,T] and [1,T-1] with original endpoints and full fixed suffix",
        "modes": MODES, "tolerance": ATOL, "search_limits": None,
        "data_type": "synthetic_toy", "global_epsilon_certified": False,
        "scope": "finite numerical optimality for each fixed-endpoint window only",
        "source_sha256": {str(path.relative_to(ROOT)): _sha(path) for path in (
            Path(__file__).resolve(), ROOT / "scripts/stdc_validation_guards.py",
            ROOT / "scripts/run_stdc_small_search.py", ROOT / "src/asar_repro/window_search.py",
            ROOT / "src/asar_repro/window_bounds.py", ROOT / "src/asar_repro/objective.py",
            ROOT / "src/asar_repro/motion.py",
        )},
    })
    rows = []
    completed_cases = []
    current = None
    started = perf_counter()
    try:
        with (output / "results.jsonl").open("w", encoding="utf-8", buffering=1) as stream:
            for kind, seed, grid, cfg, derivation in cases():
                label = f"{kind}_{seed}"
                current = {"kind": kind, "seed": seed}
                input_sha = freeze_case(inputs, label, grid, cfg)
                path = reference_path(grid, cfg, seed)
                initial = score_path(grid, path, **cfg)
                windows = [(0, cfg["budget"])]
                if cfg["budget"] >= 3:
                    windows.append((1, cfg["budget"] - 1))
                route_file = inputs / f"{label}_route.json"
                _save(route_file, {"seed": seed, "kind": kind,
                                   "reference_path": path, "windows": windows,
                                   "derivation": derivation, "data_type": "synthetic_toy"})
                route_sha = _sha(route_file)
                for a, b in windows:
                    current = {"kind": kind, "seed": seed, "window": [a, b]}
                    _save(output / "last_checked.json", {"stage": "oracle_start", **current})
                    oracle_started = perf_counter()
                    oracle = independent_window_oracle(grid, cfg, path, a, b)
                    oracle_wall = perf_counter() - oracle_started
                    for mode in MODES:
                        current = {"kind": kind, "seed": seed, "window": [a, b], "mode": mode}
                        _save(output / "last_checked.json", {"stage": "search_start", **current})
                        tic = perf_counter()
                        result = solve_window(grid, **cfg, path=path, a=a, b=b, mode=mode)
                        wall = perf_counter() - tic
                        _require(result.path is not None, f"missing complete incumbent: {current}")
                        candidate = tuple(result.path)
                        # Full frozen replay independently validates all route edges and t=0.
                        score = score_path(grid, candidate, **cfg)
                        raw_result = asdict(result) if is_dataclass(result) else vars(result)
                        checks = {
                            "completed": result.status == "completed",
                            "no_budget_stop_reason": result.stop_reason is None,
                            "not_globally_certified": result.theory_certified is False,
                            "full_absolute_horizon": len(candidate) == cfg["budget"] + 1,
                            "fixed_prefix_preserved": candidate[:a + 1] == path[:a + 1],
                            "fixed_endpoint_and_suffix_preserved": candidate[b:] == path[b:],
                            "J_replay": abs(score.J - result.J) <= ATOL,
                            "Pd_replay": abs(score.pd_final - result.Pd) <= ATOL,
                            "optimal_window_J": abs(score.J - oracle["J"]) <= ATOL,
                            "nonworsening_full_J": score.J <= initial.J + ATOL,
                            "initial_no_detection": score.g[0] == 0 and abs(score.survival[0] - 1) <= ATOL,
                            "mass_monotonic": float(np.max(np.diff(score.survival), initial=0)) <= ATOL,
                        }
                        row = {**current, "input_sha256": input_sha,
                               "route_input_sha256": route_sha, "data_type": "synthetic_toy",
                               "derivation": derivation, "reference_path": path,
                               "initial_J": initial.J, "initial_Pd": initial.pd_final,
                               "oracle": oracle, "oracle_wall_s": oracle_wall,
                               "result": raw_result, "search_wall_s": wall,
                               "replay_J": score.J, "replay_Pd": score.pd_final,
                               "J_minus_oracle": score.J - oracle["J"],
                               "J_replay_error": abs(score.J - result.J),
                               "Pd_replay_error": abs(score.pd_final - result.Pd),
                               "checks": checks, "status": "passed" if all(checks.values()) else "blocked"}
                        _save(output / "last_checked.json", row)
                        stream.write(json.dumps(_native(row), ensure_ascii=False, allow_nan=False) + "\n")
                        _require(all(checks.values()), f"window search gate failed: {current}; {checks}")
                        rows.append(row)
                completed_cases.append(current["kind"] + "/" + str(seed))
                if len(completed_cases) % 5 == 0:
                    print(f"validated {len(completed_cases)}/45 window cases; searches={len(rows)}", flush=True)
        _require(len(completed_cases) == 45 and len(rows) == 360, "incomplete window search audit")
        aggregate = []
        for kind in ("historical_dynamic_matrix", "derived_stationary_matrix", "derived_synthetic_particle"):
            for mode in MODES:
                group = [row for row in rows if row["kind"] == kind and row["mode"] == mode]
                aggregate.append({
                    "kind": kind, "mode": mode, "searches": len(group),
                    "mean_search_wall_s": float(np.mean([row["search_wall_s"] for row in group])),
                    "mean_expanded": float(np.mean([row["result"]["expanded"] for row in group])),
                    "max_absolute_J_minus_oracle": max(abs(row["J_minus_oracle"]) for row in group),
                    "max_J_replay_error": max(row["J_replay_error"] for row in group),
                    "max_Pd_replay_error": max(row["Pd_replay_error"] for row in group),
                })
        summary = {
            "status": "passed", "cases": len(completed_cases), "searches": len(rows),
            "case_counts": {"historical_dynamic_matrix": 35, "derived_stationary_matrix": 5,
                            "derived_synthetic_particle": 5},
            "historical_seeds": HISTORICAL_SEEDS, "derived_seeds": DERIVED_SEEDS,
            "tolerance": ATOL, "data_type": "synthetic_toy",
            "global_epsilon_certified": False,
            "scope": "all modes match an independently enumerated fixed-window optimum on these toys",
            "independent_full_path_replays": len(rows), "aggregate": aggregate,
            "total_wall_s": perf_counter() - started,
            "max_absolute_J_minus_oracle": max(abs(row["J_minus_oracle"]) for row in rows),
            "max_J_replay_error": max(row["J_replay_error"] for row in rows),
            "max_Pd_replay_error": max(row["Pd_replay_error"] for row in rows),
        }
        _save(output / "summary.json", summary)
        print(json.dumps({key: summary[key] for key in ("status", "cases", "searches",
                                                       "max_absolute_J_minus_oracle")}, allow_nan=False), flush=True)
    except Exception as exc:
        _save(output / "summary.json", {
            "status": "blocked", "completed_cases": completed_cases,
            "completed_searches": len(rows), "current": current,
            "error_type": type(exc).__name__, "error": str(exc),
            "data_type": "synthetic_toy", "global_epsilon_certified": False,
        })
        (output / "failure_traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
        print(f"blocked: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise


if __name__ == "__main__":
    main()
