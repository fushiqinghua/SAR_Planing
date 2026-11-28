# Isolated extension of physical_rolling_solver.py at commit
# 63357464385d45acf4db6e99adf4f49a80a8edb8 (unchanged in results commit 6084c7d).
# Prefix source SHA-256: 8fdf105cdfa58236ae8d690b911bcb5e1d5ba61659bf79206d741aae1f148405
# Added mechanism: bounded exact-state merge/shadow labels. The original prefix
# solver and its underlying refinement arithmetic remain unchanged.
"""Bounded diagnostics and one complete-route candidate for the physical study.

The frozen cached solver is not modified.  ``completion='none', objective='J',
archive=False`` keeps its heap ordering, transition arithmetic, incumbent rule
and replay triggers, while adding charged counters.  This does not promise the
same wall-clock result: instrumentation itself consumes the common budget.

The sole new completion rule greedily finishes a selected prefix using exact
physical transitions.  Its one-step forecast is an ordering device, not a lower
bound.  The optional terminal-Pd guard changes the constrained objective and
uses only a feasible incumbent for J pruning.  Every accepted or archived route
is independently replayed by the original physical scorer before the deadline.
The archive describes encountered, replayed routes, not a global Pareto front.

Nothing executes at import time.  Experiments and the accompanying tests are
prepared for execution by the user on the frozen local environment.
"""
from __future__ import annotations

import hashlib
import heapq
import math
from numbers import Integral
from time import perf_counter

from .physical_accel import CachedPhysicalProblem, _CoarseCellGuide
from .physical_state_merge import ExactStateMerge
from .physical_search import OBJECTIVE_ATOL, REPLAY_ATOL, _history_entry, _validate_options


class _Deadline(Exception):
    """Cooperative deadline; no candidate validated after it is usable."""


class _ArchiveLimit(Exception):
    """Preserve the first overflowing point and stop instead of truncating."""


class _ArchiveHistoryLimit(Exception):
    """Bound insertion evidence without silently dropping earlier witnesses."""


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


def _positive_integer(value, name):
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def _dominates_or_equals(entry, J, pd_final):
    # Exact score comparisons prevent an artificial tolerance-induced front.
    # Numerical tolerances for replay and the guard are handled separately.
    return entry["J"] <= J and entry["pd_final"] >= pd_final


def _archive_might_extend(archive, J, pd_final):
    return not any(_dominates_or_equals(entry, J, pd_final) for entry in archive)


def _archive_insert(archive, record, limit):
    """Insert a verified point; preserve, then stop on the limit+1 point.

    The stop avoids silently discarding a candidate.  At most ``limit+1`` points
    can be present in the returned archive, and ``max_archive`` explicitly
    records that a further complete search was not performed.
    """
    if not _archive_might_extend(archive, record["J"], record["pd_final"]):
        return False
    archive[:] = [entry for entry in archive
                  if not _dominates_or_equals(record, entry["J"], entry["pd_final"])]
    archive.append(record)
    if len(archive) > limit:
        raise _ArchiveLimit
    return True


def _increment(histogram, key, amount=1):
    value = histogram.get(int(key), 0) + amount
    if value < 0:
        raise AssertionError("frontier histogram became negative")
    if value:
        histogram[int(key)] = value
    else:
        histogram.pop(int(key), None)


def _json_histogram(histogram):
    return {str(key): int(histogram[key]) for key in sorted(histogram)}


