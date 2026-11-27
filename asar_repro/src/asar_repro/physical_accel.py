"""One cache-only candidate for the physical four/eight-neighbour study.

The original model and search modules remain unchanged.  All caches are fresh
inside each charged solve.  The copied solve loop is checked structurally against
the frozen original by local tests; its ordering, numerical margins, incumbent
policy and stop rules are unchanged.  Full route replay delegates to the original
problem.  Nothing executes at import time.

Cache byte counters describe retained ndarray payload, not Python object/RSS
overhead.  The guide's distance vectors use a fixed 64 MiB LRU limit.  Geometry
caches have at most one vertex entry and two neighbour entries per grid vertex,
and one entry per directed edge/connectivity used by the solve.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import fields
import hashlib
import heapq
import json
import math
from math import hypot, isfinite
from numbers import Integral
from time import perf_counter

import numpy as np

from . import physical_search as original_search
from .physical_model import (
    PhysicalProblem, PhysicalState, _connectivity, _integer, _readonly,
)
from .physical_search import OBJECTIVE_ATOL, REPLAY_ATOL, _history_entry, _validate_options


DISTANCE_CACHE_LIMIT_BYTES = 64 * 1024 * 1024


class _Deadline(Exception):
    """Cooperative deadline stop for this module's clock."""


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


def _freeze_owned(array):
    """Freeze a newly owned array without a redundant second payload copy."""
    array.setflags(write=False)
    return array


