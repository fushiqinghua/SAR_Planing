"""Independent, small-instance audit of the final STDC bound hierarchy.

Run with this package installed, or with PYTHONPATH=src.  The only stdout
output is one JSON object; --output optionally writes the same object.

The Oracle below does not import search, oracle, or research_search.  It
constructs four-neighbour adjacency itself, replays raw particle columns with
scalar arithmetic, and enumerates EVERY legal suffix without pruning.  The
package scorer is independently checked, never used to construct Oracle
states or costs.  Sampled verification is numerical evidence, not a proof.

Any quality-gap statement here uses an admissible bound at the ORIGINAL
ROOT and an independently replayed complete feasible path.  A node's bound
only concerns completions of that prefix.  In particular this script never
uses an incomplete, pruned, or timed-out OPEN list as a global certificate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter

import numpy as np

from asar_repro.grid import GridGraph
from asar_repro.heuristic import Heuristic
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path


MODES = (
    "mass_lb", "reach_lb", "capacity_lb", "stepwise_lb", "stdc_lb",
    "stdc_radius_lb",
)
SHAPES = ((1, 2), (1, 3), (2, 2), (2, 3), (3, 2), (3, 3))


def _neighbors(vertex, rows, cols):
    """Independent adjacency: no package geometry or search helper."""
    row, col = divmod(vertex, cols)
    return tuple(sorted(
        r * cols + c
        for r, c in ((row - 1, col), (row, col - 1),
                     (row, col + 1), (row + 1, col))
        if 0 <= r < rows and 0 <= c < cols
    ))


def _sense(weights, cells_at_time, vertex, q):
    """Fixed particle ID weights; special bins cannot equal a search vertex."""
    miss = 1.0 - float(q[vertex])
    return tuple(weight * miss if int(cell) == vertex else weight
                 for weight, cell in zip(weights, cells_at_time))


def _replay_prefix(path, p, q, cells):
    # Deliberately do not sense path[0].  Time is absolute, including a prefix.
    weights = tuple(float(weight) for weight in p)
    masses = []
    for time, vertex in enumerate(path[1:], 1):
        weights = _sense(weights, cells[time], vertex, q)
        masses.append(math.fsum(weights))
    return weights, math.fsum(masses)


def _enumerate_suffix(rows, cols, vertex, depth, horizon, weights, q, cells):
    """Exhaustive scalar DFS: return exact sampled optimum and its witness."""
    leaves = 0
    nodes = 0

    def visit(current, time, mass):
        nonlocal leaves, nodes
        nodes += 1
        if time == horizon:
            leaves += 1
            return 0.0, (current,)
        best_cost, best_path = math.inf, None
        for successor in _neighbors(current, rows, cols):
            next_mass = _sense(mass, cells[time + 1], successor, q)
            future_cost, future_path = visit(successor, time + 1, next_mass)
            cost = math.fsum((math.fsum(next_mass), future_cost))
            if cost < best_cost:
                best_cost = cost
                best_path = (current,) + future_path
        return best_cost, best_path

    optimum, path = visit(vertex, depth, weights)
    return optimum, path, leaves, nodes


def _make_case(seed, index):
    rng = np.random.default_rng(np.random.SeedSequence([seed, index, 0]))
    rows, cols = SHAPES[index % len(SHAPES)]
    size = rows * cols
    # A two-vertex no-wait graph has just one path at each depth.  T=7
    # therefore permits eight distinct prefixes even in that edge case.
    horizon = 7 if size == 2 else 4 + index % 3
    start = int(rng.integers(size))
    particle_count = 8 + index % 5
    cells = rng.integers(0, size + 4, size=(horizon + 1, particle_count))
    cells[:, -4:] = size + np.arange(4)  # each special bin retains mass
    cells[0, 0] = start  # positive mass at the start must not be sensed at t=0
    if index % 18 == 17:
        cells[:] = size + np.arange(particle_count) % 4  # all-special case
    p = rng.dirichlet(np.full(particle_count, 0.9))
    if index % 7 == 0:
        p[1] = 0.0
        p /= p.sum()
    regime = (index + index // 6) % 6
    q = rng.uniform(0.05, 0.95, size)
    if regime == 0:
        q[:] = 0.0
    elif regime == 1:
        q[:] = 1.0
    elif regime == 2:
        q[:] = 0.78
    elif regime == 3:
        q[0], q[-1] = 0.0, 1.0
    elif regime == 4:
        q[0] = 0.0
    ids = rng.permutation(particle_count) + 100 * index
    return rows, cols, horizon, start, p, q, cells, ids


def _sample_prefixes(rows, cols, start, horizon, count, seed, index):
    # Enumeration is tiny (T <= 7), and avoids over-counting repeated samples.
    pending = [(start,)]
    universe = []
    while pending:
        path = pending.pop()
        universe.append(path)
        if len(path) <= horizon:
            pending.extend(path + (v,) for v in
                           reversed(_neighbors(path[-1], rows, cols)))
    root = (start,)
    full = next(path for path in universe if len(path) == horizon + 1)
    chosen = [root, full]
    rng = np.random.default_rng(np.random.SeedSequence([seed, index, 1]))
    # Sampling uniformly from the whole tree would mostly select trivial
    # terminal h=0 states.  First cover every interior depth, then draw more
    # distinct interior prefixes.  Terminal samples only fill any excess.
    for depth in range(1, horizon):
        if len(chosen) == count:
            break
        at_depth = [path for path in universe if len(path) == depth + 1]
        chosen.append(at_depth[int(rng.integers(len(at_depth)))])
    for terminal in (False, True):
        pool = [path for path in universe if path not in chosen
                and (len(path) == horizon + 1) == terminal]
        take = min(max(count - len(chosen), 0), len(pool))
        chosen.extend(pool[int(i)] for i in rng.choice(len(pool), take, replace=False))
    return chosen, len(universe)


def _observe(table, name, lhs, rhs, context, failures, tolerance):
    """Observe lhs >= rhs, retaining raw floating-point violations."""
    record = table.setdefault(name, dict(
        checks=0, maximum_positive_violation=0.0, strict_dominance_count=0,
        equality_within_tolerance_count=0, maximum_margin=0.0,
        first_strict_witness=None,
    ))
    record["checks"] += 1
    margin = float(lhs - rhs)
    record["maximum_positive_violation"] = max(
        record["maximum_positive_violation"], -margin, 0.0)
    record["maximum_margin"] = max(record["maximum_margin"], margin)
    if margin > tolerance:
        record["strict_dominance_count"] += 1
        if record["first_strict_witness"] is None:
            record["first_strict_witness"] = dict(context, lhs=lhs, rhs=rhs)
    elif abs(margin) <= tolerance:
        record["equality_within_tolerance_count"] += 1
    if not math.isfinite(margin) or margin < -tolerance:
        failures.append(dict(context, check=name, lhs=lhs, rhs=rhs))


def run_audit(*, seed=20261125, models=36, prefixes_per_model=8, tolerance=1e-10):
    if seed < 0 or models < 1 or prefixes_per_model < 2:
        raise ValueError("seed must be nonnegative; models >= 1; prefixes >= 2")
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be positive and finite")
    started = perf_counter()
    admissibility, nonnegativity, dominance, gap_checks = {}, {}, {}, {}
    failures, roots, cases = [], [], []
    fractions = {mode: [] for mode in MODES}
    sample_count = leaf_count = node_count = 0
    max_score_error = max_belief_error = max_mass_formula_error = 0.0
    coverage = dict(root_prefixes=0, terminal_prefixes=0, interior_prefixes=0,
                    reduced_unnormalized_mass_prefixes=0, q_zero_models=0,
                    q_one_models=0, q_point78_models=0, nonuniform_q_models=0,
                    dynamic_models=0, all_special_models=0,
                    start_has_positive_mass_at_t0_models=0,
                    all_four_special_bins_with_positive_mass_models=0)
    for index in range(models):
        rows, cols, horizon, start, p, q, cells, ids = _make_case(seed, index)
        grid = GridGraph(rows, cols)
        motion = ParticleMotion(cells, grid.size, ids)
        estimators = {mode: Heuristic(grid, budget=horizon, q=q,
                                     motion=motion, mode=mode) for mode in MODES}
        prefixes, universe_size = _sample_prefixes(
            rows, cols, start, horizon, prefixes_per_model, seed, index)
        coverage["q_zero_models"] += int(np.all(q == 0.0))
        coverage["q_one_models"] += int(np.all(q == 1.0))
        coverage["q_point78_models"] += int(np.all(q == 0.78))
        coverage["nonuniform_q_models"] += int(np.ptp(q) > 0.0)
        coverage["dynamic_models"] += int(np.any(cells[1:] != cells[:-1]))
        coverage["all_special_models"] += int(np.all(cells >= grid.size))
        coverage["start_has_positive_mass_at_t0_models"] += int(
            float(p[cells[0] == start].sum()) > 0.0)
        coverage["all_four_special_bins_with_positive_mass_models"] += int(
            all(float(p[cells[0] == grid.size + s].sum()) > 0.0 for s in range(4)))
        model_payload = dict(grid=[rows, cols], T=horizon, start=start,
                             p=p.tolist(), q=q.tolist(), cells=cells.tolist(),
                             particle_ids=ids.tolist())
        digest = hashlib.sha256(json.dumps(model_payload, sort_keys=True,
                                           separators=(",", ":")).encode()).hexdigest()
        cases.append(dict(case_index=index, sha256=digest, grid=[rows, cols],
                          T=horizon, particle_count=len(p),
                          available_distinct_prefixes=universe_size,
                          sampled_prefixes=[list(path) for path in prefixes]))
        for path in prefixes:
            depth = len(path) - 1
            weights, prefix_cost = _replay_prefix(path, p, q, cells)
            context = dict(case_index=index, prefix=list(path), depth=depth)
            exact, witness, leaves, nodes = _enumerate_suffix(
                rows, cols, path[-1], depth, horizon, weights, q, cells)
            leaf_count += leaves
            node_count += nodes
            sample_count += 1
            coverage["root_prefixes"] += int(depth == 0)
            coverage["terminal_prefixes"] += int(depth == horizon)
            coverage["interior_prefixes"] += int(0 < depth < horizon)
            coverage["reduced_unnormalized_mass_prefixes"] += int(
                math.fsum(weights) < 1.0 - tolerance)

            # This is a cross-check of the package scorer, not an Oracle input.
            replayed = score_path(grid, path, start=start, budget=depth,
                                  p=p, q=q, motion=motion)
            score_error = abs(replayed.J - prefix_cost)
            belief_error = float(np.max(np.abs(replayed.final_belief - weights)))
            max_score_error = max(max_score_error, score_error)
            max_belief_error = max(max_belief_error, belief_error)
            if max(score_error, belief_error) > tolerance:
                failures.append(dict(context, check="independent_prefix_replay",
                                     J_error=score_error, belief_error=belief_error))
            values = {mode: float(h(path[-1], depth, weights))
                      for mode, h in estimators.items()}
            mass_formula = math.fsum(weights) * math.fsum(
                (1.0 - float(q.max())) ** k for k in range(1, horizon - depth + 1))
            formula_error = abs(values["mass_lb"] - mass_formula)
            max_mass_formula_error = max(max_mass_formula_error, formula_error)
            if formula_error > tolerance:
                failures.append(dict(context, check="independent_mass_formula",
                                     error=formula_error))
            for mode, value in values.items():
                _observe(admissibility, mode, exact, value, context, failures, tolerance)
                _observe(nonnegativity, mode, value, 0.0, context, failures, tolerance)
            combined = max(values["reach_lb"], values["capacity_lb"])
            comparisons = {
                "stdc_ge_stepwise": (values["stdc_lb"], values["stepwise_lb"]),
                "stepwise_ge_max_reach_capacity": (values["stepwise_lb"], combined),
                "stepwise_ge_reach": (values["stepwise_lb"], values["reach_lb"]),
                "stepwise_ge_capacity": (values["stepwise_lb"], values["capacity_lb"]),
                "max_reach_capacity_ge_mass": (combined, values["mass_lb"]),
                "reach_ge_mass": (values["reach_lb"], values["mass_lb"]),
                "capacity_ge_mass": (values["capacity_lb"], values["mass_lb"]),
                "stdc_exact_ge_radius": (values["stdc_lb"], values["stdc_radius_lb"]),
            }
            for name, (lhs, rhs) in comparisons.items():
                _observe(dominance, name, lhs, rhs, context, failures, tolerance)
            if depth == 0:
                feasible = prefixes[1]  # a complete independently legal path
                _, upper = _replay_prefix(feasible, p, q, cells)
                lower = values["stdc_lb"]
                _observe(gap_checks, "feasible_U_ge_exact_optimum", upper, exact,
                         context, failures, tolerance)
                _observe(gap_checks, "exact_optimum_ge_root_L0", exact, lower,
                         context, failures, tolerance)
                roots.append(dict(
                    case_index=index, lower_bounds=values, exact_optimum=exact,
                    exact_optimal_path=list(witness), feasible_path=list(feasible),
                    feasible_U=upper, root_L0=lower,
                    additive_suboptimality_upper_bound=upper - lower,
                    relative_suboptimality_upper_bound=(upper / lower - 1.0
                                                        if lower > 0.0 else None),
                    actual_additive_suboptimality=upper - exact,
                ))
                if exact > tolerance:
                    for mode in MODES:
                        fractions[mode].append(values[mode] / exact)
    all_checks = (admissibility, nonnegativity, dominance, gap_checks)
    maximum_violation = max(record["maximum_positive_violation"]
                            for table in all_checks for record in table.values())
    return dict(
        schema="stdc_final_independent_theory_audit_v1",
        status="passed" if not failures else "failed",
        seed=seed, model_count=models, requested_prefixes_per_model=prefixes_per_model,
        prefix_evaluations=sample_count, unique_prefix_evaluations=sample_count,
        tolerance=tolerance, maximum_positive_inequality_violation=maximum_violation,
        violation_count=len(failures), first_violations=failures[:20],
        coverage=coverage, admissibility=admissibility, nonnegativity=nonnegativity,
        dominance=dominance, root_gap_checks=gap_checks,
        independent_prefix_replay=dict(
            maximum_J_error=max_score_error, maximum_particle_weight_error=max_belief_error,
            t0_sensing=False, absolute_time=True, prefix_renormalization=False),
        independent_mass_formula_maximum_error=max_mass_formula_error,
        oracle=dict(method="independent exhaustive scalar DFS, without pruning",
                    uses_package_search=False, uses_package_oracle=False,
                    uses_package_geometry=False, uses_package_score_for_oracle=False,
                    enumerated_suffix_leaves=leaf_count, visited_nodes=node_count),
        root_bound_fraction_of_exact_optimum={
            mode: dict(count=len(ratios), mean=float(np.mean(ratios)) if ratios else None,
                       median=float(np.median(ratios)) if ratios else None,
                       minimum=min(ratios) if ratios else None,
                       maximum=max(ratios) if ratios else None)
            for mode, ratios in fractions.items()},
        quality_gap_scope=dict(
            basis="admissible original-root L0 and independently replayed complete feasible U",
            additive_formula="U - L0", relative_formula="U / L0 - 1, only if L0 > 0",
            raw_floating_point_values_retained=True, comparison_tolerance=tolerance,
            prefix_bounds_are_global_certificates=False,
            incomplete_or_timeout_OPEN_used=False, search_epsilon_certificate_claimed=False,
            sampled_audit_is_a_general_mathematical_proof=False),
        roots=roots, cases=cases, total_wall_s=perf_counter() - started,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20261125)
    parser.add_argument("--models", type=int, default=36)
    parser.add_argument("--prefixes-per-model", type=int, default=8)
    parser.add_argument("--tolerance", type=float, default=1e-10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_audit(seed=args.seed, models=args.models,
                       prefixes_per_model=args.prefixes_per_model,
                       tolerance=args.tolerance)
    serialized = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
