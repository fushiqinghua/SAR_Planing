"""Isolated research search for the constant-speed 4/8-neighbour study.

This is a deterministic, paper-guided anytime *adapter*, not a bit-for-bit
implementation of the paper's search algorithm.  Its coarse-cell lookahead is
only an ordering device.  It is neither a physical-model lower bound nor an
epsilon certificate, and is never used for pruning.  Both connectivities use
exactly the same code and guide; only the legal neighbours change.

The separate tiny oracle deliberately rewrites geometry, clock assignment and
particle sensing in scalar code.  Exhaustive closure is numerical evidence on
the declared toy instance, not a general or exact-arithmetic certificate.
"""

from __future__ import annotations

import heapq
import math
from numbers import Integral
from time import perf_counter

import numpy as np

from .physical_model import PhysicalProblem


OBJECTIVE_ATOL = 1e-10
REPLAY_ATOL = 1e-8
ORACLE_MAX_TICKS = 6
ORACLE_MAX_PARTICLES = 16
ORACLE_MAX_VERTICES = 36


class _Deadline(Exception):
    """Internal cooperative budget stop; never an optimality assertion."""


class _Budget:
    def __init__(self, started, seconds):
        self.started = started
        self.seconds = seconds
        self.deadline = started + seconds

    def elapsed(self):
        return float(perf_counter() - self.started)

    def check(self):
        if perf_counter() >= self.deadline:
            raise _Deadline

    def in_time(self, elapsed):
        return elapsed <= self.seconds


def _validate_options(problem, connectivity, max_seconds):
    if not isinstance(problem, PhysicalProblem):
        raise TypeError("problem must be a PhysicalProblem")
    if isinstance(connectivity, bool) or connectivity not in (4, 8):
        raise ValueError("connectivity must be 4 or 8")
    if isinstance(max_seconds, bool):
        raise ValueError("max_seconds must be finite and nonnegative")
    seconds = float(max_seconds)
    if not math.isfinite(seconds) or seconds < 0.0:
        raise ValueError("max_seconds must be finite and nonnegative")
    return int(connectivity), seconds


def _history_entry(score, elapsed_s, source):
    return dict(elapsed_s=float(elapsed_s), source=source,
                J=float(score["J"]), pd_final=float(score["pd_final"]),
                waypoints=list(score["waypoints"]), path=list(score["waypoints"]))


class _CoarseCellGuide:
    """Optimistic-looking cell-mass rollout used exclusively for heap ordering.

    Once per frame, particle IDs are grouped into occupied coarse cells.  Each
    call uses bincount on those IDs, considers an expanding Euclidean radius,
    and greedily attenuates one coarse cell per remaining observation.  The
    rollout ignores consecutive waypoint feasibility and the oriented square
    footprint, so it has *no* admissibility claim.  Outside/unsearchable mass is
    retained in the residual survival mass.  There is no grid-by-particle scan
    or connectivity-dependent heuristic, and no calls to legacy STDC/parity.
    """

    def __init__(self, problem, budget):
        self.problem = problem
        self.budget = budget
        self.frames = [None]
        vertices = np.arange(problem.size, dtype=np.int64)
        row, col = np.divmod(vertices, problem.cols)
        d = problem.cell_width_m
        self.centres = np.column_stack(((col + 0.5 - problem.cols / 2) * d,
                                       (problem.rows / 2 - row - 0.5) * d))
        for tick in range(1, problem.tick_count + 1):
            budget.check()
            xy = problem.positions_xy[tick]
            ids = np.flatnonzero(problem.searchable[tick] & np.isfinite(xy).all(axis=1))
            valid_xy = xy[ids]
            # Filter in floating point before integer conversion, including
            # finite but extremely remote special/outside coordinates.
            raw_col = np.floor(valid_xy[:, 0] / d + problem.cols / 2)
            raw_south = np.floor(valid_xy[:, 1] / d + problem.rows / 2)
            inside = ((raw_col >= 0) & (raw_col < problem.cols)
                      & (raw_south >= 0) & (raw_south < problem.rows))
            ids = ids[inside]
            cols = raw_col[inside].astype(np.int64)
            rows = problem.rows - 1 - raw_south[inside].astype(np.int64)
            cells, inverse = np.unique(rows * problem.cols + cols, return_inverse=True)
            self.frames.append((ids, cells, inverse))
        budget.check()

    def remaining_cost(self, state):
        self.budget.check()
        weights = state.weights.copy()
        origin = self.problem.vertex_xy(state.vertex)
        squared_distance = np.square(self.centres - origin).sum(axis=1)
        estimated_cost = 0.0
        sensor_radius = self.problem.cell_width_m / math.sqrt(2.0)
        for tick in range(state.tick + 1, self.problem.tick_count + 1):
            self.budget.check()
            ids, cells, inverse = self.frames[tick]
            if len(cells):
                masses = np.bincount(inverse, weights=weights[ids], minlength=len(cells))
                radius = (self.problem.speed_m_s
                          * max(0.0, self.problem.times_s[tick] - state.time_s)
                          + sensor_radius)
                reachable = squared_distance[cells] <= radius * radius
                candidates = np.flatnonzero(reachable)
                if len(candidates):
                    chosen = int(candidates[np.argmax(masses[candidates])])
                    weights[ids[inverse == chosen]] *= 1.0 - self.problem.q
            estimated_cost += float(weights.sum())
        self.budget.check()
        return float(estimated_cost)


