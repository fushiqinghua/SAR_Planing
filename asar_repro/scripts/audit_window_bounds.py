"""Independent exhaustive fixed-window audit on reproducible synthetic toys.

The Oracle enumerates complete legal paths with the original prefix, endpoint,
absolute window times, and suffix. Every candidate is replayed by the frozen
``score_path`` evaluator. Neither bounds, suffix coefficients, nor reachability
helpers determine the Oracle's routes or costs.

This is a finite numerical audit of a fixed-window problem. It is not a proof
of a global epsilon guarantee or an evaluation on real forcing/particles.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sys
import traceback

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import PathScore, score_path
from asar_repro.window_bounds import WindowHeuristic, suffix_coefficients


MODES = ("zero", "mass_lb", "stdc_lb", "stdc_endpoint_lb")
TOLERANCE = 1e-10
SEEDS = tuple(range(100, 180))


@dataclass(frozen=True)
class ToyCase:
    kind: str
    seed: int
    grid: GridGraph
    reference_path: tuple[int, ...]
    window_start: int
    window_end: int
    p: np.ndarray
    q: float | np.ndarray
    motion: MatrixMotion | ParticleMotion
    motion_label: str

    @property
    def horizon(self):
        return len(self.reference_path) - 1


@dataclass
class WindowOracle:
    candidates: dict[tuple[int, ...], PathScore]
    best_full_J_by_prefix: dict[tuple[int, ...], float]
    best_full_path_by_prefix: dict[tuple[int, ...], tuple[int, ...]]


def _validate_case(case):
    case.grid.validate_path(case.reference_path, start=case.reference_path[0],
                            budget=case.horizon)
    if not 0 <= case.window_start <= case.window_end <= case.horizon:
        raise ValueError("window must satisfy 0 <= a <= b <= T")


def replay(case, path, *, record_beliefs=True):
    """Use the original initial state and absolute times for every replay."""
    return score_path(case.grid, path, start=case.reference_path[0],
                      budget=len(path) - 1, p=case.p, q=case.q,
                      motion=case.motion, record_beliefs=record_beliefs)


def legal_window_prefixes(case):
    """All legal prefixes, including ones unable to reach the fixed endpoint."""
    _validate_case(case)
    route = list(case.reference_path[:case.window_start + 1])

    def visit():
        yield tuple(route)
        if len(route) - 1 == case.window_end:
            return
        for vertex in case.grid.neighbors(route[-1]):
            route.append(vertex)
            yield from visit()
            route.pop()

    yield from visit()


def enumerate_window_oracle(case):
    """Independent DFS of every same-time, same-endpoint replacement.

    No state merging occurs: different route histories remain different keys,
    even when their (depth, vertex), total mass, or cost happen to coincide.
    No bound, backward coefficient, or production reachability helper is used.
    """
    _validate_case(case)
    candidates = {}
    best_costs = {}
    best_paths = {}
    route = list(case.reference_path[:case.window_start + 1])
    endpoint = case.reference_path[case.window_end]

    def visit():
        if len(route) - 1 == case.window_end:
            if route[-1] != endpoint:
                return
            full_path = tuple(route) + case.reference_path[case.window_end + 1:]
            score = replay(case, full_path)
            candidates[full_path] = score
            for depth in range(case.window_start, case.window_end + 1):
                prefix = full_path[:depth + 1]
                if score.J < best_costs.get(prefix, math.inf):
                    best_costs[prefix] = score.J
                    best_paths[prefix] = full_path
            return
        for vertex in case.grid.neighbors(route[-1]):
            route.append(vertex)
            visit()
            route.pop()

    visit()
    return WindowOracle(candidates, best_costs, best_paths)


def make_random_case(kind, seed):
    """Seed is sufficient to rebuild every input; no external data are used."""
    if kind not in ("matrix", "particle"):
        raise ValueError("kind must be matrix or particle")
    rng = np.random.default_rng(seed)
    rows, cols = ((2, 2), (2, 3), (3, 3))[seed % 3]
    grid = GridGraph(rows, cols)
    horizon = 4 + seed % 2
    route = [int(rng.integers(grid.size))]
    for _ in range(horizon):
        route.append(int(rng.choice(grid.neighbors(route[-1]))))
    a = seed % 2
    b = horizon - int(seed % 4 < 2)
    sensor_kind = seed % 4
    if sensor_kind == 0:
        q = 0.0
    elif sensor_kind == 1:
        q = 1.0
    elif sensor_kind == 2:
        q = rng.uniform(0.05, 0.95, grid.size)
        q[0], q[-1] = 0.0, 1.0
    else:
        q = 0.78
    if kind == "matrix":
        if seed % 4 == 0:
            motion = MatrixMotion.identity(grid.size)
            label = "static_identity"
        elif seed % 4 == 1:
            matrix = rng.dirichlet(np.ones(grid.size), grid.size)
            motion = MatrixMotion.stationary(matrix)
            label = "stationary_asymmetric"
        else:
            matrices = [rng.dirichlet(np.ones(grid.size), grid.size)
                        for _ in range(horizon)]
            motion = MatrixMotion.time_varying(matrices)
            label = "time_varying_asymmetric"
        p = rng.dirichlet(np.ones(grid.size))
    else:
        count = grid.size + 6
        cells = rng.integers(0, grid.size + 4, size=(horizon + 1, count))
        # Four persistent special-bin trajectories cannot be sensed by a route.
        cells[:, -4:] = grid.size + np.arange(4)
        ids = rng.permutation(count) * 17 + seed * 1000
        motion = ParticleMotion(cells, grid.size, ids)
        label = "synthetic_id_preserving_with_four_special_bins"
        p = rng.dirichlet(np.ones(count))
    return ToyCase(kind, seed, grid, tuple(route), a, b, p, q, motion, label)


def case_payload(case):
    payload = {
        "kind": case.kind, "seed": case.seed, "data_type": "synthetic_toy",
        "motion_label": case.motion_label,
        "grid": {"rows": case.grid.rows, "cols": case.grid.cols},
        "reference_path": list(case.reference_path),
        "window": [case.window_start, case.window_end],
        "p": case.p.tolist(), "q": np.asarray(case.q).tolist(),
        "t0_convention": "frame zero has no observation; first motion/sense is t=1",
    }
    if isinstance(case.motion, MatrixMotion):
        payload["motion"] = {
            "repeat": case.motion._repeat,
            "matrices": [matrix.toarray().tolist() for matrix in case.motion._matrices],
        }
    else:
        payload["motion"] = {
            "cell_ids": case.motion.cell_ids.tolist(),
            "trajectory_ids": case.motion.trajectory_ids.tolist(),
            "special_bins": case.motion.bin_count - case.motion.size,
        }
    return payload


def audit_case(case, *, record=None):
    """Check every legal internal prefix against the complete replay Oracle.

    ``record`` receives the numerical evidence before any assertions, so the
    last-check file identifies the failing prefix if a gate fails.
    """
    oracle = enumerate_window_oracle(case)
    if not oracle.candidates:
        raise AssertionError("valid reference path must provide a window completion")
    coefficients = suffix_coefficients(case.grid, case.reference_path,
                                       q=case.q, motion=case.motion)
    tail = coefficients.cost[case.window_end]
    heuristics = {
        mode: WindowHeuristic(case.grid,
                              end_vertex=case.reference_path[case.window_end],
                              end_depth=case.window_end, q=case.q,
                              motion=case.motion, tail_cost=tail, mode=mode)
        for mode in MODES
    }
    max_cost_error = 0.0
    max_survival_error = 0.0
    # Only the fixed suffix (d >= b) is common to different window candidates.
    # For the reference, every depth can additionally be checked.
    suffix_checks = 0
    for path, score in oracle.candidates.items():
        depths = (range(case.horizon + 1) if path == case.reference_path
                  else range(case.window_end, case.horizon + 1))
        for depth in depths:
            J_from_suffix = float(score.g[depth] + coefficients.cost[depth] @ score.beliefs[depth])
            mass_from_suffix = float(coefficients.survival[depth] @ score.beliefs[depth])
            cost_error = abs(J_from_suffix - score.J)
            survival_error = abs(mass_from_suffix - score.survival[-1])
            evidence = {
                "check": "suffix_linearity", "kind": case.kind, "seed": case.seed,
                "path": list(path), "depth": depth,
                "J_replay": score.J, "J_from_suffix": J_from_suffix,
                "final_mass_replay": float(score.survival[-1]),
                "final_mass_from_suffix": mass_from_suffix,
                "cost_error": cost_error, "survival_error": survival_error,
            }
            if record:
                record(evidence)
            assert cost_error <= TOLERANCE, evidence
            assert survival_error <= TOLERANCE, evidence
            max_cost_error = max(max_cost_error, cost_error)
            max_survival_error = max(max_survival_error, survival_error)
            suffix_checks += 1

    feasible = 0
    infeasible = 0
    max_overestimate = {mode: 0.0 for mode in MODES}
    minimum_endpoint_margin = math.inf
    for prefix in legal_window_prefixes(case):
        depth = len(prefix) - 1
        prefix_score = replay(case, prefix)
        best_full_J = oracle.best_full_J_by_prefix.get(prefix, math.inf)
        remaining = best_full_J - prefix_score.J
        values = {mode: float(heuristic(prefix[-1], depth, prefix_score.final_belief))
                  for mode, heuristic in heuristics.items()}
        possible = math.isfinite(remaining)
        evidence = {
            "check": "prefix_admissibility", "kind": case.kind, "seed": case.seed,
            "window": [case.window_start, case.window_end],
            "prefix": list(prefix), "depth": depth, "feasible": possible,
            "prefix_J": prefix_score.J,
            "oracle_remaining": remaining if possible else None,
            "oracle_best_full_path": list(oracle.best_full_path_by_prefix[prefix]) if possible else None,
            "h": {mode: value if math.isfinite(value) else None
                  for mode, value in values.items()},
            "h_is_positive_infinity": {mode: value == math.inf for mode, value in values.items()},
        }
        if record:
            record(evidence)
        if not possible:
            assert all(value == math.inf for value in values.values()), evidence
            infeasible += 1
            continue
        feasible += 1
        for mode, value in values.items():
            assert math.isfinite(value), evidence
            assert value >= -TOLERANCE, evidence
            assert value <= remaining + TOLERANCE, evidence
            if depth == case.window_end:
                assert abs(value - remaining) <= TOLERANCE, evidence
            max_overestimate[mode] = max(max_overestimate[mode], value - remaining)
        margin = values["stdc_endpoint_lb"] - values["stdc_lb"]
        assert margin >= -TOLERANCE, evidence
        minimum_endpoint_margin = min(minimum_endpoint_margin, margin)

    return {
        "kind": case.kind, "seed": case.seed, "motion_label": case.motion_label,
        "candidate_paths": len(oracle.candidates), "feasible_prefixes": feasible,
        "infeasible_prefixes": infeasible, "suffix_linearity_checks": suffix_checks,
        "max_admissibility_overestimate": max_overestimate,
        "minimum_endpoint_minus_plain": minimum_endpoint_margin,
        "max_suffix_cost_error": max_cost_error,
        "max_suffix_survival_error": max_survival_error,
        "status": "passed",
    }


def _save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def _fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="new directory, or an existing empty directory")
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FileExistsError(f"refusing to overwrite nonempty audit output: {output}")
    output.mkdir(parents=True, exist_ok=True)
    inputs = output / "inputs"
    inputs.mkdir()
    _save(output / "protocol.json", {
        "command": [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]],
        "seeds_per_kind": list(SEEDS), "kinds": ["matrix", "particle"],
        "expected_cases": 160, "tolerance": TOLERANCE,
        "data_type": "synthetic_toy", "oracle": "independent DFS plus full frozen score_path replay",
        "scope": "fixed absolute-time window, endpoint, prefix and suffix",
        "global_epsilon_certified": False,
        "source_sha256": {str(path.relative_to(ROOT)): _fingerprint(path) for path in (
            Path(__file__).resolve(), ROOT / "src/asar_repro/window_bounds.py",
            ROOT / "src/asar_repro/objective.py", ROOT / "src/asar_repro/motion.py",
        )},
    })
    results = []
    current = None
    record_count = 0
    try:
        with (output / "checks.jsonl").open("w", encoding="utf-8") as stream:
            def record(evidence):
                nonlocal record_count
                record_count += 1
                evidence = {"record_index": record_count, **evidence}
                stream.write(json.dumps(evidence, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                _save(output / "last_checked.json", evidence)

            for kind in ("matrix", "particle"):
                for seed in SEEDS:
                    current = {"kind": kind, "seed": seed}
                    case = make_random_case(kind, seed)
                    _save(inputs / f"{kind}_{seed}.json", case_payload(case))
                    _save(output / "last_checked.json", {"check": "case_start", **current})
                    results.append(audit_case(case, record=record))
                    if len(results) % 20 == 0:
                        print(f"validated {len(results)}/160 synthetic window cases", flush=True)
        summary = {
            "status": "passed", "case_count": len(results), "expected_cases": 160,
            "seeds_per_kind": list(SEEDS), "tolerance": TOLERANCE,
            "data_type": "synthetic_toy", "global_epsilon_certified": False,
            "scope": "numerical admissibility and suffix replay for the fixed-window model only",
            "check_records": record_count,
            "candidate_paths": sum(row["candidate_paths"] for row in results),
            "feasible_prefixes": sum(row["feasible_prefixes"] for row in results),
            "infeasible_prefixes": sum(row["infeasible_prefixes"] for row in results),
            "max_admissibility_overestimate": {
                mode: max(row["max_admissibility_overestimate"][mode] for row in results)
                for mode in MODES},
            "max_suffix_cost_error": max(row["max_suffix_cost_error"] for row in results),
            "max_suffix_survival_error": max(row["max_suffix_survival_error"] for row in results),
            "minimum_endpoint_minus_plain": min(row["minimum_endpoint_minus_plain"] for row in results),
            "cases": results,
        }
        assert len(results) == 160, "incomplete audit"
        _save(output / "summary.json", summary)
        print(json.dumps({key: summary[key] for key in ("status", "case_count", "feasible_prefixes",
                                                       "infeasible_prefixes", "max_suffix_cost_error")},
                         ensure_ascii=False, allow_nan=False), flush=True)
    except Exception as exc:
        _save(output / "summary.json", {
            "status": "blocked", "completed_cases": len(results), "current_case": current,
            "error_type": type(exc).__name__, "error": str(exc),
            "global_epsilon_certified": False, "cases": results,
        })
        (output / "failure_traceback.txt").write_text(traceback.format_exc(), encoding="utf-8")
        print(f"blocked: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise


if __name__ == "__main__":
    main()