def solve_physical_prefix_merge(
        problem, *, connectivity, initial_waypoints, max_seconds,
        guide_weight=1.04, max_open=100000, completion="none", objective="J",
        pd_floor=None, pd_tolerance=1e-8, completion_every=128,
        completion_max_calls=32, archive=False, archive_limit=512,
        archive_history_limit=8192, max_expansions=None, root_prefix=None,
        merge_mode="off", merge_max_entries=16384,
        merge_max_payload_bytes=64 * 1024 * 1024):
    """Run prefix refinement with one bounded exact-state label mechanism.

    Merge OFF preserves finite-expansion search order. SHADOW observes duplicate
    opportunities without removing work. EXACT merges equal future states and
    keeps the smallest J, reopening cheaper labels and skipping stale heap items.
    The index is private to this call and its fixed committed prefix.

    The prefix starts at the original start and must prefix the supplied complete
    initial route. It is replayed on the original clock; J, survival and particle
    weights are never reset or normalized. Every candidate remains a complete
    original-mission route. With root_prefix=(problem.start,), the search
    arithmetic and ordering are the frozen refinement algorithm.

    ``greedy`` attempts completion at the root and after every
    ``completion_every`` expanded heap states, at most ``completion_max_calls``
    times.  At each step it selects the first legal neighbour minimizing
    ``child.J + (K-child.tick)*sum(child.weights)``.  It neither samples nor
    changes q, the clock, geometry, guide, tie order or graph connectivity.

    ``J_pd_guard`` requires the supplied, replayed seed to satisfy
    ``pd_final >= pd_floor-pd_tolerance``.  An invalid seed is a failed task,
    never a silently accepted fallback.  The J bound always comes from a
    feasible incumbent.  The numerical guard tolerance is not an operational
    allowance for a lower final detection probability.

    ``max_expansions`` is solely a finite-prefix test option.  Formal timed
    tasks must leave it as None.  Prefix traces are only emitted with that
    option. Enabled merging constructs exact key bytes during normal search;
    those index costs are explicitly charged and reported.
    """
    started = perf_counter()
    connectivity, seconds = _validate_options(problem, connectivity, max_seconds)
    if (isinstance(guide_weight, bool) or not math.isfinite(float(guide_weight))
            or float(guide_weight) < 1):
        raise ValueError("guide_weight must be finite and at least one")
    max_open = _positive_integer(max_open, "max_open")
    completion_every = _positive_integer(completion_every, "completion_every")
    completion_max_calls = _positive_integer(completion_max_calls, "completion_max_calls")
    archive_limit = _positive_integer(archive_limit, "archive_limit")
    archive_history_limit = _positive_integer(archive_history_limit, "archive_history_limit")
    if max_expansions is not None:
        max_expansions = _positive_integer(max_expansions, "max_expansions")
    if completion not in ("none", "greedy"):
        raise ValueError("completion must be none or greedy")
    if objective not in ("J", "J_pd_guard"):
        raise ValueError("objective must be J or J_pd_guard")
    if not isinstance(archive, bool):
        raise ValueError("archive must be a boolean")
    if (isinstance(pd_tolerance, bool) or not math.isfinite(float(pd_tolerance))
            or float(pd_tolerance) < 0):
        raise ValueError("pd_tolerance must be finite and nonnegative")
    pd_tolerance = float(pd_tolerance)
    if objective == "J_pd_guard":
        if (pd_floor is None or isinstance(pd_floor, bool)
                or not math.isfinite(float(pd_floor)) or not 0 <= float(pd_floor) <= 1):
            raise ValueError("J_pd_guard requires a finite pd_floor in [0,1]")
        pd_floor = float(pd_floor)
    elif pd_floor is not None:
        raise ValueError("pd_floor is only valid with J_pd_guard")

    budget = _Budget(started, seconds)
    merge_index = ExactStateMerge(merge_mode, max_entries=merge_max_entries,
                                  max_payload_bytes=merge_max_payload_bytes)
    stats = dict(
        expanded=0, generated=0, safe_pruned=0, terminal_candidates=0,
        replayed_candidates=0, guide_calls=0, peak_open=0,
        preprocessing_s=0.0, guide_s=0.0, transition_s=0.0,
        replay_s=0.0, initial_copy_s=0.0,
        completion_calls=0, completion_finished=0,
        completion_transitions=0, completion_s=0.0,
        completion_transition_s=0.0, completion_terminal_candidates=0,
        candidate_replay_requests=0, archive_insertions=0,
        guard_rejected_replayed=0,
    )
    histogram_names = (
        "expanded_depth", "expanded_tick", "generated_depth", "generated_tick",
        "frontier_depth", "frontier_tick",
    )
    histograms = {name: {} for name in histogram_names}
    first = dict(first_terminal_generated_s=None, first_search_terminal_generated_s=None,
                 first_completion_terminal_generated_s=None,
                 first_new_complete_replay_s=None)
    snapshot_thresholds = tuple(t for t in (0.0, 1.0, 5.0, 10.0, 20.0, 30.0, 60.0)
                                if t <= seconds)
    next_snapshot = 0
    snapshots, pop_trace = [], []
    history, late, frontier, pareto, archive_history = [], [], [], [], []
    best = None
    initial_score = None
    best_elapsed = None
    stop_reason, error = "frontier_exhausted", None
    cached = None
    prefix = None
    root_evidence = None

    def snapshot(force=False):
        nonlocal next_snapshot
        elapsed = budget.elapsed()
        due = []
        while (next_snapshot < len(snapshot_thresholds)
               and elapsed >= snapshot_thresholds[next_snapshot]):
            due.append(snapshot_thresholds[next_snapshot])
            next_snapshot += 1
        if force or due:
            snapshots.append(dict(
                elapsed_s=elapsed, crossed_thresholds_s=due, final=bool(force),
                expanded=stats["expanded"], generated=stats["generated"],
                open_count=len(frontier),
                frontier_depth=_json_histogram(histograms["frontier_depth"]),
                frontier_tick=_json_histogram(histograms["frontier_tick"]),
                max_expanded_depth=max(histograms["expanded_depth"], default=None),
                max_expanded_tick=max(histograms["expanded_tick"], default=None),
            ))

    def push(item):
        heapq.heappush(frontier, item)
        state, path = item[2], item[3]
        _increment(histograms["frontier_depth"], len(path) - 1)
        _increment(histograms["frontier_tick"], state.tick)
        stats["peak_open"] = max(stats["peak_open"], len(frontier))

    def pop():
        item = heapq.heappop(frontier)
        state, path = item[2], item[3]
        _increment(histograms["frontier_depth"], len(path) - 1, -1)
        _increment(histograms["frontier_tick"], state.tick, -1)
        if max_expansions is not None:
            pop_trace.append(dict(
                priority=item[0], serial=item[1], path=list(path),
                vertex=state.vertex, time_s=state.time_s, tick=state.tick, J=state.J,
                weights_sha256=hashlib.sha256(state.weights.tobytes()).hexdigest(),
            ))
        return item

    def feasible(pd_final):
        return objective == "J" or pd_final >= pd_floor - pd_tolerance

    def timed_replay(route):
        before = perf_counter()
        try:
            return cached.replay(route, connectivity=connectivity)
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

    def record_archive(record):
        # Keep insertion history as well as the final front.  An outer harness
        # may apply a conservative clock offset; if it excludes a later point,
        # it must be able to restore earlier points that this point dominated.
        if _archive_might_extend(pareto, record["J"], record["pd_final"]):
            archive_history.append(record)
            stats["archive_insertions"] += 1
            _archive_insert(pareto, record, archive_limit)
            if len(archive_history) > archive_history_limit:
                raise _ArchiveHistoryLimit

    def note_terminal(source):
        elapsed = budget.elapsed()
        if first["first_terminal_generated_s"] is None:
            first["first_terminal_generated_s"] = elapsed
        key = f"first_{source}_terminal_generated_s"
        if first[key] is None:
            first[key] = elapsed

    def consider(state, path, source):
        """Only fully replayed, timely candidates may enter best or pareto."""
        nonlocal best, best_elapsed
        budget.check()
        incremental_pd = 1.0 - float(state.weights.sum())
        # In guard mode a near-boundary incremental value must be replayed;
        # replay is the authority, never a relaxed surrogate threshold.
        potential_feasible = (objective == "J" or
                              incremental_pd >= pd_floor - pd_tolerance - REPLAY_ATOL)
        could_improve = (potential_feasible and
                         (best is None or state.J < best["J"] - OBJECTIVE_ATOL))
        could_extend = archive and _archive_might_extend(pareto, state.J, incremental_pd)
        if not could_improve and not could_extend:
            return
        stats["candidate_replay_requests"] += 1
        replayed = timed_replay(path)
        if (abs(replayed["J"] - state.J) > REPLAY_ATOL
                or abs(replayed["pd_final"] - incremental_pd) > REPLAY_ATOL
                or len(replayed["survival"]) != len(state.survival)
                or any(abs(a - b) > REPLAY_ATOL
                       for a, b in zip(replayed["survival"], state.survival))):
            raise AssertionError("incremental score and full physical replay disagree")
        completed = budget.elapsed()
        if not budget.in_time(completed):
            late.append(dict(source=source, elapsed_s=completed, score=replayed))
            raise _Deadline
        if first["first_new_complete_replay_s"] is None:
            first["first_new_complete_replay_s"] = completed
        eligible = feasible(replayed["pd_final"])
        if not eligible:
            stats["guard_rejected_replayed"] += 1
        if eligible and (best is None or replayed["J"] < best["J"] - OBJECTIVE_ATOL):
            best, best_elapsed = replayed, completed
            history.append(_history_entry(replayed, completed, source))
        if archive:
            record = _history_entry(replayed, completed, source)
            record["guard_feasible"] = eligible
            record_archive(record)

    def complete(prefix, prefix_path):
        """The sole, deterministic completion rule; all work is charged."""
        if stats["completion_calls"] >= completion_max_calls:
            return
        stats["completion_calls"] += 1
        before_completion = perf_counter()
        try:
            state, path = prefix, prefix_path
            while not state.terminal:
                budget.check()
                chosen, chosen_target, chosen_key = None, None, None
                for target in cached.neighbors(state.vertex, connectivity):
                    budget.check()
                    before = perf_counter()
                    try:
                        child = cached.advance(state, target, connectivity=connectivity)
                    finally:
                        stats["completion_transition_s"] += perf_counter() - before
                    stats["completion_transitions"] += 1
                    budget.check()
                    key = child.J + (cached.tick_count - child.tick) * float(child.weights.sum())
                    if chosen is None or key < chosen_key:
                        chosen, chosen_target, chosen_key = child, target, key
                if chosen is None:
                    raise AssertionError("completion reached a nonterminal vertex without a legal edge")
                state, path = chosen, path + (chosen_target,)
            stats["completion_finished"] += 1
            stats["completion_terminal_candidates"] += 1
            note_terminal("completion")
            consider(state, path, "completion")
        finally:
            # This includes completion's replay and archive handling; do not
            # sum it with those subcomponents to estimate total wall time.
            stats["completion_s"] += perf_counter() - before_completion

    try:
        budget.check()
        cached = CachedPhysicalProblem(problem)
        before = perf_counter()
        initial = tuple(initial_waypoints)
        prefix = (problem.start,) if root_prefix is None else tuple(root_prefix)
        if not prefix or prefix[0] != problem.start or initial[:len(prefix)] != prefix:
            raise ValueError("root_prefix must be an original-start prefix of the complete initial route")
        stats["initial_copy_s"] += perf_counter() - before
        budget.check()
        score = timed_replay(initial)
        completed = budget.elapsed()
        if not budget.in_time(completed):
            late.append(dict(source="initial_route", elapsed_s=completed, score=score))
            raise _Deadline
        initial_score = score
        if not feasible(score["pd_final"]):
            raise ValueError("initial route does not satisfy the declared terminal-Pd guard")
        best, best_elapsed = score, completed
        history.append(_history_entry(score, completed, "initial_route"))
        if archive:
            record = _history_entry(score, completed, "initial_route")
            record["guard_feasible"] = True
            record_archive(record)

        root = cached.initial_state()
        before_prefix = perf_counter()
        for target in prefix[1:]:
            budget.check()
            root = cached.advance(root, target, connectivity=connectivity)
        stats["root_prefix_replay_s"] = perf_counter() - before_prefix
        if root.terminal:
            raise ValueError("root_prefix must end at a full waypoint strictly before the mission horizon")
        root_evidence = dict(
            vertex=root.vertex, time_s=root.time_s, tick=root.tick, J=root.J,
            survival=list(root.survival), remaining_mass=float(root.weights.sum()),
            weights_sha256=hashlib.sha256(root.weights.tobytes()).hexdigest(),
            distance_m=root.distance_m, terminal=root.terminal,
        )
        if completion == "greedy":
            complete(root, prefix)
        before = perf_counter()
        try:
            guide = _CoarseCellGuide(cached, budget)
        finally:
            stats["preprocessing_s"] += perf_counter() - before
        root_priority = priority(guide, root)
        budget.check()
        serial = 0
        merge_index.should_discard(root, source="root")
        budget.check()
        push((root_priority, serial, root, prefix))
        snapshot()
        while frontier:
            budget.check()
            if max_expansions is not None and stats["expanded"] >= max_expansions:
                stop_reason = "max_expansions"
                break
            _, _, state, path = pop()
            stale = merge_index.is_stale(state)
            budget.check()
            if stale:
                continue
            # The guard never borrows an infeasible low-J incumbent as a bound.
            if best is not None and state.J >= best["J"] + OBJECTIVE_ATOL:
                stats["safe_pruned"] += 1
                continue
            stats["expanded"] += 1
            _increment(histograms["expanded_depth"], len(path) - 1)
            _increment(histograms["expanded_tick"], state.tick)
            if (completion == "greedy"
                    and stats["expanded"] % completion_every == 0
                    and stats["completion_calls"] < completion_max_calls):
                complete(state, path)
            for target in cached.neighbors(state.vertex, connectivity):
                budget.check()
                before = perf_counter()
                try:
                    child = cached.advance(state, target, connectivity=connectivity)
                finally:
                    stats["transition_s"] += perf_counter() - before
                stats["generated"] += 1
                child_path = path + (target,)
                _increment(histograms["generated_depth"], len(child_path) - 1)
                _increment(histograms["generated_tick"], child.tick)
                budget.check()
                if child.terminal:
                    stats["terminal_candidates"] += 1
                    note_terminal("search")
                    consider(child, child_path, "search")
                    continue
                if best is not None and child.J >= best["J"] + OBJECTIVE_ATOL:
                    stats["safe_pruned"] += 1
                    continue
                discard = merge_index.should_discard(child)
                budget.check()
                if discard:
                    continue
                if len(frontier) >= max_open:
                    stop_reason = "max_open"
                    break
                key = priority(guide, child)
                budget.check()
                serial += 1
                push((key, serial, child, child_path))
            snapshot()
            if stop_reason == "max_open":
                break
        budget.check()
    except _Deadline:
        stop_reason = "max_seconds"
    except _ArchiveLimit:
        stop_reason = "max_archive"
    except _ArchiveHistoryLimit:
        stop_reason = "max_archive_history"
    except Exception as exc:
        stop_reason = "exception"
        error = dict(type=type(exc).__name__, message=str(exc))

    snapshot(force=True)
    status = ("failed" if error else "completed" if stop_reason == "frontier_exhausted"
              else "budget_exceeded")
    result = dict(
        algorithm="physical_refinement_prefix_merge_v1",
        implementation_of="paper_guided_physical_cache_v1",
        algorithm_claim="prefix search with bounded exact-state lowest-J labels; shadow available",
        state_merge=merge_index.statistics(),
        root_prefix=None if prefix is None else list(prefix), root_state=root_evidence,
        connectivity=connectivity, footprint=problem.footprint,
        status=status, stop_reason=stop_reason, error=error,
        max_seconds=seconds, max_open=max_open, guide_weight=float(guide_weight),
        max_expansions=max_expansions, formal_timed_task=max_expansions is None,
        completion=completion, completion_every=completion_every,
        completion_max_calls=completion_max_calls,
        completion_priority="child.J + (K-child.tick)*sum(child.weights); legal-neighbour order breaks ties",
        objective=objective, pd_floor=pd_floor, pd_tolerance=pd_tolerance,
        constraint_status=("not_requested" if objective == "J" else
                           "feasible_incumbent" if best is not None else "no_feasible_incumbent"),
        guide_role="unchanged coarse-cell ordering only; neither guide nor completion is a bound",
        pruning_rule="original accumulated-J prune plus optional exact-state lowest-J labels",
        global_optimality_certified=False, epsilon_certificate=None,
        initial_route_generation_cost="external historical route; copy and original physical replay included",
        initial_score=initial_score,
        best=best, best_elapsed_s=best_elapsed, history=history,
        late_candidates=late, stats=stats, open_count=len(frontier),
        J=None if best is None else best["J"],
        pd_final=None if best is None else best["pd_final"],
        path=None if best is None else best["path"],
        waypoints=None if best is None else best["waypoints"],
        survival=None if best is None else best["survival"],
        expanded=stats["expanded"], generated=stats["generated"], peak_open=stats["peak_open"],
        timings={key: value for key, value in stats.items() if key.endswith("_s")},
        timing_note="completion_s includes its transition, replay and archive subcomponents; do not add twice",
        cache_statistics=None if cached is None else cached.cache_statistics(),
        diagnostics=dict(
            **first, histograms={name: _json_histogram(histograms[name]) for name in histogram_names},
            frontier_snapshots=snapshots, pop_trace=pop_trace,
            first_time_scope="new generated/replayed candidates only; supplied initial route excluded",
            snapshot_scope="maintained histogram counters, no full-heap scans; all sampling is charged",
        ),
        pareto_archive=pareto, pareto_archive_history=archive_history,
        archive_enabled=archive, archive_limit=archive_limit,
        archive_history_limit=archive_history_limit,
        archive_limit_reached=stop_reason == "max_archive",
        archive_history_limit_reached=stop_reason == "max_archive_history",
        archive_scope="encountered_replayed_only; J pruning can hide other nondominated routes",
        archive_global_complete=False,
        archive_limit_policy="preserve first overflow point and stop, never silently truncate",
    )
    result["wall_s"] = budget.elapsed()
    result["elapsed_s"] = result["wall_s"]
    result["deadline_overshoot_s"] = max(0.0, result["wall_s"] - seconds)
    return result
