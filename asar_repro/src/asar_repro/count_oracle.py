"""Full-horizon particle-count MILP for small diagnostic instances.

The formulation is exact on integer routes; solver bounds are floating-point
numerical evidence, not formal certificates.  This module never runs at import.
Use the original ``score_path`` for every decoded feasible route.
"""

from __future__ import annotations

import math
import os
import time
import warnings

import numpy as np

from .belief import initial_belief
from .grid import GridGraph, integer
from .motion import ParticleMotion
from .objective import score_path


DEFAULT_OPTIONS = {
    "max_particles": 64,
    "max_horizon": 24,
    "max_cells": 100,
    "max_variables": 50000,
    "max_constraints": 100000,
    "max_nonzeros": 1000000,
    "presolve": False,
    "mip_rel_gap": 0.0,
    "node_limit": 100000,
    "replay_atol": 1e-8,
    "integrality_atol": 1e-6,
    "audit_reserve_seconds": None,
    "threads": 1,
}


class _BuildDeadline(Exception):
    pass


def _finite_number(value):
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _canonical_path(grid, start, budget):
    path = [int(start)]
    for _ in range(budget):
        neighbors = grid.neighbors(path[-1])
        if not neighbors:
            raise ValueError("there is no no-wait route for this horizon")
        path.append(int(neighbors[0]))
    return path


