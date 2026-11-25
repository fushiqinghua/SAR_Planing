"""Resumable opt-in STDC search with retained path-dependent frontier.

Slices do not discard popped nodes or partly generated successor lists. Paper
greedy is an ordering device only. Constructor caps are global; advance caps
are temporary slices. All complete incumbents use the unchanged scorer.
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
from .research_particle import FutureEquivalentMotion, ParticleGuide
from .research_search import ResearchResult


class SearchSession:
    """Single-heap search that can resume after independent local proposals.

    bound and cheap_bound must be model-compatible admissible lower bounds.
    The latter, when supplied, screens enqueue before the costly guide.
    No externally supplied guide is ever used for pruning or certification.
    The caller owns the shared orchestration clock and may pass its absolute
    deadline at construction. Per-advance deadlines only pause this session.
    """

    def __init__(self, grid, *, start, budget, p, q, motion, initial_path=None,
                 guide_weight=1.04, bound_mode="stdc_lb", bound=None,
                 cheap_bound=None, guide=None, fast_guide=True,
                 max_expansions=None, max_open=None, deadline=None,
                 replay_cfg=None, archive_candidates=True):
        self.started = perf_counter()
        self.grid, self.start, self.motion = grid, start, motion
        self.budget = integer(budget, "budget")
        grid.coordinates(start)
        if grid.size != motion.size:
            raise ValueError("motion grid size must match search grid size")
        if not isfinite(guide_weight) or guide_weight < 1:
            raise ValueError("guide weight must be finite and >=1")
        for name, value in (("max_expansions", max_expansions), ("max_open", max_open)):
            if value is not None:
                integer(value, name)
        if deadline is not None and (np.isnan(deadline) or deadline == -inf):
            raise ValueError("deadline must be an absolute time or positive infinity")
        if bound is None and bound_mode not in ("zero", "mass_lb", "stdc_lb"):
            raise ValueError("unsupported built-in bound")
        self.max_expansions, self.max_open = max_expansions, max_open
        self.deadline = inf if deadline is None else deadline
        self.guide_weight, self.bound_mode = guide_weight, bound_mode
        self.sensor = sensor_probabilities(q, grid.size).copy()
        self.belief0 = initial_belief(p, motion.state_size)
        self.belief0.setflags(write=False)
        cfg = dict(start=start, budget=self.budget, p=p, q=q, motion=motion)
        if replay_cfg is not None:
            if (not isinstance(motion, FutureEquivalentMotion)
                    or replay_cfg.get("motion") is not motion.original_motion
                    or replay_cfg.get("start") != start
                    or replay_cfg.get("budget") != self.budget
                    or not np.array_equal(replay_cfg.get("p"), motion.original_initial_weights)
                    or not np.array_equal(p, motion.initial_weights)
                    or not np.array_equal(sensor_probabilities(replay_cfg.get("q"), grid.size),
                                          self.sensor)):
                raise ValueError("alternate replay requires the exact original compressed model")
        self.scoring = cfg if replay_cfg is None else replay_cfg
        self.guide = guide if guide is not None else (
            ParticleGuide(grid, budget=self.budget, q=q, motion=motion) if fast_guide else
            Heuristic(grid, budget=self.budget, q=q, motion=motion, mode="paper_greedy"))
        self.bound = bound if bound is not None else Heuristic(
            grid, budget=self.budget, q=q, motion=motion, mode=bound_mode)
        self.cheap_bound = cheap_bound
        self.archive_candidates = archive_candidates
        self.primary, self.live, self.sequence = [], {}, count()
        self._root_pending = True
        self._ready = None
        self._expansion = None
        self._held = None
        self.expanded = self.generated = self.pruned = self.peak_open = 0
        self.advance_peak_open = 0
        self.path, self.J, self.Pd, self.incumbent_source = None, inf, None, None
        self.incumbent_history, self.candidate_archive = [], []
        self.status, self.stop_reason = "paused", "not_started"
        self.stats = dict(guide_calls=0, guide_wall_s=0., bound_calls=0, bound_wall_s=0.,
            cheap_bound_calls=0, cheap_bound_wall_s=0., enqueue_bound_pruned=0,
            aux_expanded=0, aux_generated=0, work_expanded=0, complete_candidates=0,
            candidate_replays=0, candidate_replay_wall_s=0., accepted_improvements=0,
            external_incumbent_replays=0, external_improvements=0,
            bound_pruned=0, cheap_pruned=0, popped=0, slice_calls=0, slice_pauses=0,
            guide_used_for_pruning=False, guide_used_for_termination=False,
            state_merging=False, bound_is_unweighted=True, fast_guide=fast_guide,
            partial_expansions_preserved=True,
            candidate_archive_scope="nondominated replayed encountered candidates, not global Pareto frontier")
        if initial_path is not None:
            replay = self._score(initial_path)
            self._accept(initial_path, replay, "initial_path")
            self._archive(initial_path, replay)

    @property
    def frontier_count(self):
        return (len(self.live) + int(self._root_pending) + int(self._ready is not None)
                + int(self._expansion is not None) + int(self._held is not None))

    def _score(self, path):
        return score_path(self.grid, path, **self.scoring)

    def _accept(self, path, replay, source):
        self.path, self.J, self.Pd = tuple(path), replay.J, replay.pd_final
        self.incumbent_source = source
        self.incumbent_history.append(dict(path=self.path, J=self.J, Pd=self.Pd,
            expanded=self.expanded, work_expanded=self.expanded, generated=self.generated,
            elapsed_s=perf_counter()-self.started, source=source))

    def _dominated(self, j, pd):
        return any(a["J"] <= j and a["Pd"] >= pd for a in self.candidate_archive)

    def _archive(self, path, replay):
        if not self.archive_candidates or self._dominated(replay.J, replay.pd_final):
            return
        self.candidate_archive[:] = [a for a in self.candidate_archive
            if not (replay.J <= a["J"] and replay.pd_final >= a["Pd"])]
        self.candidate_archive.append(dict(path=tuple(path), J=replay.J, Pd=replay.pd_final,
            elapsed_s=perf_counter()-self.started, expanded=self.expanded))

    def inject_incumbent(self, path, *, source="rollout"):
        """Replay a complete externally proposed route; retain strict J gains only."""
        tic = perf_counter()
        replay = self._score(path)
        self.stats["external_incumbent_replays"] += 1
        self.stats["candidate_replay_wall_s"] += perf_counter()-tic
        self._archive(path, replay)
        improved = replay.J < self.J-ATOL
        if improved:
            self.stats["external_improvements"] += 1
            self._accept(path, replay, source)
        return improved

    @staticmethod
    def _check_bound(h):
        if np.isnan(h) or h < -ATOL:
            raise ValueError("invalid lower bound")

    def _enqueue(self, path, belief, g):
        """Atomic child materialization; deadline checks surround this operation."""
        depth = len(path)-1
        self.generated += int(depth > 0)
        if depth == self.budget:
            self.stats["complete_candidates"] += 1
            pd = 1-float(belief.sum())
            if g < self.J+ATOL or (self.archive_candidates and not self._dominated(g, pd)):
                tic = perf_counter()
                replay = self._score(path)
                self.stats["candidate_replays"] += 1
                self.stats["candidate_replay_wall_s"] += perf_counter()-tic
                if abs(replay.J-g)>ATOL or abs(replay.pd_final-pd)>ATOL:
                    raise AssertionError("candidate original replay mismatch")
                self._archive(path, replay)
                if replay.J < self.J-ATOL:
                    self.stats["accepted_improvements"] += 1
                    self._accept(path, replay, "search")
            return None
        if g >= self.J+ATOL:
            self.stats["cheap_pruned"] += 1
            self.pruned += 1
            return None
        if self.cheap_bound is not None:
            tic = perf_counter()
            h = self.cheap_bound(path[-1], depth, belief)
            self.stats["cheap_bound_calls"] += 1
            self.stats["cheap_bound_wall_s"] += perf_counter()-tic
            self._check_bound(h)
            if g+h >= self.J+ATOL:
                self.stats["enqueue_bound_pruned"] += 1
                self.pruned += 1
                return None
        tic = perf_counter()
        h = self.guide(path[-1], depth, belief)
        self.stats["guide_calls"] += 1
        self.stats["guide_wall_s"] += perf_counter()-tic
        priority = g+self.guide_weight*h
        if not isfinite(h) or h < -ATOL or not isfinite(priority):
            raise ValueError("invalid guide")
        if self.max_open is not None and len(self.primary)+1 > self.max_open:
            # Global stop, never a silent beam drop. Retain the child and siblings.
            self._held = (path, belief, g, priority)
            return "max_open"
        uid = next(self.sequence)
        self.live[uid] = (path, belief, g)
        heappush(self.primary, (priority, uid))
        self.peak_open = max(self.peak_open, len(self.primary))
        self.advance_peak_open = max(self.advance_peak_open, len(self.primary))
        return None

    def _stop(self, status, reason):
        self.status, self.stop_reason = status, reason
        self.stats["slice_pauses"] += int(status == "paused")
        return self.finish()

    def advance(self, *, max_expansions=None, deadline=None):
        """Spend an additional work slice without discarding the global frontier."""
        if max_expansions is not None:
            integer(max_expansions, "slice max_expansions")
        if deadline is not None and (np.isnan(deadline) or deadline == -inf):
            raise ValueError("slice deadline must be an absolute time or positive infinity")
        self.advance_peak_open = len(self.primary)
        if self.status in ("completed", "budget_exceeded"):
            return self.finish()
        self.stats["slice_calls"] += 1
        begin = self.expanded
        slice_deadline = inf if deadline is None else deadline
        while True:
            now = perf_counter()
            if now >= self.deadline:
                return self._stop("budget_exceeded", "max_seconds")
            if now >= slice_deadline:
                return self._stop("paused", "slice_seconds")
            if self._root_pending:
                reason = self._enqueue((self.start,), self.belief0, 0.)
                self._root_pending = False
                if reason:
                    return self._stop("budget_exceeded", reason)
                continue
            if self._expansion is not None:
                path, prior, g, neighbors, index = self._expansion
                if index == len(neighbors):
                    self._expansion = None
                    continue
                vertex = neighbors[index]
                child = self.motion.sense(prior, vertex, self.sensor, len(path))
                child.setflags(write=False)
                reason = self._enqueue(path+(vertex,), child, g+float(child.sum()))
                self._expansion = (path, prior, g, neighbors, index+1)
                if reason:
                    return self._stop("budget_exceeded", reason)
                continue
            if self._ready is None and not self.live:
                if self.path is None:
                    raise ValueError("no feasible path")
                return self._stop("completed", None)
            if self.max_expansions is not None and self.expanded >= self.max_expansions:
                return self._stop("budget_exceeded", "max_expansions")
            if max_expansions is not None and self.expanded-begin >= max_expansions:
                return self._stop("paused", "slice_expansions")
            if self._ready is None:
                _, uid = heappop(self.primary)
                path, belief, g = self.live.pop(uid)
                self.stats["popped"] += 1
                tic = perf_counter()
                h = self.bound(path[-1], len(path)-1, belief)
                self.stats["bound_calls"] += 1
                self.stats["bound_wall_s"] += perf_counter()-tic
                self._check_bound(h)
                if g+h >= self.J+ATOL:
                    self.pruned += 1
                    self.stats["bound_pruned"] += 1
                else:
                    self._ready = (path, belief, g, h)
                continue
            path, belief, g, h = self._ready
            self._ready = None
            # An injected incumbent can prune a previously admitted node.
            if g+h >= self.J+ATOL:
                self.pruned += 1
                self.stats["bound_pruned"] += 1
                continue
            self.expanded += 1
            prior = self.motion.propagate(belief, step=len(path))
            self._expansion = (path, prior, g, self.grid.neighbors(path[-1]), 0)

    def memory_info(self):
        """Managed live belief buffers; separate from process RSS and geometry."""
        arrays = {id(self.belief0): self.belief0}
        for _, belief, _ in self.live.values():
            arrays[id(belief)] = belief
        for pending in (self._ready, self._expansion, self._held):
            if pending is not None:
                arrays[id(pending[1])] = pending[1]
        return dict(live_belief_unique_buffers=len(arrays),
                    live_belief_array_bytes=sum(a.nbytes for a in arrays.values()),
                    physical_open_entries=len(self.primary),
                    pending_expansion=bool(self._expansion),
                    pending_bound_checked_node=bool(self._ready),
                    held_open_cap_child=bool(self._held))

    def finish(self, *, stop_reason=None):
        """Replay-check a snapshot, optionally marking an orchestration-wide cap."""
        if stop_reason is not None:
            if stop_reason not in ("max_expansions", "max_seconds", "max_open"):
                raise ValueError("unsupported global stop reason")
            if self.status != "completed" and self.status != "budget_exceeded":
                self.status, self.stop_reason = "budget_exceeded", stop_reason
        if self.path is not None:
            replay = self._score(self.path)
            if abs(replay.J-self.J)>ATOL or abs(replay.pd_final-self.Pd)>ATOL:
                raise AssertionError("final original replay mismatch")
        wall = perf_counter()-self.started
        stats = dict(self.stats, work_expanded=self.expanded,
            advance_peak_open=self.advance_peak_open,
            frontier_remaining=self.frontier_count,
            physical_frontier_remaining=len(self.primary),
            deadline_overshoot_s=max(0., self.started+wall-self.deadline),
            resumable=True, memory=self.memory_info())
        return ResearchResult(path=self.path, J=None if self.path is None else self.J,
            Pd=self.Pd, expanded=self.expanded, generated=self.generated, pruned=self.pruned,
            peak_open=self.peak_open, status=self.status, stop_reason=self.stop_reason,
            incumbent_source=self.incumbent_source, guide_weight=self.guide_weight,
            bound_mode=self.bound_mode, stats=stats, wall_s=wall,
            incumbent_history=[dict(e) for e in self.incumbent_history],
            candidate_archive=[dict(a) for a in self.candidate_archive],
            completion_reason="frontier_exhausted_at_tolerance" if self.status == "completed" else None)

