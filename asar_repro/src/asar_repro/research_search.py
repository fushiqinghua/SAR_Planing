"""Opt-in research search; frozen search/scoring implementations stay unchanged.

Paper/terminal-interception estimates only order nodes. Pruning uses an
unweighted validated bound. No path states are merged. Auxiliary lookahead
expansions count against the same work cap as actual successor expansions.
"""
from dataclasses import dataclass, field
from heapq import heappop, heappush
from itertools import count
from math import inf, isfinite
from time import perf_counter

import numpy as np

from .anytime_search import AnytimeResult, ATOL
from .belief import initial_belief, sensor_probabilities
from .grid import integer
from .heuristic import Heuristic
from .objective import score_path
from .research_particle import ParticleGuide, FutureEquivalentMotion
from .lookahead_bound import LookaheadBound


@dataclass
class ResearchResult(AnytimeResult):
    candidate_archive: list = field(default_factory=list)


def search_research(grid, *, start, budget, p, q, motion, initial_path=None,
                    guide_weight=1.04, bound_mode="stdc_lb", fast_guide=True,
                    portfolio=False, archive_candidates=True, cascade=False,
                    lookahead_horizon=8,
                    max_expansions=None, max_seconds=None, max_open=None,
                    replay_cfg=None):
    started = perf_counter()
    budget = integer(budget, "budget")
    lookahead_horizon = integer(lookahead_horizon, "lookahead_horizon", 1)
    grid.coordinates(start)
    if bound_mode not in ("zero", "mass_lb", "stdc_lb", "lookahead"):
        raise ValueError("unsupported bound")
    if not isfinite(guide_weight) or guide_weight < 1:
        raise ValueError("guide weight must be finite and >=1")
    for key, val in (("max_expansions", max_expansions), ("max_open", max_open)):
        if val is not None:
            integer(val, key)
    if max_seconds is not None and (not isfinite(max_seconds) or max_seconds < 0):
        raise ValueError("invalid time budget")
    deadline = inf if max_seconds is None else started + max_seconds
    cfg = dict(start=start, budget=budget, p=p, q=q, motion=motion)
    if replay_cfg is not None:
        if (not isinstance(motion, FutureEquivalentMotion)
                or replay_cfg.get("motion") is not motion.original_motion
                or replay_cfg.get("start") != start or replay_cfg.get("budget") != budget
                or not np.array_equal(replay_cfg.get("p"), motion.original_initial_weights)
                or not np.array_equal(p, motion.initial_weights)
                or not np.array_equal(sensor_probabilities(replay_cfg.get("q"), grid.size),
                                      sensor_probabilities(q, grid.size))):
            raise ValueError("alternate replay requires the exact original compressed model")
    scoring = cfg if replay_cfg is None else replay_cfg
    sensor = sensor_probabilities(q, grid.size)
    belief0 = initial_belief(p, motion.state_size)
    guide = (ParticleGuide(grid, budget=budget, q=q, motion=motion) if fast_guide else
             Heuristic(grid, budget=budget, q=q, motion=motion, mode="paper_greedy"))
    bound = (LookaheadBound(grid, budget=budget, q=q, motion=motion, steps=2)
             if bound_mode == "lookahead" else
             Heuristic(grid, budget=budget, q=q, motion=motion, mode=bound_mode))
    cheap = Heuristic(grid, budget=budget, q=q, motion=motion, mode="mass_lb")
    base_bound = Heuristic(grid, budget=budget, q=q, motion=motion, mode="stdc_lb") if bound_mode == "lookahead" else None
    primary, secondary, live, sequence = [], [], {}, count()
    history, archive = [], []
    expanded = generated = pruned = peak_open = 0
    incumbent, incumbent_pd, best, source = inf, None, None, None
    stats = dict(guide_calls=0, guide_wall_s=0., bound_calls=0, bound_wall_s=0.,
                 aux_expanded=0, aux_generated=0, work_expanded=0,
                 complete_candidates=0, candidate_replays=0, candidate_replay_wall_s=0.,
                 accepted_improvements=0, bound_pruned=0, cheap_pruned=0, popped=0,
                 secondary_pops=0, secondary_guide_wall_s=0., stale_entries=0,
                 guide_used_for_pruning=False, guide_used_for_termination=False,
                 state_merging=False, bound_is_unweighted=True, candidate_archive_scope=
                 "nondominated replayed complete candidates encountered, not global Pareto frontier")

    def timeout():
        return "max_seconds" if perf_counter() >= deadline else None

    def score(route):
        return score_path(grid, route, **scoring)

    def accept(route, replay, origin):
        nonlocal incumbent, incumbent_pd, best, source
        incumbent, incumbent_pd, best, source = replay.J, replay.pd_final, tuple(route), origin
        history.append(dict(path=best, J=incumbent, Pd=incumbent_pd, expanded=expanded,
                            work_expanded=expanded+stats["aux_expanded"], generated=generated,
                            elapsed_s=perf_counter()-started, source=origin))

    def dominated(j, pd):
        return any(a["J"] <= j and a["Pd"] >= pd for a in archive)

    def archive_add(route, replay):
        if not archive_candidates or dominated(replay.J, replay.pd_final):
            return
        archive[:] = [a for a in archive
                      if not (replay.J <= a["J"] and replay.pd_final >= a["Pd"])]
        archive.append(dict(path=tuple(route), J=replay.J, Pd=replay.pd_final,
                            elapsed_s=perf_counter()-started, expanded=expanded))

    def terminal_guide(vertex, depth, belief):
        # No-search target distribution at the final absolute frame. This
        # interception estimate is deliberately NOT a bound or return objective.
        prior = belief
        for t in range(depth+1, budget+1):
            prior = motion.propagate(prior, step=t)
        distance = grid.distances_from(vertex)
        remaining = budget-depth
        reachable = np.flatnonzero((distance <= remaining) & ((distance-remaining) % 2 == 0))
        mass = motion.cell_mass(prior, budget)
        gain = float(np.max(sensor[reachable]*mass[reachable], initial=0.))
        return remaining*max(0., float(belief.sum())-gain)

    def enqueue(path, belief, g):
        nonlocal generated, pruned, peak_open
        depth = len(path)-1
        generated += int(depth > 0)
        if depth == budget:
            stats["complete_candidates"] += 1
            pd = 1-float(belief.sum())
            if g < incumbent+ATOL or (archive_candidates and not dominated(g, pd)):
                tic = perf_counter()
                replay = score(path)
                stats["candidate_replays"] += 1
                stats["candidate_replay_wall_s"] += perf_counter()-tic
                if abs(replay.J-g)>ATOL or abs(replay.pd_final-pd)>ATOL:
                    raise AssertionError("candidate original replay mismatch")
                archive_add(path, replay)
                if replay.J < incumbent-ATOL:
                    stats["accepted_improvements"] += 1
                    accept(path, replay, "search")
            return timeout()
        if timeout():
            return "max_seconds"
        if g >= incumbent+ATOL:
            stats["cheap_pruned"] += 1
            pruned += 1
            return None
        tic = perf_counter()
        h = guide(path[-1], depth, belief)
        stats["guide_wall_s"] += perf_counter()-tic
        stats["guide_calls"] += 1
        priority = g+guide_weight*h
        if not isfinite(priority) or not isfinite(h) or h < -ATOL:
            raise ValueError("invalid guide")
        alt = None
        if portfolio:
            tic = perf_counter()
            alt = g+guide_weight*terminal_guide(path[-1], depth, belief)
            stats["secondary_guide_wall_s"] += perf_counter()-tic
        if timeout():
            return "max_seconds"
        needed = 2 if portfolio else 1
        if max_open is not None and len(primary)+len(secondary)+needed > max_open:
            return "max_open"
        uid = next(sequence)
        live[uid] = (path, belief, g)
        heappush(primary, (priority, uid))
        if portfolio:
            heappush(secondary, (alt, uid))
        peak_open = max(peak_open, len(primary)+len(secondary))
        return timeout()

    if initial_path is not None:
        replay = score(initial_path)
        accept(initial_path, replay, "initial_path")
        archive_add(initial_path, replay)
    reason = enqueue((start,), belief0, 0.)
    while live and reason is None:
        if timeout():
            reason = "max_seconds"
            break
        use_secondary = portfolio and (stats["popped"]+1) % 8 == 0
        heap = secondary if use_secondary else primary
        while heap and heap[0][1] not in live:
            heappop(heap)
            stats["stale_entries"] += 1
        if not heap:
            raise AssertionError("live node missing from ordering queue")
        _, uid = heappop(heap)
        path, belief, g = live.pop(uid)
        depth = len(path)-1
        stats["popped"] += 1
        stats["secondary_pops"] += int(use_secondary)
        tic = perf_counter()
        if cascade and g+cheap(path[-1], depth, belief) >= incumbent+ATOL:
            h = cheap(path[-1], depth, belief)
        elif bound_mode == "lookahead" and budget-depth <= lookahead_horizon:
            left = None if max_expansions is None else max(0, max_expansions-expanded-stats["aux_expanded"])
            ev = bound.evaluate(path[-1], depth, belief, cutoff=incumbent+ATOL-g,
                                deadline=deadline, max_aux_expansions=left)
            h = ev.value
            stats["aux_expanded"] += ev.aux_expanded
            stats["aux_generated"] += ev.aux_generated
            if ev.status == "interrupted":
                reason = "max_seconds" if ev.stop_reason == "max_seconds" else "max_expansions"
        else:
            h = (base_bound if bound_mode == "lookahead" else bound)(path[-1], depth, belief)
        stats["bound_calls"] += 1
        stats["bound_wall_s"] += perf_counter()-tic
        if np.isnan(h) or h < -ATOL:
            raise ValueError("invalid bound")
        reason = reason or timeout()
        if reason:
            break
        if g+h >= incumbent+ATOL:
            pruned += 1
            stats["bound_pruned"] += 1
            continue
        if max_expansions is not None and expanded+stats["aux_expanded"] >= max_expansions:
            reason = "max_expansions"
            break
        expanded += 1
        prior = motion.propagate(belief, step=depth+1)
        for vertex in grid.neighbors(path[-1]):
            child = motion.sense(prior, vertex, sensor, depth+1)
            reason = enqueue(path+(vertex,), child, g+float(child.sum()))
            if reason:
                break
    if best is None and reason is None:
        raise ValueError("no feasible path")
    if best is not None:
        replay = score(best)
        if abs(replay.J-incumbent)>ATOL or abs(replay.pd_final-incumbent_pd)>ATOL:
            raise AssertionError("final original replay mismatch")
    reason = reason or timeout()
    wall = perf_counter()-started
    stats.update(work_expanded=expanded+stats["aux_expanded"], frontier_remaining=len(live),
                 physical_frontier_remaining=len(primary)+len(secondary),
                 deadline_overshoot_s=max(0., started+wall-deadline),
                 fast_guide=fast_guide, portfolio=portfolio, cascade=cascade)
    if bound_mode == "lookahead":
        stats["lookahead"] = dict(bound.stats)
    return ResearchResult(path=best, J=None if best is None else incumbent, Pd=incumbent_pd,
                          expanded=expanded, generated=generated, pruned=pruned, peak_open=peak_open,
                          status="budget_exceeded" if reason else "completed", stop_reason=reason,
                          incumbent_source=source, guide_weight=guide_weight, bound_mode=bound_mode,
                          incumbent_history=history, stats=stats, wall_s=wall,
                          completion_reason=None if reason else "frontier_exhausted_at_tolerance",
                          candidate_archive=archive)
