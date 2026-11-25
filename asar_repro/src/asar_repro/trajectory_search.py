"""Particle-DP bound controls with the frozen single-heap research ordering.

Paper greedy values only order nodes. The three pruning controls use STDC,
independent-particle legal-path DP, or their maximum. Complete routes always
replay the unchanged objective, and histories are never merged by location.
"""

from heapq import heappop, heappush
from itertools import count
from math import inf, isfinite
from time import perf_counter

import numpy as np

from .anytime_search import ATOL
from .belief import initial_belief, sensor_probabilities
from .grid import integer
from .heuristic import Heuristic
from .objective import score_path
from .particle_dp import ParticleDP
from .research_particle import FutureEquivalentMotion, ParticleGuide
from .research_search import ResearchResult


def search_trajectory(grid, *, start, budget, p, q, motion, initial_path=None,
                      guide_weight=1.04, bound_mode="stdc_dp", dp=None,
                      fast_guide=True, archive_candidates=True,
                      max_expansions=None, max_seconds=None, max_open=None,
                      replay_cfg=None):
    """Run a single heap with globally paid DP construction when dp is absent.

    A prebuilt DP is permitted only after compatibility/ready checks. Its
    caller must count construction in the common invocation wall/memory scope
    and pass the remaining ``max_seconds``; this function explicitly labels
    the external preprocessing instead of treating it as measured local work.
    An interrupted automatic construction preserves a replayed initial route.
    """
    started = perf_counter()
    budget = integer(budget, "budget")
    grid.coordinates(start)
    if bound_mode not in ("stdc_lb", "dp_only", "stdc_dp"):
        raise ValueError("unsupported trajectory bound")
    if not isfinite(guide_weight) or guide_weight < 1:
        raise ValueError("guide weight must be finite and >=1")
    for key, value in (("max_expansions", max_expansions), ("max_open", max_open)):
        if value is not None:
            integer(value, key)
    if max_seconds is not None and (not isfinite(max_seconds) or max_seconds < 0):
        raise ValueError("invalid time budget")
    deadline = inf if max_seconds is None else started + max_seconds
    needs_dp = bound_mode != "stdc_lb"
    supplied_dp = dp is not None
    if supplied_dp:
        if not needs_dp or not isinstance(dp, ParticleDP):
            raise ValueError("prebuilt dp requires a DP bound and ParticleDP instance")
        dp.validate_compatibility(grid, budget=budget, q=q, motion=motion)
        if not dp.ready:
            raise ValueError("prebuilt ParticleDP must be ready")
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
    stdc = (Heuristic(grid, budget=budget, q=q, motion=motion, mode="stdc_lb")
            if bound_mode != "dp_only" else None)
    primary, live, sequence = [], {}, count()
    history, archive = [], []
    expanded = generated = pruned = peak_open = 0
    incumbent, incumbent_pd, best, source = inf, None, None, None
    stats = dict(guide_calls=0, guide_wall_s=0., bound_calls=0, bound_wall_s=0.,
                 aux_expanded=0, aux_generated=0, work_expanded=0,
                 complete_candidates=0, candidate_replays=0, candidate_replay_wall_s=0.,
                 accepted_improvements=0, bound_pruned=0, cheap_pruned=0, popped=0,
                 secondary_pops=0, secondary_guide_wall_s=0., stale_entries=0,
                 guide_used_for_pruning=False, guide_used_for_termination=False,
                 state_merging=False, bound_is_unweighted=True,
                 dp_prebuilt=supplied_dp, dp_build_wall_s=0., dp_calls=0, dp_wall_s=0.,
                 stdc_calls=0, stdc_wall_s=0.,
                 preprocessing_scope=("external invocation must include prebuilt DP time/memory"
                                      if supplied_dp else "automatic DP construction inside local deadline"),
                 candidate_archive_scope="nondominated replayed encountered candidates, not global Pareto frontier")

    def timeout():
        return "max_seconds" if perf_counter() >= deadline else None

    def score(route):
        return score_path(grid, route, **scoring)

    def accept(route, replay, origin):
        nonlocal incumbent, incumbent_pd, best, source
        incumbent, incumbent_pd, best, source = replay.J, replay.pd_final, tuple(route), origin
        history.append(dict(path=best, J=incumbent, Pd=incumbent_pd, expanded=expanded,
                            work_expanded=expanded, generated=generated,
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
        if timeout():
            return "max_seconds"
        if max_open is not None and len(primary)+1 > max_open:
            return "max_open"
        uid = next(sequence)
        live[uid] = (path, belief, g)
        heappush(primary, (priority, uid))
        peak_open = max(peak_open, len(primary))
        return timeout()

    if initial_path is not None:
        replay = score(initial_path)
        accept(initial_path, replay, "initial_path")
        archive_add(initial_path, replay)
    reason = None
    if needs_dp and dp is None and budget > 0:
        reason = timeout()
        if reason is None:
            tic = perf_counter()
            dp = ParticleDP(grid, budget=budget, q=q, motion=motion, deadline=deadline)
            stats["dp_build_wall_s"] = perf_counter()-tic
            if not dp.ready:
                reason = dp.stop_reason or "dp_preprocessing_incomplete"
    if dp is not None:
        stats["dp_build"] = dict(dp.build_info)
        stats["dp_ready"] = bool(dp.ready)
    else:
        stats["dp_ready"] = False
    reason = reason or enqueue((start,), belief0, 0.)
    while live and reason is None:
        if timeout():
            reason = "max_seconds"
            break
        _, uid = heappop(primary)
        path, belief, g = live.pop(uid)
        depth = len(path)-1
        stats["popped"] += 1
        tic = perf_counter()
        h = 0.0
        if stdc is not None:
            call_started = perf_counter()
            h = stdc(path[-1], depth, belief)
            stats["stdc_calls"] += 1
            stats["stdc_wall_s"] += perf_counter()-call_started
        if needs_dp:
            call_started = perf_counter()
            particle_h = dp(path[-1], depth, belief)
            if np.isnan(particle_h) or particle_h < -ATOL:
                raise ValueError("invalid particle DP bound")
            h = max(h, particle_h)
            stats["dp_calls"] += 1
            stats["dp_wall_s"] += perf_counter()-call_started
        stats["bound_calls"] += 1
        stats["bound_wall_s"] += perf_counter()-tic
        if np.isnan(h) or h < -ATOL:
            raise ValueError("invalid bound")
        reason = timeout()
        if reason:
            break
        if g+h >= incumbent+ATOL:
            pruned += 1
            stats["bound_pruned"] += 1
            continue
        if max_expansions is not None and expanded >= max_expansions:
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
    stats.update(work_expanded=expanded, frontier_remaining=len(live),
                 physical_frontier_remaining=len(primary),
                 deadline_overshoot_s=max(0., started+wall-deadline),
                 fast_guide=fast_guide, portfolio=False, cascade=False)
    return ResearchResult(path=best, J=None if best is None else incumbent, Pd=incumbent_pd,
        expanded=expanded, generated=generated, pruned=pruned, peak_open=peak_open,
        status="budget_exceeded" if reason else "completed", stop_reason=reason,
        incumbent_source=source, guide_weight=guide_weight, bound_mode=bound_mode,
        incumbent_history=history, stats=stats, wall_s=wall,
        completion_reason=None if reason else "frontier_exhausted_at_tolerance",
        candidate_archive=archive)
