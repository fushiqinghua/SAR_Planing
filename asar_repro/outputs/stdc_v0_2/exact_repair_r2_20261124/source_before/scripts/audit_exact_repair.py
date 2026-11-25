"""Independent DFS audit of the opt-in particle MILP repair solver.

Only synthetic data is used. This audit creates a fresh directory and never
overwrites an old experiment. The DFS does not call the solver's geometry,
grouping, constraint builder, branch bounds, or any search implementation.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter
import traceback

import numpy as np

from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path

ROOT = Path(__file__).resolve().parents[1]
ATOL = 1e-10
SEEDS = tuple(range(1041, 1089))


def native(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [native(v) for v in value]
    if isinstance(value, float) and not np.isfinite(value):
        return str(value)
    return value


def save(path, value):
    path.write_text(json.dumps(native(value), indent=2, ensure_ascii=False,
                               allow_nan=False), encoding="utf-8")


def restricted_vertices(grid, initial_path, prefix_depth, corridor_radius):
    """Independent spatial corridor, not a solver's time-layer helper."""
    if corridor_radius is None:
        return set(range(grid.size))
    centers = [divmod(v, grid.cols) for v in initial_path[prefix_depth:]]
    return {v for v in range(grid.size)
            if any(abs(v//grid.cols-r)+abs(v%grid.cols-c) <= corridor_radius
                   for r, c in centers)}


def independent_dfs(grid, cfg, initial_path, prefix_depth=0, corridor_radius=None):
    """Enumerate every allowed complete path; score each with frozen evaluator."""
    allowed = restricted_vertices(grid, initial_path, prefix_depth, corridor_radius)
    prefix = tuple(initial_path[:prefix_depth+1])
    best_j, best_path, complete = float("inf"), None, 0
    end_vertices = set()
    def visit(route):
        nonlocal best_j, best_path, complete
        if len(route) == cfg["budget"]+1:
            score = score_path(grid, route, **cfg)
            complete += 1
            end_vertices.add(route[-1])
            if score.J < best_j:
                best_j, best_path = score.J, route
            return
        for vertex in grid.neighbors(route[-1]):
            if vertex in allowed:
                visit(route+(vertex,))
    visit(prefix)
    if not complete:
        raise AssertionError("initial feasible route must belong to its corridor")
    return dict(J=best_j, path=best_path, complete_paths=complete,
                feasible_end_vertices=sorted(end_vertices))


def toy_case(seed):
    rng = np.random.default_rng(seed)
    grid = GridGraph(3, 3)
    horizon = 4 + (seed % 4)
    count = 2 + (seed % 7)
    cells = rng.integers(0, grid.size+4, (horizon+1, count))
    if seed % 3 == 0:
        cells[:, 0] = int(rng.integers(grid.size))
    if count >= 4:
        cells[horizon//2+1:, 1] = cells[horizon//2+1:, 0]
        cells[:, -1] = grid.size + (seed % 4)
    masses = rng.integers(1, 12, count).astype(float)
    if seed % 5 == 0:
        masses[-1] = 0.
    p = masses/masses.sum()
    kind = seed % 4
    q = (0., 1., .78, np.linspace(.1, .9, grid.size))[kind]
    ids = rng.permutation(np.arange(count)*17+13)
    motion = ParticleMotion(cells, grid.size, ids)
    start = 4
    path = [start]
    for _ in range(horizon):
        path.append(int(rng.choice(grid.neighbors(path[-1]))))
    return grid, dict(start=start, budget=horizon, p=p, q=q, motion=motion), tuple(path)


def check_completed(result, grid, cfg, initial_path, prefix_depth, corridor_radius, exact):
    if result.status != "completed":
        raise AssertionError(f"toy repair did not complete: {result.status}/{result.stop_reason}/{result.solver_message}")
    if result.theory_certified:
        raise AssertionError("restricted MILP must not claim global epsilon certification")
    grid.validate_path(result.path, start=cfg["start"], budget=cfg["budget"])
    if tuple(result.path[:prefix_depth+1]) != tuple(initial_path[:prefix_depth+1]):
        raise AssertionError("frozen prefix changed")
    allowed = restricted_vertices(grid, initial_path, prefix_depth, corridor_radius)
    if not all(v in allowed for v in result.path[prefix_depth:]):
        raise AssertionError("route outside restricted corridor")
    replay = score_path(grid, result.path, **cfg)
    if abs(replay.J-result.J) > ATOL or abs(replay.pd_final-result.Pd) > ATOL:
        raise AssertionError("returned route replay mismatch")
    error = abs(replay.J-exact["J"])
    if error > ATOL:
        raise AssertionError(f"MILP/DFS objective mismatch: {replay.J} vs {exact['J']}")
    # Different equal-J paths can have different terminal Pd. Never compare to
    # a particular DFS optimum's Pd or silently change the optimization goal.
    lower = result.restricted_lower_bound
    if lower is None or not np.isfinite(lower) or lower > exact["J"]+ATOL:
        raise AssertionError(f"invalid restricted lower bound {lower} > {exact['J']}")
    if result.J > score_path(grid, initial_path, **cfg).J+ATOL:
        raise AssertionError("repair lost its supplied feasible incumbent")
    return dict(objective_error=error, replay_error=max(abs(replay.J-result.J), abs(replay.pd_final-result.Pd)),
                bound_overestimate=max(0., lower-exact["J"]))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    tic = perf_counter()
    from asar_repro.exact_repair import solve_exact_repair
    names = ("scripts/audit_exact_repair.py", "src/asar_repro/exact_repair.py",
             "src/asar_repro/objective.py", "src/asar_repro/motion.py", "src/asar_repro/grid.py")
    fingerprints = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in names}
    save(out/"command.json", dict(command=[sys.executable, *sys.argv], cwd=str(ROOT), seeds=SEEDS,
         source_sha256=fingerprints, data_type="synthetic_toy", global_epsilon_certified=False))
    rows = []
    try:
        for seed in SEEDS:
            grid, cfg, path = toy_case(seed)
            save(out/f"input_{seed}.json", dict(seed=seed, rows=grid.rows, cols=grid.cols,
                 start=cfg["start"], budget=cfg["budget"], p=cfg["p"], q=cfg["q"],
                 cell_ids=cfg["motion"].cell_ids, trajectory_ids=cfg["motion"].trajectory_ids,
                 initial_path=path))
            settings = ((0, None), (cfg["budget"]//2, None), (cfg["budget"]//2, 0), (cfg["budget"], 1))
            for prefix, radius in settings:
                current = dict(seed=seed, prefix_depth=prefix, corridor_radius=radius)
                save(out/"last_checked.json", current)
                exact = independent_dfs(grid, cfg, path, prefix, radius)
                result = solve_exact_repair(grid, **cfg, initial_path=path,
                    prefix_depth=prefix, corridor_radius=radius, max_seconds=30.)
                row = dict(current, oracle=exact, result=asdict(result))
                save(out/"last_checked.json", row)
                errors = check_completed(result, grid, cfg, path, prefix, radius, exact)
                row.update(errors)
                rows.append(row)
                with (out/"cases.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps(native(row), ensure_ascii=False, allow_nan=False)+"\n")
            if (seed-SEEDS[0]+1) % 8 == 0:
                print(f"cases={seed-SEEDS[0]+1} repairs={len(rows)}", flush=True)
        after = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in names}
        assert after == fingerprints, "audit source changed while running"
        summary = dict(status="passed", synthetic_cases=len(SEEDS), repair_checks=len(rows),
            complete_path_evaluations=sum(r["oracle"]["complete_paths"] for r in rows),
            max_objective_error=max(r["objective_error"] for r in rows),
            max_replay_error=max(r["replay_error"] for r in rows),
            max_bound_overestimate=max(r["bound_overestimate"] for r in rows),
            violations=0, theory_certified=False, wall_s=perf_counter()-tic, source_preserved=True)
        save(out/"summary.json", summary)
        print(json.dumps(summary), flush=True)
        return 0
    except Exception:
        save(out/"summary.json", dict(status="blocked", completed_repairs=len(rows),
            error=traceback.format_exc(), wall_s=perf_counter()-tic, theory_certified=False))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