def solve_count_oracle(grid, *, start, budget, p, q, motion,
                       initial_path=None, max_seconds=30.0, options=None):
    """Solve the full legal route domain with a count/secant formulation.

    Only fixed-ID ParticleMotion and scalar 0 < q < 1 are supported.  All
    integer secants are present (no adaptive cut generation in this first
    implementation).  Resource limits intentionally block the real 500-particle
    cases unless a future protocol explicitly changes them.

    ``lower_bound`` is exposed only after budget-compliant numerical validation.
    ``solver_lower_bound_raw`` is diagnostic and must not be used as an on-time
    or formally certified bound.  A timeout never means optimality.
    """
    started = time.perf_counter()
    budget = integer(budget, "budget")
    start = integer(start, "start")
    grid.coordinates(start)
    if not isinstance(motion, ParticleMotion) or motion.size != grid.size:
        raise ValueError("count oracle requires matching fixed-ID ParticleMotion")
    motion.check_horizon(budget)
    weights = initial_belief(p, motion.state_size)
    q_array = np.asarray(q)
    if q_array.ndim != 0:
        raise ValueError("count oracle supports a scalar q only")
    q_value = float(q_array)
    if not math.isfinite(q_value) or not 0.0 < q_value < 1.0:
        raise ValueError("count oracle requires 0 < q < 1; q=0/1 are unsupported")
    max_seconds = float(max_seconds)
    if not math.isfinite(max_seconds) or max_seconds <= 0:
        raise ValueError("max_seconds must be finite and positive")
    deadline = started + max_seconds
    opts = dict(DEFAULT_OPTIONS)
    if options:
        unknown = set(options) - set(opts)
        if unknown:
            raise ValueError(f"unknown count-oracle options: {sorted(unknown)}")
        opts.update(options)
    for key in ("max_particles", "max_horizon", "max_cells", "max_variables",
                "max_constraints", "max_nonzeros", "node_limit", "threads"):
        opts[key] = integer(opts[key], key, 1)
    if opts["threads"] != 1:
        raise ValueError("this protocol requires threads=1")
    if not isinstance(opts["presolve"], bool):
        raise ValueError("presolve must be a bool")
    for key in ("mip_rel_gap", "replay_atol", "integrality_atol"):
        opts[key] = float(opts[key])
        if not math.isfinite(opts[key]) or opts[key] < 0:
            raise ValueError(f"{key} must be finite and nonnegative")
    reserve = opts["audit_reserve_seconds"]
    if reserve is None:
        reserve = min(max_seconds * 0.25, 1.0,
                      max(0.01, max_seconds * 0.02))
    reserve = float(reserve)
    if not math.isfinite(reserve) or reserve < 0 or reserve >= max_seconds:
        raise ValueError("audit reserve must be nonnegative and below max_seconds")
    opts["audit_reserve_seconds"] = reserve
    path = (_canonical_path(grid, start, budget) if initial_path is None
            else list(initial_path))
    incumbent = score_path(grid, path, start=start, budget=budget,
                           p=weights, q=q_value, motion=motion)
    initial_completed_s = time.perf_counter() - started
    result = {
        "method": "count_secant_full_flow", "status": "not_started",
        "path": [int(v) for v in path], "J": incumbent.J,
        "pd_final": incumbent.pd_final, "survival": incumbent.survival.tolist(),
        "initial_J": incumbent.J, "initial_completed_s": initial_completed_s,
        "history": [{"elapsed_s": initial_completed_s, "J": incumbent.J,
                     "pd_final": incumbent.pd_final, "source": "initial",
                     "path": [int(v) for v in path],
                     "completed_within_budget": initial_completed_s <= max_seconds}],
        "lower_bound": None, "solver_lower_bound_raw": None,
        "lower_bound_elapsed_s": None,
        "global_numeric_gap": None, "global_numeric_gap_absolute": None,
        "optimality_scope": "full_fixed_particle_discrete_instance",
        "formulation_integer_equivalent": True,
        "formal_certificate": False, "numerical_optimality_checked": False,
        "solver_status": None, "solver_message": None, "solver_gap_raw": None,
        "solver_objective_raw": None, "solver_node_count": None,
        "candidate": None, "warnings": [], "fatal": False,
        "model_build_s": 0.0, "solver_s": 0.0, "validation_s": 0.0,
        "elapsed_s": initial_completed_s, "max_seconds": max_seconds,
        "options": opts, "threads_requested": 1,
        "native_thread_readback_verified": False,
        "thread_environment": {key: os.environ.get(key) for key in
                               ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")},
        "versions": {"numpy": np.__version__},
        "counts": {"particles": int(len(weights)), "horizon": budget,
                   "grid_cells": grid.size},
    }

    def finish(status, reason=None):
        result["status"] = status
        result["stop_reason"] = reason or status
        result["elapsed_s"] = time.perf_counter() - started
        result["budget_exceeded"] = result["elapsed_s"] > max_seconds
        return result

    if initial_completed_s > max_seconds:
        return finish("budget_exceeded", "initial_validation_exceeded_budget")
    if budget == 0:
        result.update(lower_bound=0.0, global_numeric_gap=0.0,
                      global_numeric_gap_absolute=0.0,
                      lower_bound_elapsed_s=time.perf_counter() - started,
                      numerical_optimality_checked=True)
        return finish("trivial_optimal", "zero_horizon")
    limits = ((len(weights), opts["max_particles"], "particles"),
              (budget, opts["max_horizon"], "horizon"),
              (grid.size, opts["max_cells"], "grid_cells"))
    for actual, cap, name in limits:
        if actual > cap:
            return finish("blocked_resource_limit", f"{name}={actual} exceeds {cap}")

    try:
        import scipy
        from scipy.optimize import Bounds, LinearConstraint, milp
        from scipy.sparse import coo_matrix
    except ImportError as exc:
        result["warnings"].append(str(exc))
        return finish("blocked_dependency", "scipy_milp_unavailable")
    result["versions"]["scipy"] = scipy.__version__
    build_started = time.perf_counter()
    arcs = []
    incoming = {}
    outgoing = {}
    layers = [{start}]

    def check_build_time():
        if time.perf_counter() >= deadline - reserve:
            raise _BuildDeadline

    try:
        for t in range(1, budget + 1):
            check_build_time()
            layer = set()
            for u in sorted(layers[-1]):
                for v in grid.neighbors(u):
                    index = len(arcs)
                    arcs.append((t, u, v))
                    incoming.setdefault((t, v), []).append(index)
                    outgoing.setdefault((t - 1, u), []).append(index)
                    layer.add(v)
            layers.append(layer)
        arc_count = len(arcs)
        particle_count = len(weights)
        count_offset = arc_count
        survival_offset = arc_count + particle_count * budget
        variable_count = arc_count + 2 * particle_count * budget
        flow_rows = 1 + sum(len(layer) for layer in layers[1:-1])
        count_rows = particle_count * budget
        secant_rows = particle_count * budget * (budget + 1) // 2
        constraint_count = flow_rows + count_rows + secant_rows
        # Source/internal flow each uses at most 2*arcs entries; count rows
        # use at most two recurrence terms plus all arcs for each particle.
        estimated_nnz = (2 * arc_count + 2 * count_rows
                         + particle_count * arc_count + 2 * secant_rows)
        result["counts"].update(arcs=arc_count, variables=variable_count,
                                flow_rows=flow_rows, count_rows=count_rows,
                                secant_rows=secant_rows,
                                constraints=constraint_count,
                                estimated_nonzeros=estimated_nnz)
        for actual, cap, name in ((variable_count, opts["max_variables"], "variables"),
                                  (constraint_count, opts["max_constraints"], "constraints"),
                                  (estimated_nnz, opts["max_nonzeros"], "nonzeros_estimate")):
            if actual > cap:
                result["model_build_s"] = time.perf_counter() - build_started
                return finish("blocked_resource_limit", f"{name}={actual} exceeds {cap}")

        def count_index(t, i):
            return count_offset + (t - 1) * particle_count + i

        def survival_index(t, i):
            return survival_offset + (t - 1) * particle_count + i

        row_ids, col_ids, coefficients, row_lower, row_upper = [], [], [], [], []

        def add_row(items, lower, upper):
            row = len(row_lower)
            for column, coefficient in items:
                row_ids.append(row)
                col_ids.append(column)
                coefficients.append(coefficient)
            row_lower.append(lower)
            row_upper.append(upper)

        add_row([(j, 1.0) for j in outgoing.get((0, start), [])], 1.0, 1.0)
        for t in range(1, budget):
            check_build_time()
            for v in sorted(layers[t]):
                add_row([(j, 1.0) for j in incoming[(t, v)]]
                        + [(j, -1.0) for j in outgoing.get((t, v), [])], 0.0, 0.0)
        r = 1.0 - q_value
        powers = [r ** k for k in range(budget + 1)]
        if powers[-1] == 0.0:
            result["model_build_s"] = time.perf_counter() - build_started
            return finish("blocked_numerical_scale", "positive_survival_power_underflowed")
        for t in range(1, budget + 1):
            check_build_time()
            for i in range(particle_count):
                items = [(count_index(t, i), 1.0)]
                if t > 1:
                    items.append((count_index(t - 1, i), -1.0))
                # Special bins have no incoming searcher arcs and add no hit.
                items.extend((j, -1.0) for j in
                             incoming.get((t, int(motion.cell_ids[t, i])), []))
                add_row(items, 0.0, 0.0)
                for k in range(t):
                    add_row([(survival_index(t, i), 1.0),
                             (count_index(t, i), q_value * powers[k])],
                            powers[k] * (1.0 + q_value * k), np.inf)
        check_build_time()
        objective = np.zeros(variable_count)
        lower = np.zeros(variable_count)
        upper = np.ones(variable_count)
        integral = np.zeros(variable_count, dtype=np.uint8)
        integral[:arc_count] = 1
        for t in range(1, budget + 1):
            for i, weight in enumerate(weights):
                objective[survival_index(t, i)] = weight
                upper[count_index(t, i)] = t
        matrix = coo_matrix((np.asarray(coefficients, dtype=float),
                             (np.asarray(row_ids, dtype=np.int32),
                              np.asarray(col_ids, dtype=np.int32))),
                            shape=(len(row_lower), variable_count)).tocsc()
        result["counts"]["nonzeros"] = int(matrix.nnz)
        nonzero_abs = np.abs(matrix.data[matrix.data != 0])
        minimum_coefficient = float(nonzero_abs.min()) if nonzero_abs.size else None
        result["counts"]["minimum_abs_nonzero_coefficient"] = minimum_coefficient
        result["counts"]["coefficients_below_1e_minus_9"] = int((nonzero_abs < 1e-9).sum())
        if result["counts"]["coefficients_below_1e_minus_9"]:
            result["warnings"].append(
                "Tiny secant coefficients are retained in the submitted matrix; "
                "solver numerical preprocessing may treat them differently. "
                "Replay and independent tiny-instance enumeration remain necessary.")
        check_build_time()
    except _BuildDeadline:
        result["model_build_s"] = time.perf_counter() - build_started
        return finish("budget_exceeded", "model_construction_exhausted_budget")
    result["model_build_s"] = time.perf_counter() - build_started
    remaining = deadline - time.perf_counter() - reserve
    if remaining <= 0:
        return finish("budget_exceeded", "no_solver_time_remaining")
    solver_options = {"time_limit": remaining, "presolve": opts["presolve"],
                      "mip_rel_gap": opts["mip_rel_gap"],
                      "node_limit": opts["node_limit"], "threads": 1}
    result["solver_options"] = dict(solver_options)
    solver_started = time.perf_counter()
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            solved = milp(objective, integrality=integral,
                          bounds=Bounds(lower, upper),
                          constraints=LinearConstraint(matrix, row_lower, row_upper),
                          options=solver_options)
        result["warnings"].extend(str(item.message) for item in caught)
    except Exception as exc:
        result["solver_s"] = time.perf_counter() - solver_started
        result["warnings"].append(f"{type(exc).__name__}: {exc}")
        return finish("solver_error", "milp_exception")
    result["solver_s"] = time.perf_counter() - solver_started
    result["solver_returned_s"] = time.perf_counter() - started
    result["solver_status"] = int(solved.status)
    result["solver_message"] = str(solved.message)
    result["solver_objective_raw"] = _finite_number(getattr(solved, "fun", None))
    result["solver_lower_bound_raw"] = _finite_number(getattr(solved, "mip_dual_bound", None))
    result["solver_gap_raw"] = _finite_number(getattr(solved, "mip_gap", None))
    node_count = _finite_number(getattr(solved, "mip_node_count", None))
    result["solver_node_count"] = None if node_count is None else int(node_count)
    validation_started = time.perf_counter()
    if solved.status in (2, 3):
        result["fatal"] = True
        result["validation_s"] = time.perf_counter() - validation_started
        return finish("fatal_numerical_inconsistency",
                      "solver_infeasible_or_unbounded_despite_verified_feasible_route")
    if getattr(solved, "x", None) is not None:
        vector = np.asarray(solved.x)
        try:
            if vector.shape != (variable_count,) or not np.isfinite(vector).all():
                raise ValueError("invalid primal vector")
            arc_values = vector[:arc_count]
            if np.max(np.abs(arc_values - np.rint(arc_values))) > opts["integrality_atol"]:
                raise ValueError("fractional incumbent cannot be decoded as a route")
            selected = {j for j, value in enumerate(arc_values) if value > 0.5}
            decoded = [start]
            used = set()
            for t in range(1, budget + 1):
                choices = [j for j in outgoing.get((t - 1, decoded[-1]), [])
                           if j in selected]
                if len(choices) != 1:
                    raise ValueError("primal does not contain exactly one outgoing route arc")
                used.add(choices[0])
                decoded.append(arcs[choices[0]][2])
            if selected != used:
                raise ValueError("primal contains extra selected arcs")
            candidate_score = score_path(grid, decoded, start=start, budget=budget,
                                         p=weights, q=q_value, motion=motion)
            true_counts = np.cumsum(
                motion.cell_ids[1:budget + 1] == np.asarray(decoded[1:])[:, None], axis=0)
            primal_counts = vector[count_offset:survival_offset].reshape(budget, particle_count)
            result["primal_count_discrepancy"] = float(np.max(np.abs(primal_counts - true_counts)))
            if result["primal_count_discrepancy"] > opts["integrality_atol"]:
                raise ValueError("primal counts disagree with decoded original particle hits")
            primal_survival = vector[survival_offset:].reshape(budget, particle_count)
            exact_survival = np.power(r, true_counts)
            result["primal_epigraph_violation"] = float(
                np.maximum(exact_survival - primal_survival, 0.0).max())
            if result["primal_epigraph_violation"] > opts["replay_atol"]:
                raise ValueError("primal epigraph underestimates decoded particle survival")
            model_objective = float(objective @ vector)
            raw_objective = result["solver_objective_raw"]
            if raw_objective is None:
                raise ValueError("solver returned a primal vector without a finite objective")
            result["objective_replay_discrepancy"] = abs(candidate_score.J - model_objective)
            result["objective_epigraph_slack"] = model_objective - candidate_score.J
            if abs(model_objective - raw_objective) > opts["replay_atol"]:
                raise ValueError("reported solver objective disagrees with its primal vector")
            if candidate_score.J - model_objective > opts["replay_atol"]:
                raise ValueError("solver objective underestimates original score_path")
            # A nonoptimal integer incumbent may leave z above the exact
            # exponential. Positive epigraph slack is legal and does not
            # invalidate the decoded route or a separate valid dual bound.
            if result["objective_epigraph_slack"] > opts["replay_atol"]:
                result["warnings"].append(
                    "Primal epigraph has positive slack; use original replayed J. "
                    "Optimality requires the replayed U and numerical dual to close.")
            completed_s = time.perf_counter() - started
            on_time = completed_s <= max_seconds
            result["candidate"] = {"path": [int(v) for v in decoded],
                                   "J": candidate_score.J,
                                   "pd_final": candidate_score.pd_final,
                                   "survival": candidate_score.survival.tolist(),
                                   "completed_s": completed_s,
                                   "completed_within_budget": on_time}
            if on_time and candidate_score.J < result["J"]:
                result.update(path=[int(v) for v in decoded], J=candidate_score.J,
                              pd_final=candidate_score.pd_final,
                              survival=candidate_score.survival.tolist())
                result["history"].append({"elapsed_s": completed_s,
                                          "J": candidate_score.J,
                                          "pd_final": candidate_score.pd_final,
                                          "path": [int(v) for v in decoded],
                                          "source": "milp",
                                          "completed_within_budget": True})
        except ValueError as exc:
            result["warnings"].append(str(exc))
            result["fatal"] = True
            result["validation_s"] = time.perf_counter() - validation_started
            return finish("fatal_numerical_inconsistency", "primal_replay_failed")
    bound = result["solver_lower_bound_raw"]
    if bound is not None and bound > result["J"] + opts["replay_atol"]:
        result["fatal"] = True
        result["validation_s"] = time.perf_counter() - validation_started
        return finish("fatal_numerical_inconsistency", "dual_exceeds_verified_upper_bound")
    result["validation_s"] = time.perf_counter() - validation_started
    if time.perf_counter() > deadline:
        return finish("budget_exceeded", "solver_or_replay_exceeded_total_budget")
    if bound is not None:
        # The maximum of 0 and a numerical dual preserves the known nonnegative
        # mathematical bound; numerical provenance is still explicitly retained.
        result["lower_bound"] = max(0.0, bound)
        gap = max(0.0, result["J"] - result["lower_bound"])
        result["global_numeric_gap_absolute"] = gap
        result["global_numeric_gap"] = gap / result["J"] if result["J"] > 0 else 0.0
        result["lower_bound_elapsed_s"] = time.perf_counter() - started
    if solved.status == 0:
        if result["candidate"] is None or bound is None:
            result["fatal"] = True
            return finish("fatal_numerical_inconsistency", "optimal_without_primal_or_dual")
        # Solver status=0 alone is insufficient when a positive mip_rel_gap
        # permits a merely tolerance-optimal incumbent.
        result["numerical_optimality_checked"] = (
            result["global_numeric_gap_absolute"] <= opts["replay_atol"])
        return finish("optimal_numeric" if result["numerical_optimality_checked"]
                      else "gap_tolerance_reached")
    if solved.status == 1:
        return finish("solver_limit", "time_or_node_limit")
    return finish("solver_error", "solver_nonoptimal_status")


def diagnostic_cases(tier="tiny"):
    """Nine fixed cases per tier; model parameters do not depend on outcomes.

    These are new diagnostic instances of the same mathematical problem, not
    reductions that certify the full real archives.  Tiny T=4/5/6 allows the
    existing independent DFS oracle; medium T=12/14/16 has no such promise.
    """
    if tier not in ("tiny", "medium"):
        raise ValueError("tier must be tiny or medium")
    side = 4 if tier == "tiny" else 7
    horizons = (4, 5, 6) if tier == "tiny" else (12, 14, 16)
    grid = GridGraph(side, side)
    cases = []
    for family in ("order", "transfer", "repeat"):
        for variant, horizon in enumerate(horizons):
            if family == "order":
                start = grid.vertex(side // 2, side // 2)
                locations = [grid.vertex(0, 0), grid.vertex(0, side - 1),
                             grid.vertex(side - 1, 0), grid.vertex(side - 1, side - 1)]
                weights = np.array([[0.43, 0.31, 0.17, 0.09],
                                    [0.30, 0.37, 0.13, 0.20],
                                    [0.24, 0.24, 0.29, 0.23]][variant])
                cells = np.tile(locations, (horizon + 1, 1))
                # Slow inward/outward motion at two opposite clusters changes
                # arrival-time value while preserving fixed particle identities.
                for t in range(horizon + 1):
                    shift = (t // (2 + variant)) % 2
                    cells[t, 0] = grid.vertex(0, shift)
                    cells[t, 3] = grid.vertex(side - 1, side - 1 - shift)
            elif family == "transfer":
                start = grid.vertex(0, 0)
                locations = [grid.vertex(1, 0), grid.vertex(0, side - 1),
                             grid.vertex(side - 1, side - 1), grid.vertex(side - 1, 0)]
                weights = np.array([[0.10, 0.60, 0.25, 0.05],
                                    [0.20, 0.50, 0.25, 0.05],
                                    [0.30, 0.40, 0.25, 0.05]][variant])
                cells = np.tile(locations, (horizon + 1, 1))
            else:
                start = grid.vertex(side // 2, side // 2)
                locations = [grid.vertex(side // 2, side // 2 - 1),
                             grid.vertex(side // 2 - 1, side // 2),
                             grid.vertex(0, side - 1), grid.size]
                weights = np.array([[0.60, 0.22, 0.16, 0.02],
                                    [0.48, 0.32, 0.18, 0.02],
                                    [0.38, 0.40, 0.20, 0.02]][variant])
                cells = np.tile(locations, (horizon + 1, 1))
                for t in range(horizon + 1):
                    if variant > 0 and (t // 2) % 2:
                        cells[t, 0] = grid.vertex(side // 2, side // 2)
            ids = np.arange(len(weights), dtype=np.int64)
            motion = ParticleMotion(cells, grid.size, ids)
            case = {"id": f"{tier}_{family}_{variant}", "family": family,
                    "tier": tier, "grid": grid, "start": start,
                    "budget": horizon, "p": weights, "q": 0.78,
                    "motion": motion,
                    "initial_path": _canonical_path(grid, start, horizon)}
            case["metadata"] = diagnostic_case_metadata(case)
            cases.append(case)
    return cases


def diagnostic_case_metadata(case):
    """Complete JSON-serializable instance definition for protocol freezing."""
    return {"id": case["id"], "family": case["family"], "tier": case["tier"],
            "grid": {"rows": case["grid"].rows, "cols": case["grid"].cols},
            "start": int(case["start"]), "budget": int(case["budget"]),
            "p": np.asarray(case["p"]).tolist(), "q": float(case["q"]),
            "cell_ids": case["motion"].cell_ids.tolist(),
            "trajectory_ids": case["motion"].trajectory_ids.tolist(),
            "initial_path": [int(v) for v in case["initial_path"]],
            "scope": "synthetic_diagnostic_only_not_a_real_archive_certificate"}
