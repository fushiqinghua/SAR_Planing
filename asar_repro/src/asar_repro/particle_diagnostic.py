"""Independent fixed-particle LP/MILP diagnostic; never a search certificate.

The minimization LP keeps one time-expanded searcher flow and relaxes binary
positions in exact bounded-product constraints. Only a checked dual/box lower
bound is exposed as ``lower_bound``; a primal LP objective is not a lower bound.
All time indices refer to the original archive, including at a fixed prefix.
"""

from dataclasses import dataclass, field
from math import inf, isfinite, nextafter
from time import perf_counter

import numpy as np
import scipy
from scipy import sparse
from scipy.optimize import Bounds, LinearConstraint, linprog, milp

from .belief import initial_belief, sensor_probabilities
from .grid import integer
from .motion import ParticleMotion
from .objective import score_path


@dataclass
class DiagnosticResult:
    method: str
    status: str
    stop_reason: str | None
    path: tuple | None = None
    J: float | None = None
    Pd: float | None = None
    incumbent_source: str | None = None
    lower_bound: float = 0.0
    lower_bound_source: str = "nonnegative_remaining_objective"
    solver_primal_objective: float | None = None
    solver_dual_bound_estimate: float | None = None
    gap: float | None = None
    solver_status: int | None = None
    solver_message: str | None = None
    theory_certified: bool = False
    model_size: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    dual_verification: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


@dataclass
class _Model:
    c: np.ndarray
    A_ub: object
    b_ub: np.ndarray
    A_eq: object
    b_eq: np.ndarray
    upper: np.ndarray
    lower: np.ndarray
    integrality: np.ndarray
    position_count: int
    size: dict


class _TimeLimit(Exception):
    pass


def _check_time(deadline):
    if perf_counter() >= deadline:
        raise _TimeLimit


def _build_model(grid, *, budget, prefix, p, belief, sensor, motion, deadline):
    """Build with fixed original p bounds, not belief-dependent big-M values."""
    depth, n, vertices = len(prefix) - 1, motion.state_size, grid.size
    remaining = budget - depth
    edges = [(v, u) for v in range(vertices) for u in grid.neighbors(v)]
    outgoing, incoming = [[] for _ in range(vertices)], [[] for _ in range(vertices)]
    for index, (v, u) in enumerate(edges):
        outgoing[v].append(index)
        incoming[u].append(index)
    nx, ny = (remaining + 1) * vertices, remaining * len(edges)
    nw, nz = (remaining + 1) * n, remaining * n
    wbase, zbase, count = nx + ny, nx + ny + nw, nx + ny + nw + nz
    c = np.zeros(count)
    c[wbase + n:zbase] = 1.0
    upper = np.r_[np.ones(nx + ny), np.tile(p, remaining + 1), np.tile(p, remaining)]
    lower = np.zeros(count)
    upper[:vertices] = 0.0
    lower[prefix[-1]] = upper[prefix[-1]] = 1.0
    integrality = np.zeros(count, dtype=np.uint8)
    integrality[:nx] = 1
    er, ec, ev, eb, ur, uc, uv, ub = [], [], [], [], [], [], [], []

    def eq(items, rhs=0.0):
        row = len(eb)
        for col, value in items:
            if value:
                er.append(row); ec.append(col); ev.append(value)
        eb.append(rhs)

    def le(items, rhs=0.0):
        row = len(ub)
        for col, value in items:
            if value:
                ur.append(row); uc.append(col); uv.append(value)
        ub.append(rhs)

    for i in range(n):
        eq(((wbase + i, 1.0),), float(belief[i]))
    active_products = 0
    for k in range(1, remaining + 1):
        _check_time(deadline)
        ybase = nx + (k - 1) * len(edges)
        for v in range(vertices):
            eq([(ybase + e, 1.0) for e in outgoing[v]] + [((k - 1) * vertices + v, -1.0)])
            eq([(ybase + e, 1.0) for e in incoming[v]] + [(k * vertices + v, -1.0)])
        for i, cell in enumerate(motion.cell_ids[depth + k]):
            previous, current = wbase + (k - 1) * n + i, wbase + k * n + i
            z = zbase + (k - 1) * n + i
            detection = float(sensor[cell]) if cell < vertices else 0.0
            eq(((current, 1.0), (previous, -1.0), (z, detection)))
            if detection == 0.0:
                upper[z] = 0.0  # Includes every special bin; its mass survives.
                continue
            x, maximum = k * vertices + int(cell), float(p[i])
            le(((z, 1.0), (previous, -1.0)))
            le(((z, 1.0), (x, -maximum)))
            le(((z, -1.0), (previous, 1.0), (x, maximum)), maximum)
            active_products += 1
    Aeq = sparse.coo_matrix((ev, (er, ec)), shape=(len(eb), count)).tocsr()
    Aub = sparse.coo_matrix((uv, (ur, uc)), shape=(len(ub), count)).tocsr()
    return _Model(c, Aub, np.asarray(ub), Aeq, np.asarray(eb), upper, lower,
                  integrality, nx, dict(variables=count, position_variables=nx,
                  flow_variables=ny, weight_variables=nw, product_variables=nz,
                  binary_variables=nx, equalities=len(eb), inequalities=len(ub),
                  nonzeros=Aeq.nnz + Aub.nnz, active_products=active_products,
                  particles=n, vertices=vertices, directed_edges=len(edges),
                  remaining_steps=remaining, absolute_depth=depth))