class CachedPhysicalProblem(PhysicalProblem):
    """Per-solve cache wrapper around one frozen, standard PhysicalProblem.

    Input arrays are already immutable and shared.  No coordinate, edge or guide
    cache is constructed outside this wrapper's lifetime.  Only incremental
    transitions use the cache; replay always uses the original implementation.
    """

    def __init__(self, problem):
        if type(problem) is not PhysicalProblem:
            raise TypeError("cache candidate requires the frozen PhysicalProblem type")
        for item in fields(PhysicalProblem):
            object.__setattr__(self, item.name, getattr(problem, item.name))
        object.__setattr__(self, "_original", problem)
        object.__setattr__(self, "_fixed_horizon", problem.horizon_s)
        object.__setattr__(self, "_fixed_tick_count", problem.tick_count)
        object.__setattr__(self, "_fixed_time_tolerance", problem.time_tolerance_s)
        object.__setattr__(self, "_vertices", {})
        object.__setattr__(self, "_neighbourhoods", {})
        object.__setattr__(self, "_edges", {})
        object.__setattr__(self, "_cache_counts", dict(
            vertex_hits=0, vertex_misses=0, neighbour_hits=0, neighbour_misses=0,
            edge_hits=0, edge_misses=0, owned_weight_copy_elisions=0))
        object.__setattr__(self, "_distance_info", None)

    @property
    def horizon_s(self):
        return self._fixed_horizon

    @property
    def tick_count(self):
        return self._fixed_tick_count

    @property
    def time_tolerance_s(self):
        return self._fixed_time_tolerance

    def vertex_xy(self, vertex):
        vertex = _integer(vertex, "vertex")
        if vertex >= self.size:
            raise ValueError("vertex is outside the grid")
        cached = self._vertices.get(vertex)
        if cached is not None:
            self._cache_counts["vertex_hits"] += 1
            return cached
        self._cache_counts["vertex_misses"] += 1
        cached = PhysicalProblem.vertex_xy(self, vertex)
        cached.setflags(write=False)
        self._vertices[vertex] = cached
        return cached

    def neighbors(self, vertex, connectivity=4):
        connectivity = _connectivity(connectivity)
        vertex = _integer(vertex, "vertex")
        if vertex >= self.size:
            raise ValueError("vertex is outside the grid")
        key = (vertex, connectivity)
        cached = self._neighbourhoods.get(key)
        if cached is not None:
            self._cache_counts["neighbour_hits"] += 1
            return cached
        self._cache_counts["neighbour_misses"] += 1
        cached = PhysicalProblem.neighbors(self, vertex, connectivity)
        self._neighbourhoods[key] = cached
        return cached

    def _geometry(self, source, target, connectivity):
        connectivity = _connectivity(connectivity)
        source = _integer(source, "vertex")
        target = _integer(target, "target")
        key = (source, target, connectivity)
        cached = self._edges.get(key)
        if cached is not None:
            self._cache_counts["edge_hits"] += 1
            return cached
        if target not in self.neighbors(source, connectivity):
            raise ValueError(f"illegal {connectivity}-neighbor edge {source} -> {target}")
        self._cache_counts["edge_misses"] += 1
        source_xy, target_xy = self.vertex_xy(source), self.vertex_xy(target)
        # Keep the exact original arithmetic rather than substituting d or sqrt(2)d.
        duration = hypot(float(target_xy[0] - source_xy[0]),
                         float(target_xy[1] - source_xy[1])) / self.speed_m_s
        if not isfinite(duration) or duration <= 0:
            raise ValueError("edge duration must be finite and positive")
        displacement = target_xy - source_xy
        heading = displacement / (duration * self.speed_m_s)
        sr, sc = self.coordinates(source)
        tr, tc = self.coordinates(target)
        diagonal = abs(sr - tr) == 1 and abs(sc - tc) == 1
        displacement.setflags(write=False)
        heading.setflags(write=False)
        cached = (duration, source_xy, target_xy, displacement, heading, diagonal)
        self._edges[key] = cached
        return cached

    def edge_duration_s(self, source, target, connectivity=4):
        return self._geometry(source, target, connectivity)[0]

    def _advance(self, state, target, connectivity, observations):
        if not isinstance(state, PhysicalState) or state._owner != id(self):
            raise ValueError("state does not belong to this PhysicalProblem")
        if state.terminal:
            raise ValueError("cannot move after the fixed physical horizon")
        target = _integer(target, "target")
        duration, source_xy, target_xy, displacement, heading, diagonal = self._geometry(
            state.vertex, target, connectivity)
        full_arrival = state.time_s + duration
        if not isfinite(full_arrival):
            raise ValueError("planned arrival time exceeds finite numeric range")
        terminal = full_arrival >= self.horizon_s - self.time_tolerance_s
        end = self.horizon_s if terminal else full_arrival
        partial = full_arrival > self.horizon_s + self.time_tolerance_s
        fraction_end = min(1.0, max(0.0, (end - state.time_s) / duration))
        actual_xy = source_xy + fraction_end * displacement
        if not partial:
            actual_xy = target_xy
        weights = state.weights.copy()
        survival = list(state.survival)
        tick, objective = state.tick, state.J
        while tick < self.tick_count and self.times_s[tick + 1] <= end + self.time_tolerance_s:
            tick += 1
            time_s = float(self.times_s[tick])
            if time_s < state.time_s - self.time_tolerance_s:
                raise AssertionError("observation clock moved backwards")
            fraction = min(1.0, max(0.0, (time_s - state.time_s) / duration))
            aircraft_xy = source_xy + fraction * displacement
            hits = self.observation_mask(tick, aircraft_xy, heading)
            before = float(weights.sum())
            weights[hits] *= 1.0 - self.q
            after = float(weights.sum())
            survival.append(after)
            objective += after
            if observations is not None:
                indices = np.flatnonzero(hits)
                observations.append(dict(
                    tick=tick, time_s=time_s, aircraft_xy=aircraft_xy.tolist(),
                    heading_xy=heading.tolist(), source_vertex=state.vertex,
                    target_vertex=target, fraction_of_edge=fraction,
                    sensed_particle_indices=indices.tolist(),
                    sensed_trajectory_ids=(None if self.trajectory_ids is None else
                                           self.trajectory_ids[indices].tolist()),
                    mass_before=before, mass_after=after,
                    detected_mass=before - after, cumulative_J=objective,
                ))
        if terminal and tick != self.tick_count:
            raise AssertionError("terminal route omitted a required observation")
        travelled = self.speed_m_s * (end - state.time_s)
        self._cache_counts["owned_weight_copy_elisions"] += 1
        return PhysicalState(target, float(end), tick, _freeze_owned(weights),
                             float(objective), bool(terminal), _freeze_owned(actual_xy),
                             bool(partial), tuple(survival),
                             state.distance_m + travelled,
                             state.diagonal_distance_m + (travelled if diagonal else 0.0),
                             id(self))

    def replay(self, waypoints, connectivity=4):
        return self._original.replay(waypoints, connectivity=connectivity)

    def cache_statistics(self):
        vertex_bytes = sum(v.nbytes for v in self._vertices.values())
        edge_bytes = sum(edge[3].nbytes + edge[4].nbytes for edge in self._edges.values())
        distance = None if self._distance_info is None else dict(self._distance_info)
        return dict(
            **self._cache_counts,
            vertex_entries=len(self._vertices), neighbour_entries=len(self._neighbourhoods),
            directed_edge_entries=len(self._edges),
            vertex_array_bytes=vertex_bytes, edge_array_bytes=edge_bytes,
            distance_vectors=distance,
            retained_array_bytes=vertex_bytes + edge_bytes + (
                0 if distance is None else distance["current_bytes"]),
            byte_counter_scope="retained ndarray payload only; use sampled RSS for total memory",
            fixed_scalar_cache="original horizon, tick count and time tolerance values",
            scope="fresh caches inside one charged solve; no cross-run reuse",
        )