def solve_physical(problem, *, connectivity, initial_waypoints, max_seconds,
                   guide_weight=1.04, max_open=100000):
    """Improve a supplied complete route within a charged wall-clock budget.

    Supplying the common initial route is mandatory.  Obtaining that historical
    route is external; copying it and replaying it in this physical model are
    charged here.  A route first validated after the deadline is recorded only
    in ``late_candidates`` and can never become the reported incumbent.

    ``max_open`` is a stop condition, not beam-width truncation.  Only the
    already-incurred objective ``g`` can prune a branch; the conservative
    numerical margin retains near ties.  New candidates are fully replayed
    before acceptance.  Every accepted improvement remains in ``history``.
    """
    started = perf_counter()
    connectivity, seconds = _validate_options(problem, connectivity, max_seconds)
    if isinstance(guide_weight, bool) or not math.isfinite(float(guide_weight)) or float(guide_weight) < 1:
        raise ValueError("guide_weight must be finite and at least one")
    if isinstance(max_open, bool) or not isinstance(max_open, Integral) or max_open < 1:
        raise ValueError("max_open must be a positive integer")
    budget = _Budget(started, seconds)
    stats = dict(expanded=0, generated=0, safe_pruned=0, terminal_candidates=0,
                 replayed_candidates=0, guide_calls=0, peak_open=0,
                 preprocessing_s=0.0, guide_s=0.0, transition_s=0.0,
                 replay_s=0.0, initial_copy_s=0.0)
    history, late, frontier = [], [], []
    best = None
    best_elapsed = None
    stop_reason = "frontier_exhausted"
    error = None

    def timed_replay(route):
        before = perf_counter()
        try:
            return problem.replay(route, connectivity=connectivity)
        finally:
            stats["replay_s"] += perf_counter() - before
            stats["replayed_candidates"] += 1

    def priority(guide, state):
        before = perf_counter()
        try:
            return state.J + float(guide_weight) * guide.remaining_cost(state)
        finally:
            stats["guide_s"] += perf_counter() - before
            stats["guide_calls"] += 1

    try:
        budget.check()
        before = perf_counter()
        initial = tuple(initial_waypoints)
        stats["initial_copy_s"] += perf_counter() - before
        budget.check()
        score = timed_replay(initial)
        completed = budget.elapsed()
        if not budget.in_time(completed):
            late.append(dict(source="initial_route", elapsed_s=completed, score=score))
            raise _Deadline
        best, best_elapsed = score, completed
        history.append(_history_entry(score, completed, "initial_route"))

        before = perf_counter()
        try:
            guide = _CoarseCellGuide(problem, budget)
        finally:
            stats["preprocessing_s"] += perf_counter() - before
        root = problem.initial_state()
        root_priority = priority(guide, root)
        budget.check()
        serial = 0
        heapq.heappush(frontier, (root_priority, serial, root, (problem.start,)))
        stats["peak_open"] = 1
        while frontier:
            budget.check()
            _, _, state, path = heapq.heappop(frontier)
            # No guide, STDC, parity or geometric bound is used here.
            if state.J >= best["J"] + OBJECTIVE_ATOL:
                stats["safe_pruned"] += 1
                continue
            stats["expanded"] += 1
            for target in problem.neighbors(state.vertex, connectivity):
                budget.check()
                before = perf_counter()
                try:
                    child = problem.advance(state, target, connectivity=connectivity)
                finally:
                    stats["transition_s"] += perf_counter() - before
                stats["generated"] += 1
                child_path = path + (target,)
                budget.check()
                if child.terminal:
                    stats["terminal_candidates"] += 1
                    if child.J < best["J"] - OBJECTIVE_ATOL:
                        replayed = timed_replay(child_path)
                        if (abs(replayed["J"] - child.J) > REPLAY_ATOL
                                or abs(replayed["pd_final"] - (1.0 - float(child.weights.sum()))) > REPLAY_ATOL):
                            raise AssertionError("incremental score and full physical replay disagree")
                        completed = budget.elapsed()
                        if not budget.in_time(completed):
                            late.append(dict(source="search", elapsed_s=completed, score=replayed))
                            raise _Deadline
                        if replayed["J"] < best["J"] - OBJECTIVE_ATOL:
                            best, best_elapsed = replayed, completed
                            history.append(_history_entry(replayed, completed, "search"))
                    continue
                if child.J >= best["J"] + OBJECTIVE_ATOL:
                    stats["safe_pruned"] += 1
                    continue
                if len(frontier) >= int(max_open):
                    stop_reason = "max_open"
                    break
                key = priority(guide, child)
                budget.check()
                serial += 1
                heapq.heappush(frontier, (key, serial, child, child_path))
                stats["peak_open"] = max(stats["peak_open"], len(frontier))
            if stop_reason == "max_open":
                break
        budget.check()
    except _Deadline:
        stop_reason = "max_seconds"
    except Exception as exc:
        stop_reason = "exception"
        error = dict(type=type(exc).__name__, message=str(exc))

    status = ("failed" if error else "completed" if stop_reason == "frontier_exhausted"
              else "budget_exceeded")
    result = dict(
        algorithm="paper_guided_physical_anytime_adapter_v1",
        algorithm_claim="research adapter, not a bit-for-bit paper reproduction",
        connectivity=connectivity, footprint=problem.footprint,
        status=status, stop_reason=stop_reason, error=error,
        max_seconds=seconds, max_open=int(max_open), guide_weight=float(guide_weight),
        guide_role="coarse-cell ordering only; not an admissible bound",
        pruning_rule="accumulated J >= incumbent J + 1e-10; remaining cost is nonnegative",
        global_optimality_certified=False, epsilon_certificate=None,
        initial_route_generation_cost="external and excluded; copy and physical replay included",
        best=best, best_elapsed_s=best_elapsed, history=history,
        late_candidates=late, stats=stats, open_count=len(frontier),
        J=None if best is None else best["J"],
        pd_final=None if best is None else best["pd_final"],
        path=None if best is None else best["path"],
        waypoints=None if best is None else best["waypoints"],
        survival=None if best is None else best["survival"],
        expanded=stats["expanded"], generated=stats["generated"],
        peak_open=stats["peak_open"], timings={
            key: value for key, value in stats.items() if key.endswith("_s")},
    )
    result["wall_s"] = budget.elapsed()
    result["elapsed_s"] = result["wall_s"]
    result["deadline_overshoot_s"] = max(0.0, result["wall_s"] - seconds)
    return result