def _dot_interval(a, b):
    """Outward-rounded dot interval for finite IEEE-754 input coefficients."""
    low = high = 0.0
    for left, right in zip(a, b):
        product = float(left) * float(right)
        if not isfinite(product):
            raise ValueError("nonfinite product during dual verification")
        # Exact zero needs no widening and avoids artificial subnormal terms.
        if left == 0 or right == 0:
            continue
        low = nextafter(low + nextafter(product, -inf), -inf)
        high = nextafter(high + nextafter(product, inf), inf)
    if not isfinite(low) or not isfinite(high):
        raise ValueError("nonfinite sum during dual verification")
    return low, high


def _verified_dual_bound(model, equality_dual, inequality_dual, *, deadline=inf):
    """Verify a box-corrected dual bound, including stationarity residuals.

    With y <= 0 for A_ub s <= b_ub and free eta, let
    r = c - A_ub.T y - A_eq.T eta. Every feasible s in [l,u] obeys
    c.s >= y.b_ub + eta.b_eq + sum(min(r*l, r*u)).
    Outward rounding encloses each dot/subtraction/product/sum. Thus even
    approximate multipliers remain usable after the box residual correction.
    This checks the stored floating-coefficient LP, not a global SAR guarantee.
    """
    eta = np.asarray(equality_dual, dtype=float)
    raw_y = np.asarray(inequality_dual, dtype=float)
    if (eta.shape != model.b_eq.shape or raw_y.shape != model.b_ub.shape
            or not np.all(np.isfinite(eta)) or not np.all(np.isfinite(raw_y))):
        raise ValueError("missing or nonfinite LP dual multipliers")
    y = np.minimum(raw_y, 0.0)  # Enforce the mathematical inequality sign.
    ae, au = model.A_eq.tocsc(), model.A_ub.tocsc()
    eq_low, _ = _dot_interval(eta, model.b_eq)
    ub_low, _ = _dot_interval(y, model.b_ub)
    base = nextafter(eq_low + ub_low, -inf)
    corrected, correction = base, 0.0
    max_residual = 0.0
    for j in range(len(model.c)):
        if j % 2048 == 0:
            _check_time(deadline)
        es = slice(ae.indptr[j], ae.indptr[j + 1])
        us = slice(au.indptr[j], au.indptr[j + 1])
        el, eh = _dot_interval(ae.data[es], eta[ae.indices[es]])
        ul, uh = _dot_interval(au.data[us], y[au.indices[us]])
        rlow = nextafter(nextafter(float(model.c[j]) - eh, -inf) - uh, -inf)
        rhigh = nextafter(nextafter(float(model.c[j]) - el, inf) - ul, inf)
        max_residual = max(max_residual, abs(rlow), abs(rhigh))
        term = min(nextafter(rlow * float(model.lower[j]), -inf),
                   nextafter(rlow * float(model.upper[j]), -inf))
        correction = nextafter(correction + term, -inf)
        corrected = nextafter(corrected + term, -inf)
    if not isfinite(corrected):
        raise ValueError("nonfinite corrected dual bound")
    return corrected, dict(verified=True, scheme="outward_rounded_box_residual",
        dual_objective_lower=base, box_correction_lower=correction,
        corrected_lower_bound=corrected, max_stationarity_residual=max_residual,
        inequality_sign_projection=float(np.maximum(raw_y, 0).max(initial=0.0)),
        scope="stored floating-coefficient LP; no global search certification")


def _finite(value):
    return float(value) if value is not None and np.isfinite(value) else None