class _CoarseCellGuide(original_search._CoarseCellGuide):
    """Identical coarse-cell arithmetic with bounded vertex distance reuse."""

    def __init__(self, problem, budget):
        if not isinstance(problem, CachedPhysicalProblem):
            raise TypeError("cached guide requires a fresh CachedPhysicalProblem")
        super().__init__(problem, budget)
        self._distance_vectors = OrderedDict()
        self._distance_stats = dict(
            hits=0, misses=0, evictions=0, oversized_vectors=0,
            entries=0, current_bytes=0, peak_bytes=0,
            limit_bytes=DISTANCE_CACHE_LIMIT_BYTES)
        object.__setattr__(problem, "_distance_info", self._distance_stats)

    def _squared_distance(self, vertex):
        cached = self._distance_vectors.get(vertex)
        if cached is not None:
            self._distance_stats["hits"] += 1
            self._distance_vectors.move_to_end(vertex)
            return cached
        self._distance_stats["misses"] += 1
        origin = self.problem.vertex_xy(vertex)
        squared_distance = np.square(self.centres - origin).sum(axis=1)
        squared_distance.setflags(write=False)
        size = squared_distance.nbytes
        limit = self._distance_stats["limit_bytes"]
        if size > limit:
            self._distance_stats["oversized_vectors"] += 1
            return squared_distance
        while self._distance_stats["current_bytes"] + size > limit:
            _, removed = self._distance_vectors.popitem(last=False)
            self._distance_stats["current_bytes"] -= removed.nbytes
            self._distance_stats["evictions"] += 1
        self._distance_vectors[vertex] = squared_distance
        self._distance_stats["current_bytes"] += size
        self._distance_stats["peak_bytes"] = max(
            self._distance_stats["peak_bytes"], self._distance_stats["current_bytes"])
        self._distance_stats["entries"] = len(self._distance_vectors)
        return squared_distance

    def remaining_cost(self, state):
        self.budget.check()
        weights = state.weights.copy()
        squared_distance = self._squared_distance(state.vertex)
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



