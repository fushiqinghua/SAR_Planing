"""Paper-guided anytime search with a separate, lazy admissible pruning bound.

The paper heuristic orders OPEN only. It never prunes or terminates search.
Every path retains its own belief; no depth/vertex or exact-state merging is
performed. Complete improving candidates are replayed before acceptance.
Results deliberately carry no full-route epsilon certificate.
"""
from dataclasses import dataclass, field
from heapq import heappop, heappush
from itertools import count
from math import inf, isfinite
from time import perf_counter

from .belief import initial_belief, sensor_probabilities
from .grid import integer
from .heuristic import Heuristic
from .objective import score_path

ATOL = 1e-10
BOUND_MODES = ("zero", "mass_lb", "stdc_lb")


@dataclass
class AnytimeResult:
    path: tuple | None
    J: float | None
    Pd: float | None
    expanded: int
    generated: int
    pruned: int
    peak_open: int
    status: str
    stop_reason: str | None
    incumbent_source: str | None
    guide_weight: float
    bound_mode: str
    theory_certified: bool = False
    incumbent_history: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    wall_s: float = 0.0
    completion_reason: str | None = None


def search_anytime(grid, *, start, budget, p, q, motion, initial_path=None,
                   guide_weight=1.04, bound_mode="stdc_lb", max_expansions=None,
                   max_seconds=None, max_open=None, trace=None):
    """Continue past every goal; prune only with unweighted g + h_bound.

    Limits cover initial/final replay, guides, lazy bounds and successor work.
    Time is cooperative: replay a just-generated potential improvement even
    at the deadline, then preserve it when stopping. Expanded counts actual
    successor expansions, excluding popped nodes rejected by the bound.
    """
    started = perf_counter()
    budget = integer(budget, "budget")
    grid.coordinates(start)
    if bound_mode not in BOUND_MODES:
        raise ValueError("bound_mode must be zero, mass_lb or stdc_lb")
    if not isfinite(guide_weight) or guide_weight < 1:
        raise ValueError("guide_weight must be finite and >= 1")
    for name, value in (("max_expansions", max_expansions), ("max_open", max_open)):
        if value is not None:
            integer(value, name)
    if max_seconds is not None and (not isfinite(max_seconds) or max_seconds < 0):
        raise ValueError("max_seconds must be finite and nonnegative")
    deadline = inf if max_seconds is None else started + max_seconds
    cfg = dict(start=start, budget=budget, p=p, q=q, motion=motion)
    guide = Heuristic(grid, budget=budget, q=q, motion=motion, mode="paper_greedy")
    bound = Heuristic(grid, budget=budget, q=q, motion=motion, mode=bound_mode)
    sensor = sensor_probabilities(q, grid.size)
    root_belief = initial_belief(p, motion.state_size)
    queue, history, sequence = [], [], count()
    expanded = generated = pruned = peak_open = 0
    incumbent, incumbent_pd, best_path, source = inf, None, None, None
    stats = dict(guide_calls=0, guide_wall_s=0.0, bound_calls=0, bound_wall_s=0.0,
                 complete_candidates=0, candidate_replays=0, candidate_replay_wall_s=0.0,
                 candidate_replay_error_J_max=0.0, candidate_replay_error_Pd_max=0.0,
                 initial_replays=0, final_replays=0, replay_wall_s=0.0,
                 accepted_improvements=0, popped=0, bound_pruned=0, cheap_pruned=0,
                 max_generated_depth=0, max_expanded_depth=0,
                 guide_used_for_pruning=False, guide_used_for_termination=False,
                 state_merging=False, bound_is_unweighted=True,
                 frontier_count_scope="physical queued nodes only; interrupted work is not enumerated")

    def timed_out():
        return "max_seconds" if perf_counter() >= deadline else None

    def record(event, path, g, **extra):
        if trace is not None:
            trace(dict(event=event, vertex=path[-1], depth=len(path)-1, path=path,
                       g=g, incumbent_J=None if best_path is None else incumbent, **extra))

    def replay(path, kind):
        tic = perf_counter()
        result = score_path(grid, path, **cfg)
        elapsed = perf_counter() - tic
        stats[kind + "_replays"] += 1
        stats["replay_wall_s"] += elapsed
        if kind == "candidate":
            stats["candidate_replay_wall_s"] += elapsed
        return result

    def accept(path, score, origin):
        nonlocal incumbent, incumbent_pd, best_path, source
        incumbent, incumbent_pd, best_path, source = score.J, score.pd_final, tuple(path), origin
        history.append(dict(path=best_path, J=incumbent, Pd=incumbent_pd,
                            expanded=expanded, generated=generated,
                            elapsed_s=perf_counter()-started, source=origin))
        record("incumbent", best_path, incumbent, source=origin)

    def enqueue(path, belief, g):
        nonlocal generated, pruned, peak_open
        depth = len(path)-1
        generated += int(depth > 0)
        stats["max_generated_depth"] = max(stats["max_generated_depth"], depth)
        if depth == budget:
            stats["complete_candidates"] += 1
            record("candidate", path, g)
            # Conservative prediction guard; acceptance uses only replayed J.
            if g < incumbent + ATOL:
                score = replay(path, "candidate")
                err_j, err_pd = abs(score.J-g), abs(score.pd_final-(1-float(belief.sum())))
                if err_j > ATOL or err_pd > ATOL:
                    raise AssertionError("complete candidate disagrees with independent replay")
                stats["candidate_replay_error_J_max"] = max(stats["candidate_replay_error_J_max"], err_j)
                stats["candidate_replay_error_Pd_max"] = max(stats["candidate_replay_error_Pd_max"], err_pd)
                if score.J < incumbent - ATOL:
                    stats["accepted_improvements"] += 1
                    accept(path, score, "search")
            return timed_out()  # Terminal candidates never enter OPEN.
        if timed_out():
            return "max_seconds"
        if g >= incumbent + ATOL:
            pruned += 1
            stats["cheap_pruned"] += 1
            record("cheap_prune", path, g)
            return timed_out()
        tic = perf_counter()
        h_guide = guide(path[-1], depth, belief)
        stats["guide_calls"] += 1
        stats["guide_wall_s"] += perf_counter()-tic
        priority = g + guide_weight*h_guide
        if not isfinite(h_guide) or h_guide < -ATOL or not isfinite(priority):
            raise ValueError("invalid or overflowing paper guide priority")
        if timed_out():
            return "max_seconds"
        if max_open is not None and len(queue) >= max_open:
            return "max_open"  # Stop the whole search; never drop a node and continue.
        heappush(queue, (priority, next(sequence), path, belief, g))
        peak_open = max(peak_open, len(queue))
        record("push", path, g, h_guide=h_guide, f_guide=priority)
        return timed_out()

    if initial_path is not None:
        initial_path = tuple(initial_path)
        accept(initial_path, replay(initial_path, "initial"), "initial_path")
    reason = enqueue((start,), root_belief, 0.0)
    while queue and reason is None:
        reason = timed_out()
        if reason:
            break
        priority, _, path, belief, g = heappop(queue)
        depth = len(path)-1
        stats["popped"] += 1
        record("pop", path, g, f_guide=priority)
        reason = timed_out()
        if reason:
            break
        tic = perf_counter()
        h_bound = bound(path[-1], depth, belief)  # Lazy: never evaluate on enqueue.
        stats["bound_calls"] += 1
        stats["bound_wall_s"] += perf_counter()-tic
        if not isfinite(h_bound) or h_bound < -ATOL:
            raise ValueError("invalid admissible bound")
        reason = timed_out()
        if reason:
            break
        if g+h_bound >= incumbent+ATOL:
            pruned += 1
            stats["bound_pruned"] += 1
            record("bound_prune", path, g, h_bound=h_bound, lower_bound=g+h_bound)
            continue
        if max_expansions is not None and expanded >= max_expansions:
            reason = "max_expansions"
            break
        expanded += 1
        stats["max_expanded_depth"] = max(stats["max_expanded_depth"], depth)
        record("expand", path, g, h_bound=h_bound, lower_bound=g+h_bound)
        prior = motion.propagate(belief, step=depth+1)
        for vertex in grid.neighbors(path[-1]):
            child = motion.sense(prior, vertex, sensor, depth+1)
            reason = enqueue(path+(vertex,), child, g+float(child.sum()))
            if reason:
                break
    if best_path is None and reason is None:
        raise ValueError("no feasible path of the requested length")
    if best_path is not None:
        final = replay(best_path, "final")
        if abs(final.J-incumbent) > ATOL or abs(final.pd_final-incumbent_pd) > ATOL:
            raise AssertionError("final incumbent replay mismatch")
        incumbent, incumbent_pd = final.J, final.pd_final
    reason = reason or timed_out()
    wall = perf_counter()-started
    stats.update(frontier_remaining=len(queue), deadline_overshoot_s=max(0.0, started+wall-deadline))
    return AnytimeResult(best_path, incumbent if best_path is not None else None, incumbent_pd,
                         expanded, generated, pruned, peak_open,
                         "budget_exceeded" if reason else "completed", reason, source,
                         guide_weight, bound_mode, incumbent_history=history, stats=stats, wall_s=wall,
                         completion_reason=None if reason else "frontier_exhausted_at_tolerance")
