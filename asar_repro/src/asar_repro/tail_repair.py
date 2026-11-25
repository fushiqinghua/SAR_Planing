"""Free-endpoint suffix repair under the unchanged full-route objective.

Each phase fixes the route through absolute time a and searches every legal
continuation through T, subject only to admissible bound pruning and explicit
budgets. Terminal position is free. The original unnormalised prefix belief
and its accumulated cost are retained; there is no observation at time zero.
All accepted routes are independently replayed by the original scorer.

This module neither runs a seed planner nor changes the original window
implementation. Completion concerns the requested suffix neighbourhoods,
and results deliberately carry no global epsilon certificate.
"""

from dataclasses import dataclass, field
from heapq import heappop, heappush
from itertools import count
from math import inf, isfinite
from time import perf_counter

from .belief import sensor_probabilities
from .grid import integer
from .heuristic import Heuristic
from .objective import score_path


ATOL = 1e-10
BOUND_MODES = ("zero", "mass_lb", "stdc_lb")


@dataclass
class TailRepairResult:
    path: tuple
    J: float
    Pd: float
    expanded: int
    generated: int
    pruned: int
    peak_open: int
    status: str
    stop_reason: str | None
    incumbent_source: str
    bound_mode: str
    theory_certified: bool = False
    incumbent_history: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    phases: list = field(default_factory=list)
    wall_s: float = 0.0
    completion_reason: str | None = None

    @property
    def history(self):
        return self.incumbent_history


class _Budget:
    """One ledger for all suffix phases, preprocessing and required replay."""

    def __init__(self, max_expansions, max_seconds, max_open):
        self.started = perf_counter()
        for name, value in (("max_expansions", max_expansions), ("max_open", max_open)):
            if value is not None:
                integer(value, name)
        if max_seconds is not None and (not isfinite(max_seconds) or max_seconds < 0):
            raise ValueError("max_seconds must be finite and nonnegative")
        self.deadline = inf if max_seconds is None else self.started + max_seconds
        self.cap, self.open_cap = max_expansions, max_open
        self.expanded = self.generated = self.pruned = self.peak_open = 0
        self.stats = dict(initial_replays=0, phase_replays=0, candidate_replays=0,
                          final_replays=0, replay_wall_s=0.0, bound_calls=0,
                          bound_wall_s=0.0, complete_candidates=0, accepted_improvements=0,
                          candidate_replay_error_J_max=0.0, candidate_replay_error_Pd_max=0.0,
                          state_merging=False, endpoint_free=True, seed_search_run=False,
                          bound_is_unweighted=True, objective="sum M[1:T+1]",
                          budget_scope="one shared ledger including preprocessing and full replay")

    def time_stop(self):
        return "max_seconds" if perf_counter() >= self.deadline else None

    def expansion_stop(self):
        return self.time_stop() or ("max_expansions" if self.cap is not None
                                    and self.expanded >= self.cap else None)


def _settings(budget, bound_mode):
    budget = integer(budget, "budget")
    if bound_mode not in BOUND_MODES:
        raise ValueError("bound_mode must be zero, mass_lb or stdc_lb")
    return budget


