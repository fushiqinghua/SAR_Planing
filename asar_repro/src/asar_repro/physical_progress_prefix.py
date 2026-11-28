"""Experiment-only C0 variant with progress-gated early/middle OPEN quotas.

The solver body is derived from the frozen physical_refinement.py (Git blob
428b2843b3c109246a5bcc50d023f15511c4bf40). The protected C0 files are unchanged.
Only the frontier container and its progress-dependent pop order differ, with scheduler counters
in the returned diagnostics. Original guide, transitions and replay still
run through their original implementations.
"""
from __future__ import annotations

import hashlib
from collections import deque
import heapq
import math
from time import perf_counter

from .physical_accel import CachedPhysicalProblem, _CoarseCellGuide
from .physical_refinement import (
    _ArchiveHistoryLimit, _ArchiveLimit, _Budget, _Deadline, _archive_insert,
    _archive_might_extend, _increment, _json_histogram, _positive_integer,
)
from .physical_search import OBJECTIVE_ATOL, REPLAY_ATOL, _history_entry, _validate_options


PROGRESS_POLICY = {
    "reserved_every": 4,
    "band_order": ["early", "middle"],
    "early": "4*tick < K",
    "middle": "K <= 4*tick < 3*K",
    "tail": "3*K <= 4*tick",
    "key": "original guide priority, original insertion serial",
    "empty_band": "global next",
    "state_drop": False,
    "activation": {
        "first_search_improvement_before_fraction": 0.20,
        "stagnation_seconds": 2.0,
        "window_expansions": 512,
        "tail_enter_fraction": 0.80,
        "tail_exit_fraction": 0.55,
        "recent_improvement_pause_s": 1.0,
    },
}