def solve_diagnostic(grid, *, start, budget, p, q, motion, method="lp",
                     max_seconds=30.0, prefix_path=None, initial_path=None,
                     mip_rel_gap=0.0):
    """Diagnose the unchanged J objective; time caps include all local work.

    ``prefix_path`` fixes history and derives its belief by the old scorer.
    LP positions are fractional and never presented as a feasible path.
    MILP paths and provided incumbents are independently replayed. When using
    FutureEquivalentMotion, accepted routes also replay the original archive.
    Solver work is limited by remaining wall time; cooperative build/dual
    checks and mandatory candidate replay can overrun, explicitly reported.
    """
    started = perf_counter()
    budget = integer(budget, "budget")
    grid.coordinates(start)
    if not isinstance(motion, ParticleMotion) or motion.size != grid.size:
        raise ValueError("diagnostic requires ParticleMotion matching the grid")
    motion.check_horizon(budget)
    p = initial_belief(p, motion.state_size)
    sensor = sensor_probabilities(q, grid.size).copy()
    if method not in ("lp", "milp"):
        raise ValueError("method must be lp or milp")
    if not isfinite(max_seconds) or max_seconds < 0:
        raise ValueError("max_seconds must be finite and nonnegative")
    if not isfinite(mip_rel_gap) or mip_rel_gap < 0:
        raise ValueError("mip_rel_gap must be finite and nonnegative")
    prefix = (start,) if prefix_path is None else tuple(prefix_path)
    grid.validate_path(prefix, start=start, budget=len(prefix) - 1)
    if len(prefix) > budget + 1:
        raise ValueError("prefix exceeds budget")
    deadline = started + max_seconds
    out = DiagnosticResult(method, "not_started", None)
    out.timings = dict(model_s=0.0, solver_s=0.0, dual_verification_s=0.0,
                       replay_s=0.0, wall_s=0.0)
    out.metadata = dict(scipy_version=scipy.__version__, absolute_depth=len(prefix)-1,
        horizon=budget, initial_mass=float(p.sum()), archive_frames=len(motion.cell_ids),
        particles=motion.state_size, special_bins_retained=True, t0_detection=False,
        fixed_original_big_m=True, objective="sum M_t, t=1..T", replay_count=0,
        max_seconds=float(max_seconds), prefix=list(prefix),
        lp_primal_used_as_lower_bound=False, solver_bound_is_numerical_estimate=True,
        stop_is_cooperative=True, original_archive_replay_count=0)

    def replay(path, horizon):
        mark = perf_counter()
        try:
            score = score_path(grid, path, start=start, budget=horizon,
                               p=p, q=sensor, motion=motion)
            out.metadata["replay_count"] += 1
            if hasattr(motion, "original_motion"):
                if not np.array_equal(p, motion.initial_weights):
                    raise ValueError("compressed replay requires its original initial weights")
                original = score_path(grid, path, start=start, budget=horizon,
                    p=motion.original_initial_weights, q=sensor, motion=motion.original_motion)
                out.metadata["original_archive_replay_count"] += 1
                if abs(score.J-original.J) > 1e-10 or abs(score.pd_final-original.pd_final) > 1e-10:
                    raise RuntimeError("blocked: compressed/original replay mismatch")
            return score
        finally:
            out.timings["replay_s"] += perf_counter() - mark

    prefix_score = replay(prefix, len(prefix)-1)
    out.lower_bound = prefix_score.J  # Remaining mass is nonnegative.
    if initial_path is not None:
        initial_path = tuple(initial_path)
        if initial_path[:len(prefix)] != prefix:
            raise ValueError("initial path must extend prefix")
        incumbent = replay(initial_path, budget)
        out.path, out.J, out.Pd = initial_path, incumbent.J, incumbent.pd_final
        out.incumbent_source = "initial_path"

    def finish():
        out.timings["wall_s"] = perf_counter() - started
        out.metadata["budget_overrun_s"] = max(0.0, out.timings["wall_s"] - max_seconds)
        if out.J is not None:
            if out.lower_bound > out.J + 1e-8:
                raise RuntimeError("blocked: checked LP lower bound exceeds replayed incumbent")
            out.gap = max(0.0, out.J - out.lower_bound)
        if out.timings["wall_s"] >= max_seconds and out.status == "completed":
            out.status, out.stop_reason = "budget_exhausted", "wall_time_during_finalization"
        return out

    if len(prefix) == budget + 1:
        out.path, out.J, out.Pd = prefix, prefix_score.J, prefix_score.pd_final
        out.incumbent_source = "terminal_prefix"
        out.lower_bound_source = "terminal_prefix_replay"
        out.status = "completed"
        return finish()
    mark = perf_counter()
    try:
        _check_time(deadline)
        model = _build_model(grid, budget=budget, prefix=prefix, p=p,
            belief=prefix_score.final_belief, sensor=sensor, motion=motion, deadline=deadline)
        out.model_size = model.size
        _check_time(deadline)
    except _TimeLimit:
        out.status, out.stop_reason = "budget_exhausted", "wall_time_during_model"
        return finish()
    finally:
        out.timings["model_s"] = perf_counter() - mark

    remaining = deadline - perf_counter()
    mark = perf_counter()
    if method == "lp":
        solved = linprog(model.c, A_ub=model.A_ub, b_ub=model.b_ub,
            A_eq=model.A_eq, b_eq=model.b_eq, bounds=np.c_[model.lower, model.upper],
            method="highs", options={"time_limit": max(1e-9, remaining)})
    else:
        matrix = sparse.vstack((model.A_eq, model.A_ub), format="csc")
        constraints = LinearConstraint(matrix, np.r_[model.b_eq, np.full(len(model.b_ub), -inf)],
                                       np.r_[model.b_eq, model.b_ub])
        solved = milp(model.c, integrality=model.integrality,
            bounds=Bounds(model.lower, model.upper), constraints=constraints,
            options={"time_limit": max(1e-9, deadline-perf_counter()), "mip_rel_gap": mip_rel_gap})
    out.timings["solver_s"] = perf_counter() - mark
    out.solver_status, out.solver_message = int(solved.status), str(solved.message)
    out.status = {0: "completed", 1: "budget_exhausted", 2: "infeasible"}.get(solved.status, "solver_error")
    out.stop_reason = None if solved.status == 0 else str(solved.message)
    primal = _finite(getattr(solved, "fun", None))
    out.solver_primal_objective = None if primal is None else prefix_score.J + primal
    if method == "lp":
        mark = perf_counter()
        try:
            _check_time(deadline)
            bound, report = _verified_dual_bound(model,
                solved.eqlin.marginals, solved.ineqlin.marginals, deadline=deadline)
            out.lower_bound = max(prefix_score.J, nextafter(prefix_score.J + bound, -inf))
            out.lower_bound_source = "verified_box_corrected_lp_dual"
            out.dual_verification = report
        except _TimeLimit:
            out.status, out.stop_reason = "budget_exhausted", "wall_time_during_dual_verification"
            out.dual_verification = dict(verified=False, reason="verification_time_limit")
        except (AttributeError, TypeError, ValueError) as error:
            out.dual_verification = dict(verified=False, reason=str(error))
        finally:
            out.timings["dual_verification_s"] = perf_counter() - mark
    else:
        estimate = _finite(getattr(solved, "mip_dual_bound", None))
        out.solver_dual_bound_estimate = None if estimate is None else prefix_score.J + estimate
        out.metadata["solver_mip_gap"] = _finite(getattr(solved, "mip_gap", None))
        out.metadata["solver_node_count"] = _finite(getattr(solved, "mip_node_count", None))
        values = getattr(solved, "x", None)
        if values is not None:
            positions = np.asarray(values[:model.position_count]).reshape(-1, grid.size)
            integer_error = float(np.max(np.abs(positions - np.rint(positions))))
            out.metadata["position_integrality_error"] = integer_error
            if integer_error <= 1e-5 and np.all(np.abs(positions.sum(axis=1)-1) <= 1e-5):
                candidate = prefix[:-1] + tuple(int(v) for v in positions.argmax(axis=1))
                candidate_score = replay(candidate, budget)
                out.metadata["milp_replayed_J"] = candidate_score.J
                out.metadata["objective_replay_error"] = (None if primal is None else
                    abs(candidate_score.J-prefix_score.J-primal))
                if (primal is not None and solved.status == 0
                        and out.metadata["objective_replay_error"] > 1e-6):
                    raise RuntimeError("blocked: optimal MILP objective disagrees with independent replay")
                if out.J is None or candidate_score.J < out.J:
                    out.path, out.J, out.Pd = candidate, candidate_score.J, candidate_score.pd_final
                    out.incumbent_source = "milp_independent_replay"
            else:
                out.metadata["candidate_rejected"] = "fractional_positions"
    return finish()