def _run(grid, cfg, initial_path, starts, bound_mode, ledger, trace, requested_lengths):
    path = tuple(initial_path)
    history, phases = [], []
    sensor = sensor_probabilities(cfg["q"], grid.size)
    estimate = None
    source = "initial_path"

    def replay(route, kind, *, record_beliefs=False):
        tic = perf_counter()
        result = score_path(grid, route, **cfg, record_beliefs=record_beliefs)
        ledger.stats[kind + "_replays"] += 1
        ledger.stats["replay_wall_s"] += perf_counter() - tic
        return result

    score = replay(path, "initial")

    def record(event, route, g, **extra):
        if trace is not None:
            trace(dict(event=event, path=tuple(route), vertex=route[-1],
                       depth=len(route)-1, g=g, incumbent_J=score.J, **extra))

    def remember(origin, a=None):
        history.append(dict(path=path, J=score.J, Pd=score.pd_final, source=origin,
                            a=a, expanded=ledger.expanded, generated=ledger.generated,
                            elapsed_s=perf_counter()-ledger.started))
        record("incumbent", path, score.J, source=origin, a=a)

    remember(source)
    reason = ledger.time_stop()
    for phase_index, a in enumerate(starts):
        if reason:
            break
        # A zero-length suffix needs no expansion and remains a valid no-op.
        if a < cfg["budget"]:
            reason = ledger.expansion_stop()
            if reason:
                break
        tic = perf_counter()
        before = (ledger.expanded, ledger.generated, ledger.pruned,
                  ledger.stats["accepted_improvements"])
        original = path
        prefix_score = replay(original, "phase", record_beliefs=True)
        initial_J = score.J
        if abs(prefix_score.J-score.J) > ATOL or abs(prefix_score.pd_final-score.pd_final) > ATOL:
            raise AssertionError("phase incumbent replay mismatch")
        prefix = original[:a+1]
        queue = []
        sequence = count()
        local_peak = 0
        reason = ledger.time_stop()
        if estimate is None and a < cfg["budget"] and reason is None:
            # Horizon is always the full absolute T, not the suffix length.
            estimate = Heuristic(grid, budget=cfg["budget"], q=cfg["q"],
                                 motion=cfg["motion"], mode=bound_mode)

        def enqueue(route, belief, g):
            nonlocal path, score, source, local_peak
            depth = len(route)-1
            ledger.generated += int(depth > a)
            if depth == cfg["budget"]:
                ledger.stats["complete_candidates"] += 1
                record("candidate", route, g, a=a)
                # A just-generated improving route is replayed before stopping
                # at a cooperative deadline, so its valid incumbent is kept.
                if g < score.J + ATOL:
                    candidate = replay(route, "candidate")
                    err_j = abs(candidate.J-g)
                    err_pd = abs(candidate.pd_final-(1.0-float(belief.sum())))
                    if err_j > ATOL or err_pd > ATOL:
                        raise AssertionError("tail prediction disagrees with complete replay")
                    ledger.stats["candidate_replay_error_J_max"] = max(
                        ledger.stats["candidate_replay_error_J_max"], err_j)
                    ledger.stats["candidate_replay_error_Pd_max"] = max(
                        ledger.stats["candidate_replay_error_Pd_max"], err_pd)
                    if candidate.J < score.J - ATOL:
                        path, score = tuple(route), candidate
                        source = f"free_tail[{a}:{cfg['budget']}]"
                        ledger.stats["accepted_improvements"] += 1
                        remember(source, a)
                return ledger.time_stop()
            if ledger.time_stop():
                return "max_seconds"
            bound_started = perf_counter()
            h = float(estimate(route[-1], depth, belief))
            ledger.stats["bound_calls"] += 1
            ledger.stats["bound_wall_s"] += perf_counter()-bound_started
            lower = g+h
            if not isfinite(lower) or h < -ATOL:
                raise AssertionError("invalid suffix lower bound")
            if ledger.time_stop():
                return "max_seconds"
            # g already contains the fixed prefix cost. Do not add it twice.
            if lower >= score.J + ATOL:
                ledger.pruned += 1
                record("bound_prune", route, g, a=a, h_bound=h, lower_bound=lower)
                return None
            if ledger.open_cap is not None and len(queue) >= ledger.open_cap:
                return "max_open"  # Never silently drop nodes and claim completion.
            heappush(queue, (lower, next(sequence), tuple(route), belief, g))
            ledger.peak_open = max(ledger.peak_open, len(queue))
            local_peak = max(local_peak, len(queue))
            record("push", route, g, a=a, h_bound=h, lower_bound=lower)
            return ledger.time_stop()

        if reason is None:
            reason = enqueue(prefix, prefix_score.beliefs[a].copy(), float(prefix_score.g[a]))
        while queue and reason is None:
            lower, _, route, belief, g = heappop(queue)
            record("pop", route, g, a=a, lower_bound=lower)
            if lower >= score.J + ATOL:
                ledger.pruned += 1
                continue
            reason = ledger.expansion_stop()
            if reason:
                break
            ledger.expanded += 1
            record("expand", route, g, a=a, lower_bound=lower)
            # Prefix belief already includes the observation at a. The next
            # motion/observation is at absolute a+1, never at local step 1.
            t = len(route)
            prior = cfg["motion"].propagate(belief, step=t)
            for vertex in grid.neighbors(route[-1]):
                detected = cfg["motion"].sense(prior, vertex, sensor, step=t)
                reason = enqueue(route+(vertex,), detected, g+float(detected.sum()))
                if reason:
                    break
        reason = reason or ledger.time_stop()
        phases.append(dict(index=phase_index, a=a, b=cfg["budget"],
                           length=cfg["budget"]-a, endpoint_free=True,
                           fixed_prefix=list(prefix), initial_J=initial_J, final_J=score.J,
                           status="budget_exceeded" if reason else "completed", stop_reason=reason,
                           expanded=ledger.expanded-before[0], generated=ledger.generated-before[1],
                           pruned=ledger.pruned-before[2], peak_open=local_peak,
                           accepted_improvements=ledger.stats["accepted_improvements"]-before[3],
                           frontier_remaining=len(queue), wall_s=perf_counter()-tic))

    final = replay(path, "final")
    if abs(final.J-score.J) > ATOL or abs(final.pd_final-score.pd_final) > ATOL:
        raise AssertionError("final tail incumbent replay mismatch")
    reason = reason or ledger.time_stop()
    wall = perf_counter()-ledger.started
    ledger.stats.update(requested_lengths=requested_lengths, requested_starts=list(starts),
                        completed_phases=sum(row["status"] == "completed" for row in phases),
                        started_phases=len(phases), unstarted_phases=len(starts)-len(phases),
                        deadline_overshoot_s=max(0.0, ledger.started+wall-ledger.deadline))
    return TailRepairResult(path, final.J, final.pd_final, ledger.expanded, ledger.generated,
                            ledger.pruned, ledger.peak_open,
                            "budget_exceeded" if reason else "completed", reason,
                            source, bound_mode, incumbent_history=history, stats=ledger.stats,
                            phases=phases, wall_s=wall,
                            completion_reason=None if reason else "requested_free_tails_exhausted_at_tolerance")