def _oracle_neighbours(vertex, rows, cols, connectivity):
    row, col = divmod(vertex, cols)
    candidates = []
    for other in range(rows * cols):
        rr, cc = divmod(other, cols)
        dr, dc = abs(rr - row), abs(cc - col)
        if (dr + dc == 1) or (connectivity == 8 and dr == dc == 1):
            candidates.append(other)
    return tuple(candidates)


def _oracle_xy(vertex, rows, cols, width):
    row, col = divmod(vertex, cols)
    return ((col + 0.5 - cols / 2.0) * width,
            (rows / 2.0 - row - 0.5) * width)


def independent_replay(problem, waypoints, *, connectivity, _budget=None):
    """Scalar audit evaluator, independent of model transition/sensing code.

    This function uses only the declared problem data.  It does not call model
    geometry, ``advance``, ``observation_mask`` or ``replay``.  The same explicit
    half-open footprint convention and clock tolerance are part of the shared
    mathematical model, not an implementation shortcut.  Intended for tiny
    instances; the exhaustive entry point enforces its own size guard.
    """
    connectivity, _ = _validate_options(problem, connectivity, 0.0)
    route = tuple(waypoints)
    if (not route or route[0] != problem.start
            or any(isinstance(v, bool) or not isinstance(v, Integral)
                   or v < 0 or v >= problem.rows * problem.cols for v in route)):
        raise ValueError("invalid independent replay route")
    if _budget is not None:
        _budget.check()
    width, speed = float(problem.cell_width_m), float(problem.speed_m_s)
    horizon = float(problem.times_s[-1])
    tolerance = 64.0 * np.finfo(float).eps * horizon
    segments, planned, arrived = [], [0.0], [0.0]
    elapsed, distance, diagonal_distance = 0.0, 0.0, 0.0
    last_partial = False
    final_xy = _oracle_xy(route[0], problem.rows, problem.cols, width)
    for source, target in zip(route, route[1:]):
        if _budget is not None:
            _budget.check()
        if elapsed >= horizon - tolerance:
            raise ValueError("independent route contains commands after H")
        if target not in _oracle_neighbours(source, problem.rows, problem.cols, connectivity):
            raise ValueError("independent route contains an illegal edge")
        x0, y0 = _oracle_xy(source, problem.rows, problem.cols, width)
        x1, y1 = _oracle_xy(target, problem.rows, problem.cols, width)
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        duration = length / speed
        arrival = elapsed + duration
        terminal = arrival >= horizon - tolerance
        end = horizon if terminal else arrival
        last_partial = arrival > horizon + tolerance
        frac = min(1.0, max(0.0, (end - elapsed) / duration))
        final_xy = (x0 + frac * dx, y0 + frac * dy) if last_partial else (x1, y1)
        segments.append((elapsed, end, duration, x0, y0, dx, dy))
        planned.append(float(arrival))
        if not last_partial:
            arrived.append(float(end))
        flown = speed * (end - elapsed)
        distance += flown
        if dx != 0.0 and dy != 0.0:
            diagonal_distance += flown
        elapsed = end
    if elapsed < horizon - tolerance:
        raise ValueError("independent route ends before H")

    weights = [float(w) for w in problem.initial_weights]
    survival = [sum(weights)]
    objective, segment_index = 0.0, 0
    for tick in range(1, len(problem.times_s)):
        if _budget is not None:
            _budget.check()
        now = float(problem.times_s[tick])
        # Equality belongs to the incoming edge, including its heading.
        while now > segments[segment_index][1] + tolerance:
            segment_index += 1
        t0, _, duration, x0, y0, dx, dy = segments[segment_index]
        fraction = min(1.0, max(0.0, (now - t0) / duration))
        aircraft_x, aircraft_y = x0 + fraction * dx, y0 + fraction * dy
        norm = math.hypot(dx, dy)
        forward_x, forward_y = dx / norm, dy / norm
        for particle in range(len(weights)):
            if not bool(problem.searchable[tick, particle]):
                continue
            px = float(problem.positions_xy[tick, particle, 0]) - aircraft_x
            py = float(problem.positions_xy[tick, particle, 1]) - aircraft_y
            if problem.footprint == "heading_square":
                first = px * forward_x + py * forward_y
                second = -px * forward_y + py * forward_x
            else:
                first, second = px, py
            if -width / 2 <= first < width / 2 and -width / 2 <= second < width / 2:
                weights[particle] *= 1.0 - problem.q
        mass = sum(weights)
        survival.append(float(mass))
        objective += mass
    score = dict(
        evaluator="independent_scalar_physical_replay_v1",
        J=float(objective), pd_final=float(1.0 - sum(weights)),
        J_time_scaled_s=float(objective * (width / speed)),
        final_weights=weights, survival=survival, waypoints=list(route), path=list(route),
        footprint=problem.footprint, connectivity=connectivity,
        observation_times_s=[float(t) for t in problem.times_s[1:]],
        observation_count=len(problem.times_s) - 1, horizon_s=horizon,
        physical_duration_s=float(elapsed), planned_arrival_times_s=planned,
        arrival_times_s=arrived, distance_m=float(distance),
        diagonal_distance_m=float(diagonal_distance),
        diagonal_distance_fraction=float(diagonal_distance / distance),
        final_xy=list(final_xy), last_edge_partial=bool(last_partial),
        formal_certificate=False,
    )
    # Let the enumerator timestamp the completed score and retain it as raw
    # late evidence when the last scalar observation crossed the deadline.
    return score