class _ProgressFrontier:
    """Store entries once and pop an early/middle band head on reserved turns."""

    def __init__(self, tick_count):
        self.tick_count = tick_count
        self._buckets = ([], [], [])
        self._size = 0
        self.global_pops = 0
        self.empty_band_fallback_pops = 0
        self.reserved_pops = [0, 0]

    def __len__(self):
        return self._size

    def push(self, item):
        tick4 = 4 * item[2].tick
        if tick4 < self.tick_count:
            band = 0
        elif tick4 < 3 * self.tick_count:
            band = 1
        else:
            band = 2
        heapq.heappush(self._buckets[band], item)
        self._size += 1

    def pop(self, expanded, allow_reserved=False):
        next_expansion = expanded + 1
        if allow_reserved and next_expansion % 4 == 0:
            band = (next_expansion // 4 - 1) % 2
            if self._buckets[band]:
                self.reserved_pops[band] += 1
                self._size -= 1
                return heapq.heappop(self._buckets[band])
            self.empty_band_fallback_pops += 1
        # The earliest insertion serial breaks ties across bands as in C0.
        global_head = min((bucket for bucket in self._buckets if bucket),
                          key=lambda bucket: bucket[0][:2])
        self.global_pops += 1
        self._size -= 1
        return heapq.heappop(global_head)

    def statistics(self):
        return dict(policy=PROGRESS_POLICY, global_pops=self.global_pops,
                    reserved_early_pops=self.reserved_pops[0],
                    reserved_middle_pops=self.reserved_pops[1],
                    empty_band_fallback_pops=self.empty_band_fallback_pops,
                    final_band_sizes=[len(bucket) for bucket in self._buckets])



class _ProgressController:
    """Causal, constant-space search-progress policy; it never sees future outcomes."""

    def __init__(self, tick_count, total_seconds):
        self.tick_count = int(tick_count)
        self.total_seconds = float(total_seconds)
        self.recent = deque()
        self.tail_count = 0
        self.first_search_improvement_s = None
        self.active = False
        self.calls = 0
        self.active_decisions = 0
        self.events = []
        self.activations = 0
        self.deactivations = 0
        self.max_tail_fraction = 0.0
        self.last_tail_fraction = 0.0
        self._gate = PROGRESS_POLICY["activation"]

    def register_search_improvement(self, elapsed):
        if self.first_search_improvement_s is None:
            self.first_search_improvement_s = float(elapsed)

    def observe_expansion(self, tick):
        window = self._gate["window_expansions"]
        if len(self.recent) == window:
            expired = self.recent.popleft()
            if expired >= self.tick_count - 2:
                self.tail_count -= 1
        self.recent.append(int(tick))
        if tick >= self.tick_count - 2:
            self.tail_count += 1

    def should_reserve(self, elapsed, best_elapsed):
        self.calls += 1
        gate = self._gate
        if len(self.recent) < gate["window_expansions"]:
            return False
        frac = self.tail_count / len(self.recent)
        self.last_tail_fraction = frac
        self.max_tail_fraction = max(self.max_tail_fraction, frac)
        first = self.first_search_improvement_s
        eligible = (first is not None
                    and first <= self.total_seconds * gate["first_search_improvement_before_fraction"])
        since_best = float(elapsed) - (float(best_elapsed) if best_elapsed is not None else 0.0)
        if self.active and (not eligible or frac < gate["tail_exit_fraction"]
                            or since_best < gate["recent_improvement_pause_s"]):
            self.active = False
            self.deactivations += 1
            self.events.append(dict(event="off", elapsed_s=float(elapsed), tail_fraction=frac))
        elif (not self.active and eligible and frac >= gate["tail_enter_fraction"]
              and since_best >= gate["stagnation_seconds"]):
            self.active = True
            self.activations += 1
            self.events.append(dict(event="on", elapsed_s=float(elapsed), tail_fraction=frac))
        if self.active:
            self.active_decisions += 1
        return self.active

    def statistics(self):
        return dict(policy=PROGRESS_POLICY["activation"],
                    first_search_improvement_s=self.first_search_improvement_s,
                    activations=self.activations, deactivations=self.deactivations,
                    active=self.active, active_decisions=self.active_decisions,
                    checked_pops=self.calls, max_tail_fraction=self.max_tail_fraction,
                    last_tail_fraction=self.last_tail_fraction, events=list(self.events))


def solve_physical_progress_prefix(
        problem, *, connectivity, initial_waypoints, max_seconds,
        guide_weight=1.04, max_open=100000, completion="none", objective="J",
        pd_floor=None, pd_tolerance=1e-8, completion_every=128,
        completion_max_calls=32, archive=False, archive_limit=512,
        archive_history_limit=8192, max_expansions=None):
    """Run C0 refinement with causally progress-gated OPEN reservations.

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
    option; normal execution does not hash every expanded state.
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
    history, late, pareto, archive_history = [], [], [], []
    frontier = _ProgressFrontier(problem.tick_count)
    progress = _ProgressController(problem.tick_count, seconds)
    best = None
    initial_score = None
    best_elapsed = None
    stop_reason, error = "frontier_exhausted", None
    cached = None

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
        frontier.push(item)
        state, path = item[2], item[3]
        _increment(histograms["frontier_depth"], len(path) - 1)
        _increment(histograms["frontier_tick"], state.tick)
        stats["peak_open"] = max(stats["peak_open"], len(frontier))

    def pop(allow_reserved=False):
        item = frontier.pop(stats["expanded"], allow_reserved=allow_reserved)
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
            if source == "search":
                progress.register_search_improvement(completed)
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
        if completion == "greedy":
            complete(root, (cached.start,))
        before = perf_counter()
        try:
            guide = _CoarseCellGuide(cached, budget)
        finally:
            stats["preprocessing_s"] += perf_counter() - before
        root_priority = priority(guide, root)
        budget.check()
        serial = 0
        push((root_priority, serial, root, (cached.start,)))
        snapshot()
        while frontier:
            budget.check()
            if max_expansions is not None and stats["expanded"] >= max_expansions:
                stop_reason = "max_expansions"
                break
            allow_reserved = progress.should_reserve(budget.elapsed(), best_elapsed)
            _, _, state, path = pop(allow_reserved)
            # The guard never borrows an infeasible low-J incumbent as a bound.
            if best is not None and state.J >= best["J"] + OBJECTIVE_ATOL:
                stats["safe_pruned"] += 1
                continue
            stats["expanded"] += 1
            progress.observe_expansion(state.tick)
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
        algorithm="physical_progress_prefix_v1",
        implementation_of="paper_guided_physical_cache_v1",
        algorithm_claim="instrumented control or one bounded greedy-completion research candidate",
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
        pruning_rule="accumulated J >= feasible incumbent J + 1e-10; remaining cost is nonnegative",
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
            prefix_order=frontier.statistics(), progress_schedule=progress.statistics(),
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