def repair_suffix(grid, *, start, budget, p, q, motion, initial_path, a,
                  bound_mode="stdc_lb", max_expansions=None, max_seconds=None,
                  max_open=None, trace=None):
    """Optimise one free-endpoint suffix [a,T] while retaining path[:a+1]."""
    ledger = _Budget(max_expansions, max_seconds, max_open)
    budget = _settings(budget, bound_mode)
    a = integer(a, "a")
    if a > budget:
        raise ValueError("a must satisfy 0 <= a <= budget")
    cfg = dict(start=start, budget=budget, p=p, q=q, motion=motion)
    return _run(grid, cfg, initial_path, (a,), bound_mode, ledger, trace, [budget-a])


def repair_tail(grid, *, start, budget, p, q, motion, initial_path,
                bound_mode="stdc_lb", lengths=(6, 10), max_expansions=None,
                max_seconds=None, max_open=None, trace=None):
    """Try deterministic suffix lengths with one shared total resource budget.

    Lengths larger than T are capped at T; duplicate resulting start times are
    searched once in first-occurrence order. Caller supplies the initial route
    and is responsible for including any preceding planner's cost in a larger
    experiment budget. This function performs no unreported seed search.
    """
    ledger = _Budget(max_expansions, max_seconds, max_open)
    budget = _settings(budget, bound_mode)
    lengths = tuple(integer(length, "length", 1) for length in lengths)
    if not lengths or len(set(lengths)) != len(lengths):
        raise ValueError("lengths must be nonempty and unique positive integers")
    starts = tuple(dict.fromkeys(max(0, budget-length) for length in lengths))
    cfg = dict(start=start, budget=budget, p=p, q=q, motion=motion)
    return _run(grid, cfg, initial_path, starts, bound_mode, ledger, trace, list(lengths))