def enumerate_physical(problem, *, connectivity, max_seconds):
    """Exhaust all finite command routes on a guarded, tiny physical instance.

    No objective/heuristic pruning is performed.  A final model replay of the
    independent optimum is included in the budget and proof timestamp.  Only
    ``optimal_enumerated`` with ``proof_elapsed_s <= max_seconds`` establishes
    numerical closure; timeout, late audit, blocked and failed are not proofs.
    """
    started = perf_counter()
    connectivity, seconds = _validate_options(problem, connectivity, max_seconds)
    budget = _Budget(started, seconds)
    best, proof_elapsed, audit = None, None, None
    history, late = [], []
    stats = dict(visited=0, complete_routes=0, scored_routes=0, maximum_depth=0,
                 final_audit_s=0.0)
    error = None
    status, stop_reason = "budget_exceeded", "max_seconds"
    enumeration_complete = False
    complete_elapsed = None
    guard = (problem.tick_count > ORACLE_MAX_TICKS
             or len(problem.initial_weights) > ORACLE_MAX_PARTICLES
             or problem.size > ORACLE_MAX_VERTICES)

    def visit(path, elapsed):
        nonlocal best
        budget.check()
        stats["visited"] += 1
        stats["maximum_depth"] = max(stats["maximum_depth"], len(path) - 1)
        if elapsed >= problem.horizon_s - problem.time_tolerance_s:
            stats["complete_routes"] += 1
            score = independent_replay(problem, path, connectivity=connectivity, _budget=budget)
            completed = budget.elapsed()
            stats["scored_routes"] += 1
            if not budget.in_time(completed):
                late.append(dict(source="enumeration", elapsed_s=completed, score=score))
                raise _Deadline
            # Enumeration reports the actual minimum of its floating-point
            # scores; unlike heuristic search, it must not merge near ties.
            if best is None or score["J"] < best["J"]:
                best = score
                history.append(_history_entry(score, completed, "enumeration"))
            return
        source = path[-1]
        x0, y0 = _oracle_xy(source, problem.rows, problem.cols, problem.cell_width_m)
        for target in _oracle_neighbours(source, problem.rows, problem.cols, connectivity):
            budget.check()
            x1, y1 = _oracle_xy(target, problem.rows, problem.cols, problem.cell_width_m)
            duration = math.hypot(x1 - x0, y1 - y0) / problem.speed_m_s
            visit(path + (target,), elapsed + duration)

    if guard:
        status, stop_reason = "blocked", "tiny_oracle_size_guard"
    else:
        try:
            visit((problem.start,), 0.0)
            complete_elapsed = budget.elapsed()
            budget.check()
            if best is None:
                raise AssertionError("exhausted oracle has no feasible complete route")
            before = perf_counter()
            try:
                audit = problem.replay(best["waypoints"], connectivity=connectivity)
            finally:
                stats["final_audit_s"] += perf_counter() - before
            if (abs(best["J"] - audit["J"]) > REPLAY_ATOL
                    or abs(best["pd_final"] - audit["pd_final"]) > REPLAY_ATOL
                    or len(best["survival"]) != len(audit["survival"])
                    or any(abs(x - y) > REPLAY_ATOL
                           for x, y in zip(best["survival"], audit["survival"]))):
                raise AssertionError("independent oracle and model replay disagree")
            proof_elapsed = budget.elapsed()
            if not budget.in_time(proof_elapsed):
                late.append(dict(source="final_oracle_audit", elapsed_s=proof_elapsed, score=audit))
                raise _Deadline
            enumeration_complete = True
            status, stop_reason = "optimal_enumerated", "all_routes_enumerated_and_replay_verified"
        except _Deadline:
            status, stop_reason = "budget_exceeded", "max_seconds"
        except Exception as exc:
            status, stop_reason = "failed", "exception"
            error = dict(type=type(exc).__name__, message=str(exc))
    result = dict(
        algorithm="independent_tiny_physical_enumeration_v1",
        connectivity=connectivity, footprint=problem.footprint,
        status=status, stop_reason=stop_reason, error=error,
        max_seconds=seconds, enumeration_complete=enumeration_complete,
        enumeration_complete_elapsed_s=complete_elapsed, proof_elapsed_s=proof_elapsed,
        numerical_optimum_established=enumeration_complete,
        global_optimality_certified=False, formal_certificate=False,
        lower_bound=best["J"] if enumeration_complete else None,
        gap=0.0 if enumeration_complete else None,
        guard=dict(max_ticks=ORACLE_MAX_TICKS, max_particles=ORACLE_MAX_PARTICLES,
                   max_vertices=ORACLE_MAX_VERTICES),
        best=best, model_audit=audit, history=history, late_candidates=late, stats=stats,
        J=None if best is None else best["J"],
        pd_final=None if best is None else best["pd_final"],
        path=None if best is None else best["path"],
        waypoints=None if best is None else best["waypoints"],
        survival=None if best is None else best["survival"],
    )
    result["wall_s"] = budget.elapsed()
    result["elapsed_s"] = result["wall_s"]
    result["deadline_overshoot_s"] = max(0.0, result["wall_s"] - seconds)
    return result