def solve_physical_accel(problem, *, connectivity, initial_waypoints, max_seconds,
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
        problem = CachedPhysicalProblem(problem)
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
    result["algorithm"] = "paper_guided_physical_cache_v1"
    result["implementation_of"] = "paper_guided_physical_anytime_adapter_v1"
    result["cache_statistics"] = (problem.cache_statistics()
                                  if isinstance(problem, CachedPhysicalProblem) else None)
    result["wall_s"] = budget.elapsed()
    result["elapsed_s"] = result["wall_s"]
    result["deadline_overshoot_s"] = max(0.0, result["wall_s"] - seconds)
    return result

def _assert_state_equal(reference, candidate):
    scalar_fields = (
        "vertex", "time_s", "tick", "J", "terminal", "last_edge_partial",
        "survival", "distance_m", "diagonal_distance_m",
    )
    for field in scalar_fields:
        if getattr(reference, field) != getattr(candidate, field):
            raise AssertionError(f"exact transition mismatch in {field}")
    for field in ("weights", "actual_xy"):
        a, b = getattr(reference, field), getattr(candidate, field)
        if a.dtype != b.dtype or a.shape != b.shape or not np.array_equal(a, b):
            raise AssertionError(f"exact transition mismatch in {field}")
        if a.flags.writeable or b.flags.writeable:
            raise AssertionError(f"state array became writable: {field}")


def audit_equivalence(problem, *, connectivity, initial_waypoints,
                      max_expansions=128, max_seconds=30, guide_weight=1.04):
    """Bounded deterministic prefix/guide audit, never a performance experiment.

    Each legal transition is evaluated by the original and cached models.  All
    state numbers and guide values must compare exactly, without a tolerance.
    Only equal priorities enter the common heap with the original serial tie
    order.  Thus each recorded pop is the same decision for both implementations
    within this finite work horizon.  Cached state IDs intentionally differ;
    owner IDs are not compared.

    The deadline covers both evaluations and all audit overhead.  Any timeout is
    a failed gate, even when a prefix of the requested workload matched.  This
    finite probe is complemented by the source-structure and exhaustive toy
    checks in local pytest; it is not a whole-instance equivalence proof.
    """
    started = perf_counter()
    connectivity, seconds = _validate_options(problem, connectivity, max_seconds)
    if (isinstance(max_expansions, bool) or not isinstance(max_expansions, Integral)
            or max_expansions < 1):
        raise ValueError("max_expansions must be a positive integer")
    if (isinstance(guide_weight, bool) or not math.isfinite(float(guide_weight))
            or float(guide_weight) < 1):
        raise ValueError("guide_weight must be finite and at least one")
    budget = _Budget(started, seconds)
    stats = dict(expanded=0, generated=0, safe_pruned=0, terminal_candidates=0,
                 compared_states=0, compared_guides=0, compared_neighbourhoods=0,
                 peak_open=0)
    cached = None
    history, trace, frontier = [], [], []
    error, passed = None, False
    stop_reason = "not_started"

    def compare_state(a, b):
        _assert_state_equal(a, b)
        stats["compared_states"] += 1

    def priority(a, b, reference_guide, candidate_guide):
        h_reference = reference_guide.remaining_cost(a)
        h_candidate = candidate_guide.remaining_cost(b)
        if h_reference != h_candidate or not math.isfinite(h_reference):
            raise AssertionError("exact guide value mismatch")
        key_reference = a.J + float(guide_weight) * h_reference
        key_candidate = b.J + float(guide_weight) * h_candidate
        if key_reference != key_candidate:
            raise AssertionError("exact heap priority mismatch")
        stats["compared_guides"] += 1
        return key_reference

    try:
        budget.check()
        cached = CachedPhysicalProblem(problem)
        seed = tuple(initial_waypoints)
        best = problem.replay(seed, connectivity=connectivity)
        budget.check()
        history.append(dict(source="initial_route", J=best["J"],
                            pd_final=best["pd_final"], waypoints=list(seed)))
        reference_guide = original_search._CoarseCellGuide(problem, budget)
        candidate_guide = _CoarseCellGuide(cached, budget)
        reference_state, candidate_state = problem.initial_state(), cached.initial_state()
        compare_state(reference_state, candidate_state)
        key = priority(reference_state, candidate_state, reference_guide, candidate_guide)
        serial = 0
        heapq.heappush(frontier, (key, serial, reference_state, candidate_state, (problem.start,)))
        stats["peak_open"] = 1
        while frontier and stats["expanded"] < int(max_expansions):
            budget.check()
            key, pop_serial, state, candidate_state, path = heapq.heappop(frontier)
            compare_state(state, candidate_state)
            trace.append(dict(
                serial=pop_serial, path=list(path), vertex=state.vertex,
                time_s=state.time_s, tick=state.tick, J=state.J, priority=key,
                weights_sha256=hashlib.sha256(state.weights.tobytes()).hexdigest(),
            ))
            if state.J >= best["J"] + OBJECTIVE_ATOL:
                stats["safe_pruned"] += 1
                continue
            stats["expanded"] += 1
            reference_neighbours = problem.neighbors(state.vertex, connectivity)
            candidate_neighbours = cached.neighbors(candidate_state.vertex, connectivity)
            if reference_neighbours != candidate_neighbours:
                raise AssertionError("neighbour order mismatch")
            stats["compared_neighbourhoods"] += 1
            for target in reference_neighbours:
                budget.check()
                child = problem.advance(state, target, connectivity=connectivity)
                other = cached.advance(candidate_state, target, connectivity=connectivity)
                compare_state(child, other)
                stats["generated"] += 1
                child_path = path + (target,)
                budget.check()
                if child.terminal:
                    stats["terminal_candidates"] += 1
                    if child.J < best["J"] - OBJECTIVE_ATOL:
                        replayed = problem.replay(child_path, connectivity=connectivity)
                        if (replayed["J"] != child.J
                            or replayed["pd_final"] != 1.0-float(child.weights.sum())
                            or replayed["survival"] != list(child.survival)):
                            raise AssertionError("exact original replay mismatch in probe")
                        best = replayed
                        history.append(dict(source="probe", J=best["J"],
                                            pd_final=best["pd_final"], waypoints=list(child_path)))
                    continue
                if child.J >= best["J"] + OBJECTIVE_ATOL:
                    stats["safe_pruned"] += 1
                    continue
                key = priority(child, other, reference_guide, candidate_guide)
                budget.check()
                serial += 1
                heapq.heappush(frontier, (key, serial, child, other, child_path))
                stats["peak_open"] = max(stats["peak_open"], len(frontier))
        budget.check()
        stop_reason = "fixed_work_complete" if frontier else "frontier_exhausted"
        passed = True
    except _Deadline:
        stop_reason = "audit_deadline"
    except Exception as exc:
        stop_reason = "audit_error"
        error = dict(type=type(exc).__name__, message=str(exc))
    trace_hash = hashlib.sha256(json.dumps(
        trace, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    cache_report = None if cached is None else cached.cache_statistics()
    elapsed = budget.elapsed()
    if elapsed > seconds:
        passed = False
        stop_reason = "audit_deadline"
    return dict(
        passed=passed, status="passed" if passed else "failed", stop_reason=stop_reason,
        error=error, max_expansions=int(max_expansions), max_seconds=seconds,
        connectivity=connectivity, footprint=problem.footprint,
        expanded=stats["expanded"], generated=stats["generated"],
        compared_guides=stats["compared_guides"], stats=stats,
        pop_trace=trace, pop_trace_sha256=trace_hash, history=history,
        cache_statistics=cache_report,
        audit_wall_s=elapsed, strict_numerical_equality=True,
        performance_claim=False, global_equivalence_proof=False,
        scope="finite shared prefix probe; no tolerance enlargement and no benchmark conclusion",
    )
