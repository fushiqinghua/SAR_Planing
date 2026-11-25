"""Opt-in fixed-prefix particle MILP repair, with independently replayed routes.

The objective, horizon, motion archive and scorer are unchanged. A solver dual
value concerns only this prefix/corridor subproblem and is a numerical estimate,
never a global epsilon certificate. HiGHS native workspace is not covered by the
managed model-buffer cap; callers must monitor process RSS separately.
"""
from array import array
from dataclasses import dataclass, field
from math import isfinite
from time import perf_counter
import warnings

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_array

from .belief import sensor_probabilities
from .grid import integer
from .motion import ParticleMotion
from .objective import score_path
from .highs_start import milp_with_start

ATOL = 1e-10
INTEGRALITY_ATOL = 1e-7
CONSTRAINT_ATOL = 1e-7


@dataclass
class ExactRepairResult:
    path: tuple
    J: float
    Pd: float
    status: str
    stop_reason: str | None
    incumbent_source: str
    wall_s: float
    model_build_s: float
    solve_s: float
    restricted_lower_bound: float | None
    restricted_gap: float | None
    solver_status: int | None
    solver_message: str | None
    stats: dict = field(default_factory=dict)
    theory_certified: bool = False


class _BuildStop(Exception):
    pass


def solve_exact_repair(grid, *, start, budget, p, q, motion, initial_path,
                       prefix_depth=0, corridor_radius=None, max_seconds=30.,
                       max_memory_bytes=512 * 2**20, node_limit=None,
                       mip_rel_gap=0., warm_start=False, objective_cutoff=False):
    """Minimize the original J in a fixed-prefix, free-endpoint neighborhood.

    ``corridor_radius`` is Manhattan distance to ANY vertex of the incumbent's
    suffix (including its prefix endpoint), intersected at each absolute time
    with exact reachability. ``None`` uses the entire reachable suffix cone.
    Identical future particle columns are grouped only inside this fixed-prefix
    model, with their original undetected weights summed; search histories are
    not merged. Zero-weight groups contribute exactly zero and may be omitted.
    """
    begun = perf_counter()
    if not isinstance(warm_start, bool) or not isinstance(objective_cutoff, bool):
        raise ValueError('warm_start and objective_cutoff must be boolean')
    budget = integer(budget, "budget")
    prefix_depth = integer(prefix_depth, "prefix_depth")
    if prefix_depth > budget:
        raise ValueError("prefix_depth must not exceed budget")
    if corridor_radius is not None:
        corridor_radius = integer(corridor_radius, "corridor_radius")
    if max_memory_bytes is not None:
        max_memory_bytes = integer(max_memory_bytes, "max_memory_bytes")
    if node_limit is not None:
        node_limit = integer(node_limit, "node_limit")
    if isinstance(max_seconds, bool) or not isinstance(max_seconds, (int, float)) or not isfinite(max_seconds) or max_seconds < 0:
        raise ValueError("max_seconds must be finite and nonnegative")
    if isinstance(mip_rel_gap, bool) or not isinstance(mip_rel_gap, (int, float)) or not isfinite(mip_rel_gap) or mip_rel_gap < 0:
        raise ValueError("mip_rel_gap must be finite and nonnegative")
    if not isinstance(motion, ParticleMotion):
        raise ValueError("exact repair requires a fixed ParticleMotion archive")
    motion.check_horizon(budget)
    path = tuple(initial_path)
    cfg = dict(start=start, budget=budget, p=p, q=q, motion=motion)
    initial = score_path(grid, path, **cfg, record_beliefs=True)
    sensor = sensor_probabilities(q, grid.size)
    deadline = begun + float(max_seconds)
    stats = dict(prefix_depth=prefix_depth, corridor_radius=corridor_radius,
                 endpoint_free=True, bound_scope="restricted_subproblem",
                 bound_kind="solver numerical dual estimate; not independently certified",
                 state_merging=False, objective="original sum(M_t,t=1..T)",
                 t0_sensed=False, initial_J=initial.J, initial_Pd=initial.pd_final,
                 memory_scope="managed model buffers estimate, excluding native HiGHS workspace and input archive",
                 max_memory_bytes=max_memory_bytes, max_seconds=float(max_seconds),
                 node_limit=node_limit, mip_rel_gap=float(mip_rel_gap),
                 integrality_atol=INTEGRALITY_ATOL, constraint_atol=CONSTRAINT_ATOL,
                 replay_atol=ATOL, candidate_accepted=False, real_input_assumed=False)
    stats.update(warm_start_requested=warm_start, objective_cutoff_requested=objective_cutoff,
                 mip_start_submitted=False, mip_start_roundtrip_verified=False)
    stats["native_presolve_policy"] = (
        "disabled: frozen seed1059 model reproduces a false optimum in bundled "
        "HiGHS1.12.0 with presolve and strict native settings; unchanged model "
        "with presolve off matches independent DFS; tolerances remain unchanged")
    model_s = solve_s = 0.
    solver_status = None
    solver_message = None

    def result(status, reason, *, selected=path, score=initial, lower=None, source="initial_path"):
        wall = perf_counter() - begun
        stats["deadline_overshoot_s"] = max(0., wall - max_seconds)
        gap = None if lower is None else max(0., score.J-lower) / max(abs(score.J), 1e-15)
        return ExactRepairResult(tuple(selected), float(score.J), float(score.pd_final),
            status, reason, source, wall, model_s, solve_s, lower, gap,
            solver_status, solver_message, dict(stats), False)

    def check_time():
        if perf_counter() >= deadline:
            raise _BuildStop("max_seconds")

    def check_memory(estimated):
        stats["estimated_peak_model_bytes"] = int(estimated)
        if max_memory_bytes is not None and estimated > max_memory_bytes:
            raise _BuildStop("max_memory_bytes")

    try:
        check_time()
        check_memory(initial.beliefs.nbytes + 4096)
        if prefix_depth == budget:
            model_s = perf_counter()-begun
            stats.update(trivial_fixed_path=True, model_variables=0, model_rows=0)
            solver_message = "No free moves; exact original replay of fixed route."
            return result("completed", None, lower=initial.J)
        if node_limit == 0:
            # SciPy 1.17 can map HiGHS' zero-node solution-limit status to its
            # generic error code. A requested zero-node quota requires no solve.
            model_s = perf_counter()-begun
            stats["node_limit_precheck"] = True
            return result("budget_exceeded","node_limit")
        # A geometric corridor is immutable throughout one solve. Absolute-time
        # parity prevents accidental wait moves or t=0 observations.
        verts = np.arange(grid.size, dtype=np.intp)
        rr, cc = verts//grid.cols, verts%grid.cols
        r0, c0 = grid.coordinates(path[prefix_depth])
        distance = np.abs(rr-r0)+np.abs(cc-c0)
        corridor = np.ones(grid.size, dtype=bool)
        if corridor_radius is not None:
            near = np.full(grid.size, grid.size, dtype=np.intp)
            for v in set(path[prefix_depth:]):
                r, c = grid.coordinates(v)
                np.minimum(near, np.abs(rr-r)+np.abs(cc-c), out=near)
                check_time()
            corridor = near <= corridor_radius
        H = budget-prefix_depth
        layers = {}
        for t in range(prefix_depth+1, budget+1):
            steps = t-prefix_depth
            allowed = np.flatnonzero(corridor & (distance <= steps) & ((steps-distance)%2 == 0))
            if grid.size == 1:
                allowed = np.empty(0, dtype=np.intp)
            if path[t] not in allowed:
                raise AssertionError("incumbent lost from geometric neighborhood")
            layers[t] = allowed
            check_time()
        X = sum(len(v) for v in layers.values())
        check_memory(initial.beliefs.nbytes + grid.size*64 + X*160 + motion.state_size*H*64 + 4096)
        x_index = {}
        k = 0
        for t, allowed in layers.items():
            x_index[t] = {int(v): k+j for j, v in enumerate(allowed)}
            k += len(allowed)
        # Group by every future absolute frame, including special-bin IDs.
        traces, inverse = np.unique(motion.cell_ids[prefix_depth+1:budget+1].T,
                                    axis=0, return_inverse=True)
        weights = np.bincount(inverse, weights=initial.beliefs[prefix_depth], minlength=len(traces))
        groups = []
        offset = float(initial.g[prefix_depth])
        for trace, weight in zip(traces, weights):
            if weight == 0.:
                continue
            events = [(prefix_depth+j+1, int(v), float(sensor[v]))
                      for j, v in enumerate(trace)
                      if int(v) in x_index[prefix_depth+j+1] and sensor[int(v)] > 0.]
            if not events:
                offset += float(weight)*H
            else:
                offset += float(weight)*(events[0][0]-prefix_depth-1)
                groups.append((float(weight), events))
            check_time()
        E = sum(len(events) for _, events in groups)
        G = len(groups)
        nvar = X+2*E-G
        row_upper = H+X+4*E-3*G+int(objective_cutoff)
        nz_upper = 6*X+11*E+(nvar if objective_cutoff else 0)
        # Packed COO assembly + conversion + objective/bounds + Python maps.
        # This conservative reserve is not an OS/native solver memory limit.
        estimate = (initial.beliefs.nbytes+grid.size*64+X*160+motion.state_size*H*64
                    + nvar*(144 if warm_start or objective_cutoff else 128)+row_upper*96+nz_upper*64+65536)
        check_memory(estimate)
        stats.update(original_particle_columns=motion.state_size,
                     future_trace_groups=len(traces), positive_detectable_groups=G,
                     detectable_group_events=E, position_binaries=X,
                     model_variables=nvar, objective_constant=offset,
                     free_steps=H, layer_sizes={str(t):len(v) for t,v in layers.items()},
                     group_prefix_mass=float(weights.sum()),
                     special_mass_retained=True,
                     representation="exact future-trace grouping with event-span residual costs")
        c = np.zeros(nvar, dtype=np.float64)
        integrality = np.zeros(nvar, dtype=np.uint8)
        integrality[:X] = 1
        lbs = np.zeros(nvar, dtype=np.float64)
        ubs = np.ones(nvar, dtype=np.float64)
        seed_vector = np.zeros(nvar) if warm_start or objective_cutoff else None
        if seed_vector is not None:
            for t, xi in x_index.items():
                seed_vector[xi[path[t]]] = 1.
        row_i, col_i, values = array('i'), array('i'), array('d')
        row_low, row_high = array('d'), array('d')

        def row(pairs, lo, hi):
            ix = len(row_low)
            for col, value in pairs:
                if value:
                    row_i.append(ix);col_i.append(int(col));values.append(float(value))
            row_low.append(float(lo));row_high.append(float(hi))
            if ix%256 == 0:
                check_time()

        for t, xi in x_index.items():
            row(((ix,1.) for ix in xi.values()),1.,1.)
            if t == prefix_depth+1:
                # Exact one-step cone has only neighbors of the fixed prefix.
                continue
            prev_x = x_index[t-1]
            for v, ix in xi.items():
                row([(ix,1.)]+[(prev_x[u],-1.) for u in grid.neighbors(v) if u in prev_x],
                    -np.inf,0.)
        next_var = X
        for weight, events in groups:
            previous = None
            residual = 1.
            for j, (t, vertex, detect_q) in enumerate(events):
                rix = next_var;next_var += 1
                next_t = events[j+1][0] if j+1 < len(events) else budget+1
                c[rix] = weight*(next_t-t)
                x = x_index[t][vertex]
                if previous is None:
                    # Initial group residual is 1, hence z=x exactly.
                    row([(rix,1.),(x,detect_q)],1.,1.)
                else:
                    z = next_var;next_var += 1
                    row([(rix,1.),(previous,-1.),(z,detect_q)],0.,0.)
                    row([(z,1.),(previous,-1.)],-np.inf,0.)
                    row([(z,1.),(x,-1.)],-np.inf,0.)
                    row([(z,1.),(previous,-1.),(x,-1.)],-1.,np.inf)
                    if seed_vector is not None:
                        seed_vector[z] = residual*float(path[t] == vertex)
                residual *= 1.-detect_q*float(path[t] == vertex)
                if seed_vector is not None:
                    seed_vector[rix] = residual
                previous = rix
            check_time()
        assert next_var == nvar
        if seed_vector is not None:
            seed_cost = float(c @ seed_vector)
            seed_error = abs(seed_cost+offset-initial.J)
            stats.update(mip_start_original_J=initial.J, mip_start_model_J=seed_cost+offset,
                         mip_start_replay_error=seed_error)
            if seed_error > ATOL:
                raise AssertionError('MIP start original objective mismatch')
            if objective_cutoff:
                # A non-strict feasible upper bound, with one-ulp outward
                # rounding. Never J-delta: the known route must remain feasible.
                upper = float(np.nextafter(max(seed_cost, initial.J-offset), np.inf))
                row(((i,float(c[i])) for i in np.flatnonzero(c)), -np.inf, upper)
                stats.update(objective_cutoff_variable_rhs=upper,
                             objective_cutoff_total_J=upper+offset,
                             objective_cutoff_rounding='max(model start cost, original J-offset), then nextafter(+inf)')
        check_time()
        A = coo_array((np.asarray(values), (np.asarray(row_i),np.asarray(col_i))),
                      shape=(len(row_low),nvar)).tocsc()
        lower_rows, upper_rows = np.asarray(row_low), np.asarray(row_high)
        if seed_vector is not None:
            activity = np.asarray(A @ seed_vector).ravel()
            violation = max(float(np.maximum(lower_rows-activity,0.).max(initial=0.)),
                            float(np.maximum(activity-upper_rows,0.).max(initial=0.)))
            stats['mip_start_constraint_violation'] = violation
            if violation > ATOL or np.any(seed_vector < 0.) or np.any(seed_vector > 1.):
                raise AssertionError('MIP start infeasible')
        stats.update(model_rows=A.shape[0], model_nnz=A.nnz,
                     sparse_matrix_bytes=A.data.nbytes+A.indices.nbytes+A.indptr.nbytes)
        check_time()
        model_s = perf_counter()-begun
        options = dict(time_limit=max(1e-9,deadline-perf_counter()),
                       mip_rel_gap=float(mip_rel_gap), presolve=False, disp=False,
                       mip_abs_gap=0., mip_feasibility_tolerance=1e-10,
                       primal_feasibility_tolerance=1e-10,
                       dual_feasibility_tolerance=1e-10, small_matrix_value=1e-12,
                       threads=1, random_seed=0)
        if node_limit is not None:
            options["node_limit"] = node_limit
        stats["solver_options"] = dict(options)
        solver_begun = perf_counter()
        try:
            # These documented native HiGHS options are passed through by SciPy.
            # Keep its forwarding warning and any other numeric warning in the
            # result, rather than silently suppressing them.
            with warnings.catch_warnings(record=True) as messages:
                warnings.simplefilter("always")
                try:
                    kwargs = dict(integrality=integrality,bounds=Bounds(lbs,ubs),
                                  constraints=LinearConstraint(A,lower_rows,upper_rows),options=options)
                    if warm_start:
                        solved = milp_with_start(c, **kwargs, start=seed_vector, stats=stats)
                    else:
                        solved = milp(c, **kwargs)
                finally:
                    stats["solver_warnings"] = [dict(category=w.category.__name__,message=str(w.message)) for w in messages]
        finally:
            solve_s = perf_counter()-solver_begun
    except _BuildStop as stop:
        model_s = perf_counter()-begun
        return result("budget_exceeded",str(stop))
    except (MemoryError, OverflowError) as exc:
        model_s = perf_counter()-begun
        stats["exception"] = repr(exc)
        return result("budget_exceeded","max_memory_bytes")
    except Exception as exc:
        model_s = max(model_s,perf_counter()-begun-solve_s)
        stats["exception"] = repr(exc)
        return result("blocked","model_or_solver_error")

    solver_status = int(solved.status)
    solver_message = str(solved.message)
    stats["solver_mip_node_count"] = int(getattr(solved,"mip_node_count",0) or 0)
    raw_gap = getattr(solved,"mip_gap",None)
    stats["solver_mip_gap"] = float(raw_gap) if raw_gap is not None and isfinite(raw_gap) else None
    dual = getattr(solved,"mip_dual_bound",None)
    lower = float(dual)+offset if dual is not None and isfinite(dual) else None
    stats["raw_solver_dual_without_constant"] = float(dual) if dual is not None and isfinite(dual) else None
    # A known feasible original route always exists in the subproblem.
    if lower is not None and lower > initial.J+ATOL:
        stats["inconsistent_dual"] = lower
        return result("blocked","dual_exceeds_known_feasible")
    selected, score, source = path, initial, "initial_path"
    solution = getattr(solved,"x",None)
    if solution is not None:
        solution = np.asarray(solution,dtype=float)
        if solution.shape != (nvar,) or not np.all(np.isfinite(solution)):
            return result("blocked","invalid_solver_solution")
        integrality_error = float(np.max(np.abs(solution[:X]-np.rint(solution[:X])))) if X else 0.
        stats["max_integrality_error"] = integrality_error
        if integrality_error > INTEGRALITY_ATOL:
            return result("blocked","nonintegral_solution")
        activity = np.asarray(A@solution).ravel()
        violation = max(float(np.maximum(lower_rows-activity,0.).max(initial=0.)),
                        float(np.maximum(activity-upper_rows,0.).max(initial=0.)),
                        float(np.maximum(lbs-solution,0.).max(initial=0.)),
                        float(np.maximum(solution-ubs,0.).max(initial=0.)))
        stats["max_constraint_violation"] = violation
        if violation > CONSTRAINT_ATOL:
            return result("blocked","solver_constraint_violation")
        candidate = list(path[:prefix_depth+1])
        for t, xi in x_index.items():
            chosen = [v for v,ix in xi.items() if solution[ix] > .5]
            if len(chosen) != 1:
                return result("blocked","invalid_position_selection")
            candidate.append(chosen[0])
        try:
            candidate_score = score_path(grid,candidate,**cfg)
        except (ValueError,AssertionError) as exc:
            stats["exception"] = repr(exc)
            return result("blocked","illegal_solver_route")
        fun = getattr(solved,"fun",None)
        objective = float(c@solution)+offset
        stats.update(candidate_path=candidate,candidate_J=candidate_score.J,
                     candidate_Pd=candidate_score.pd_final,solver_objective=objective,
                     solver_reported_objective=None if fun is None else float(fun)+offset,
                     model_replay_error=abs(objective-candidate_score.J))
        if fun is None or not isfinite(fun) or abs(float(fun)+offset-objective)>ATOL or abs(objective-candidate_score.J)>ATOL:
            return result("blocked","model_replay_mismatch")
        if lower is not None and lower > candidate_score.J+ATOL:
            return result("blocked","dual_exceeds_replayed_candidate")
        if candidate_score.J < initial.J-ATOL:
            selected,score,source = tuple(candidate),candidate_score,"milp_replayed_candidate"
            stats["candidate_accepted"] = True
    if solver_status == 0:
        if solution is None or lower is None:
            return result("blocked","optimal_status_missing_primal_or_dual")
        stats["completion_scope"] = "restricted numerical optimum at configured MIP gap; not global certificate"
        return result("completed",None,selected=selected,score=score,lower=lower,source=source)
    message = solver_message.lower()
    native_node_limit = (solver_status == 4 and node_limit is not None
                         and "highs status 16:" in message
                         and "solution limit reached" in message)
    if solver_status == 1 or native_node_limit:
        # HiGHS has one limit status. Do not pretend to distinguish node/time
        # stops when its message does not provide that information.
        if native_node_limit:
            stats["native_limit_mapping"] = "SciPy status4 / HiGHS16 solution limit with explicit node cap"
        reason = "max_seconds" if "time" in message or perf_counter()>=deadline else "node_limit" if "node" in message or node_limit is not None else "solver_limit"
        return result("budget_exceeded",reason,selected=selected,score=score,lower=lower,source=source)
    return result("blocked","solver_error",selected=selected,score=score,source=source)