def diagnostic_cases():
    """Six fixed JSON-compatible cases, N=4 and K<=4; never result-selected.

    Times/coordinates are dimensionless fixtures realised with d=v=1, giving
    delta=1.  They validate mechanics, not calibrated maritime performance.
    Every seed is a complete legal 4-neighbour route usable by both searches.
    """
    def case(name, purpose, frames, weights, initial, searchable=None):
        return dict(id=name, purpose=purpose, rows=3, cols=3,
                    cell_width_m=1.0, speed_m_s=1.0,
                    times_s=[float(k) for k in range(len(frames))],
                    positions_xy=[[list(point) for point in frame] for frame in frames],
                    searchable=([[True] * 4 for _ in frames] if searchable is None
                                else [list(mask) for mask in searchable]),
                    initial_weights=list(weights), start=4, q=0.78,
                    initial_waypoints=list(initial))

    intercept = [(1.0, 1.0), (0.0, -1.0), (-1.0, 0.0), (0.0, 1.0)]
    repeated = [(0.0, 0.0), (1.0, 0.0), (-1.0, 0.0), (0.0, 1.0)]
    special = [(1.0, 0.0), (0.0, 1.0), (0.0, 0.0), (9.0, 9.0)]
    coverage = [(1.0, 0.0), (1.0, 1.0), (-1.0, 0.0), (0.0, -1.0)]
    return [
        case("diagonal_intercept", "Equal-clock diagonal detection of heavy NE mass before any cardinal route.",
             [intercept] * 3, [0.7, 0.1, 0.1, 0.1], [4, 5, 2]),
        case("late_drift", "Exogenous moving particles cross the fixed-clock sensing locations.", [
            [(-1.0, -0.7), (0.9, 1.0), (-0.8, 0.7), (0.5, -1.0)],
            [(-0.5, -0.4), (0.8, 0.6), (-0.4, 0.8), (0.6, -0.8)],
            [(0.0, 0.0), (0.7, 0.2), (0.0, 0.9), (0.7, -0.6)],
            [(0.5, 0.4), (0.6, -0.2), (0.4, 1.0), (0.8, -0.4)],
            [(1.0, 0.8), (0.5, -0.6), (0.8, 1.1), (0.9, -0.2)],
        ], [0.4, 0.3, 0.2, 0.1], [4, 5, 4, 5, 4]),
        case("repeat_detection", "Repeated visits attenuate persistent particle mass without renormalisation.",
             [repeated] * 5, [0.55, 0.25, 0.1, 0.1], [4, 5, 4, 5, 4]),
        case("special_mass", "Unsearchable and outside mass remains in survival; some IDs deactivate.",
             [special] * 4, [0.4, 0.2, 0.2, 0.2], [4, 5, 4, 5],
             [[True, True, False, False], [True, True, False, False],
              [True, False, False, False], [True, False, False, False]]),
        case("coverage_tradeoff", "Shorter transit to NE can postpone much heavier east-cell coverage.",
             [coverage] * 3, [0.85, 0.05, 0.05, 0.05], [4, 5, 2]),
        case("turning_footprint", "Off-centre particles expose the heading-versus-axis square proxy sensitivity.", [
            [(0.48, 0.48), (0.72, 0.2), (-0.7, 0.1), (0.0, -0.9)],
            [(0.48, 0.48), (0.72, 0.2), (-0.5, 0.2), (0.1, -0.8)],
            [(0.55, 0.55), (0.82, 0.3), (-0.3, 0.3), (0.2, -0.7)],
            [(0.62, 0.62), (0.92, 0.4), (-0.1, 0.4), (0.3, -0.6)],
        ], [0.4, 0.3, 0.2, 0.1], [4, 5, 4, 5]),
    ]


def problem_from_case(case, footprint="heading_square"):
    """Build a physical problem without executing search or enumeration."""
    fields = ("rows", "cols", "cell_width_m", "speed_m_s", "times_s",
              "positions_xy", "searchable", "initial_weights", "start", "q")
    values = {field: case[field] for field in fields}
    values["searchable"] = np.asarray(values["searchable"], dtype=bool)
    return PhysicalProblem(**values, footprint=footprint,
                           trajectory_ids=np.arange(len(case["initial_weights"])))
