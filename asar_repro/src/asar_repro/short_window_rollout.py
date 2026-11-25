"""Resumable short-window proposals with exact fixed-suffix replay.

The linear no-detection score only orders proposals. Safe pruning uses the
existing window bounds. Quality slots are retained before any optional extra
diversity slots. Completion concerns this finite beam schedule, never a global
optimum. Original planners, objective, motion archives and scorer are unchanged.
"""
from dataclasses import dataclass, field
from math import inf, isfinite
from time import perf_counter

import numpy as np

from .belief import sensor_probabilities
from .grid import integer
from .motion import MatrixMotion, ParticleMotion
from .objective import score_path
from .research_particle import FutureEquivalentMotion
from .window_bounds import WindowHeuristic, suffix_coefficients

ATOL = 1e-10


@dataclass
class BurstResult:
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
    theory_certified: bool = False
    stats: dict = field(default_factory=dict)
    incumbent_history: list = field(default_factory=list)
    wall_s: float = 0.0
    completion_reason: str | None = None


@dataclass
class _Node:
    path: tuple
    belief: np.ndarray
    g: float
    priority: float
    sequence: int
    lower: float | None = None


class BurstRollout:
    """A local proposal session; all times and depths remain absolute.

    advance() accepts a *new* expansion quota and an absolute deadline. Pending
    layers and cached full bounds survive a slice stop. max_open counts every
    retained frontier and next-layer state, and can change between slices.
    The caller must subtract this frontier from any concurrent global queue.
    """
    def __init__(self, grid, *, start, budget, p, q, motion, initial_path,
                 quality_width=24, diversity_slots=0, lazy_bound=True,
                 window_lengths=(4, 6, 8), windows=None, replay_cfg=None, trace=None):
        self.started = perf_counter()
        self.grid, self.motion = grid, motion
        self.budget = integer(budget, "budget")
        self.quality_width = integer(quality_width, "quality_width", 1)
        self.diversity_slots = integer(diversity_slots, "diversity_slots")
        if not isinstance(lazy_bound, bool):
            raise ValueError("lazy_bound must be bool")
        self.lazy_bound, self.trace = lazy_bound, trace
        self.lengths = tuple(integer(x, "window length", 1) for x in window_lengths)
        if not self.lengths or len(set(self.lengths)) != len(self.lengths):
            raise ValueError("window_lengths must be nonempty and unique")
        self.explicit_windows = None
        if windows is not None:
            self.explicit_windows = tuple((integer(a, "a"), integer(b, "b")) for a, b in windows)
            if not self.explicit_windows or any(not 0 <= a < b <= budget for a, b in self.explicit_windows):
                raise ValueError("windows must satisfy 0 <= a < b <= T")
        if not isinstance(motion, (ParticleMotion, MatrixMotion)):
            raise ValueError("unsupported motion")
        self.cfg = dict(start=start, budget=budget, p=p, q=q, motion=motion)
        self.sensor = sensor_probabilities(q, grid.size)
        if replay_cfg is not None:
            if (not isinstance(motion, FutureEquivalentMotion)
                    or replay_cfg.get("motion") is not motion.original_motion
                    or replay_cfg.get("start") != start or replay_cfg.get("budget") != budget
                    or not np.array_equal(replay_cfg.get("p"), motion.original_initial_weights)
                    or not np.array_equal(p, motion.initial_weights)
                    or not np.array_equal(sensor_probabilities(replay_cfg.get("q"), grid.size), self.sensor)):
                raise ValueError("alternate replay requires exact original compressed model")
        elif isinstance(motion, FutureEquivalentMotion):
            raise ValueError("compressed proposals require original replay model")
        self.scoring = self.cfg if replay_cfg is None else replay_cfg
        self.expanded = self.generated = self.pruned = self.peak_open = self._sequence = 0
        self.stats = dict(work_expanded=0, complete_candidates=0, candidate_replays=0,
            accepted_improvements=0, bound_calls=0, bound_wall_s=0., cheap_bound_calls=0,
            linear_guide_calls=0, linear_guide_wall_s=0., replay_wall_s=0.,
            beam_discarded=0, unqueried_bound_discarded=0, diversity_extra_retained=0,
            external_updates=0, proposal_resets=0, reset_discarded=0,
            windows_started=0, windows_completed=0, state_merging=False,
            guide_used_for_pruning=False, guide_used_for_termination=False,
            bound_is_unweighted=True, theory_certified=False, quality_width=self.quality_width,
            diversity_slots=self.diversity_slots, lazy_bound=lazy_bound,
            guide="no sensing until fixed window endpoint, then exact incumbent suffix; ordering only",
            schedule="positive immediate missed detection gain weighted by remaining time",
            completion_scope="scheduled finite window beams only; not global search")
        self.history = []
        self.task = None
        self._scheduled = None
        self._reset_pending = False
        self.path = tuple(initial_path)
        self.score = self._replay(self.path)
        self.source = "initial_path"
        self._remember()

    def _replay(self, path, *, model=False, beliefs=False):
        tic = perf_counter()
        result = score_path(self.grid, path, **(self.cfg if model else self.scoring), record_beliefs=beliefs)
        self.stats["replay_wall_s"] += perf_counter()-tic
        return result

    def _remember(self):
        self.history.append(dict(path=self.path, J=self.score.J, Pd=self.score.pd_final,
            source=self.source, expanded=self.expanded, work_expanded=self.expanded,
            elapsed_s=perf_counter()-self.started))

    @property
    def frontier_count(self):
        return 0 if self.task is None else len(self.task["frontier"])+len(self.task["next"])

    @property
    def done(self):
        return self._scheduled == [] and self.task is None

    def _emit(self, event, **values):
        if self.trace is not None:
            self.trace(dict(event=event, **values))

    def _reset(self):
        self.stats["reset_discarded"] += self.frontier_count
        self.stats["proposal_resets"] += 1
        self.task, self._scheduled = None, None
        self._reset_pending = False

    def set_incumbent(self, path):
        """Replay a supplied route; replace only for a strict original-J gain."""
        path = tuple(path)
        if path == self.path:
            return False
        score = self._replay(path)
        if score.J >= self.score.J-ATOL:
            return False
        self.path, self.score, self.source = path, score, "external_incumbent"
        self.stats["external_updates"] += 1
        self._remember()
        self._reset()
        return True

    def _prepare_schedule(self):
        self._model_score = self._replay(self.path, model=True, beliefs=True)
        if abs(self._model_score.J-self.score.J)>ATOL or abs(self._model_score.pd_final-self.score.pd_final)>ATOL:
            raise AssertionError("compressed incumbent replay mismatch")
        self._coeff = suffix_coefficients(self.grid, self.path, q=self.cfg["q"], motion=self.motion)
        if self.explicit_windows is not None:
            self._scheduled = list(self.explicit_windows)
            return
        gains = np.zeros(self.budget)
        for a in range(self.budget):
            moved = self.motion.propagate(self._model_score.beliefs[a], step=a+1)
            mu = self.motion.cell_mass(moved, a+1)
            best = max((self.sensor[v]*mu[v] for v in self.grid.neighbors(self.path[a])), default=0.)
            gains[a] = max(0., best-float(self._model_score.delta_pd[a]))*(self.budget-a)
        lengths = sorted(set(min(x, self.budget) for x in self.lengths)) if self.budget else []
        options = [(a, a+length) for length in lengths for a in range(self.budget-length+1)]
        self._scheduled = sorted(options, key=lambda ab: (-float(gains[ab[0]:ab[1]].sum()), ab[0], ab[1]))
        self._emit("window_schedule", windows=list(self._scheduled), opportunity=gains.tolist())

    def _start_window(self):
        a, b = self._scheduled.pop(0)
        tail = self._coeff.cost[b]
        full = WindowHeuristic(self.grid, end_vertex=self.path[b], end_depth=b,
            q=self.cfg["q"], motion=self.motion, tail_cost=tail, mode="stdc_endpoint_lb")
        cheap = WindowHeuristic(self.grid, end_vertex=self.path[b], end_depth=b,
            q=self.cfg["q"], motion=self.motion, tail_cost=tail, mode="mass_lb")
        # No-observation window cost, then the *fixed* suffix. It is an ordering
        # score, never an admissible bound and never a candidate score.
        linear = {b: tail}
        for t in range(b, a, -1):
            nxt = 1.0+linear[t]
            if isinstance(self.motion, MatrixMotion):
                P = self.motion._matrices[0 if self.motion._repeat else t-1]
                nxt = np.asarray(P @ nxt).ravel()
            linear[t-1] = nxt
        belief = self._model_score.beliefs[a].copy()
        g = float(self._model_score.g[a])
        root = _Node(self.path[:a+1], belief, g, g+float(linear[a]@belief), self._sequence)
        self._sequence += 1
        self.task = dict(a=a, b=b, original=self.path, coeff=self._coeff,
            full=full, cheap=cheap, linear=linear, frontier=[root], next=[])
        self.stats["windows_started"] += 1
        self._emit("window_start", a=a, b=b, incumbent_J=self.score.J)

    def _bound(self, node):
        if node.lower is None:
            tic = perf_counter()
            h = float(self.task["full"](node.path[-1], len(node.path)-1, node.belief))
            self.stats["bound_calls"] += 1
            self.stats["bound_wall_s"] += perf_counter()-tic
            if not isfinite(h) or h < -ATOL:
                raise AssertionError("invalid window lower bound")
            node.lower = node.g+h
        return node.lower

    def _signature(self, node):
        # Residual searchable *spatial* mass, not a particle/trajectory ID.
        d = len(node.path)-1
        mu = self.motion.cell_mass(node.belief, d)[:self.grid.size]
        if not np.any(mu*self.sensor):
            return (-1, -1)
        cell = int(np.argmax(mu*self.sensor))
        r, c = self.grid.coordinates(cell)
        prev = node.path[-2] if len(node.path)>1 else node.path[-1]
        pr, pc = self.grid.coordinates(prev)
        nr, nc = self.grid.coordinates(node.path[-1])
        return (r//3, c//3, nr-pr, nc-pc)

    def _select(self, deadline):
        candidates = sorted(self.task["next"], key=lambda n: (n.priority,n.sequence))
        if not self.lazy_bound:
            for n in candidates:
                if perf_counter()>=deadline:
                    return False
                self._bound(n)
        selected, quality, rejected, seen = [], [], set(), set()
        for n in candidates:
            if len(quality)==self.quality_width:
                break
            if perf_counter()>=deadline:
                return False
            if self._bound(n)>=self.score.J+ATOL:
                rejected.add(n.sequence)
                continue
            quality.append(n)
        selected.extend(quality)
        ids = {n.sequence for n in quality}
        if self.diversity_slots:
            seen = {self._signature(n) for n in quality}
            for n in candidates:
                if len(selected)>=len(quality)+self.diversity_slots:
                    break
                if n.sequence in ids or n.sequence in rejected:
                    continue
                if perf_counter()>=deadline:
                    return False
                signature = self._signature(n)
                if signature in seen:
                    continue
                if self._bound(n)>=self.score.J+ATOL:
                    rejected.add(n.sequence)
                    continue
                selected.append(n)
                ids.add(n.sequence)
                seen.add(signature)
        discarded = [n for n in candidates if n.sequence not in ids and n.sequence not in rejected]
        self.pruned += len(rejected)
        self.stats["beam_discarded"] += len(discarded)
        self.stats["unqueried_bound_discarded"] += sum(n.lower is None for n in discarded)
        self.stats["diversity_extra_retained"] += len(selected)-len(quality)
        self._emit("beam_select", a=self.task["a"], b=self.task["b"],
            quality_paths=[n.path for n in quality], retained_paths=[n.path for n in selected],
            discarded_paths=[n.path for n in discarded], bound_pruned=len(rejected))
        self.task["frontier"] = sorted(selected, key=lambda n:(n.priority,n.sequence))
        self.task["next"] = []
        return True

    def _candidate(self, route, belief, g):
        task = self.task
        b = task["b"]
        self.stats["complete_candidates"] += 1
        predicted_j = g+float(task["coeff"].cost[b]@belief)
        predicted_pd = 1.0-float(task["coeff"].survival[b]@belief)
        if predicted_j<self.score.J+ATOL:
            complete = route+task["original"][b+1:]
            candidate = self._replay(complete)
            self.stats["candidate_replays"] += 1
            if abs(candidate.J-predicted_j)>ATOL or abs(candidate.pd_final-predicted_pd)>ATOL:
                raise AssertionError("exact fixed-suffix score disagrees with independent replay")
            if candidate.J<self.score.J-ATOL:
                self.path,self.score,self.source = complete,candidate,"short_window_rollout"
                self.stats["accepted_improvements"] += 1
                self._remember()
                self._reset_pending = True

    def advance(self, *, max_expansions=None, deadline=inf, max_open=None):
        if max_expansions is not None:
            integer(max_expansions,"max_expansions")
        if max_open is not None:
            integer(max_open,"max_open")
        if not isinstance(deadline,(int,float)) or np.isnan(deadline):
            raise ValueError("deadline must be an absolute number")
        cap = inf if max_expansions is None else self.expanded+max_expansions
        advance_peak = self.frontier_count
        reason = None
        while True:
            if max_open is not None and self.frontier_count>max_open:
                reason="max_open";break
            if self.done:
                break
            if perf_counter()>=deadline:
                reason="slice_time";break
            if self.expanded>=cap:
                reason="slice_expansions";break
            if self._scheduled is None:
                self._prepare_schedule()
                continue
            if self.task is None:
                if not self._scheduled:
                    break
                if max_open==0:
                    reason="max_open";break
                self._start_window()
                advance_peak=max(advance_peak,self.frontier_count)
                continue
            if not self.task["frontier"]:
                if self.task["next"]:
                    if not self._select(deadline):
                        reason="slice_time";break
                    if self.task["frontier"]:
                        continue
                self.task=None
                self.stats["windows_completed"]+=1
                continue
            node=self.task["frontier"][0]
            if node.lower is not None and node.lower>=self.score.J+ATOL:
                self.task["frontier"].pop(0);self.pruned+=1
                continue
            t=len(node.path)
            legal=[v for v in self.grid.neighbors(node.path[-1]) if self.task["full"]._feasible(v,self.task["b"]-t)]
            # Reserve an atomic expansion's maximum buffered children before
            # consuming its parent. No successor is lost at an OPEN stop.
            potential=0 if t==self.task["b"] else len(legal)
            if max_open is not None and self.frontier_count-1+potential>max_open:
                reason="max_open";break
            self.task["frontier"].pop(0)
            self.expanded+=1
            moved=self.motion.propagate(node.belief,step=t)
            for v in legal:
                detected=self.motion.sense(moved,v,self.sensor,step=t)
                route=node.path+(v,);g=node.g+float(detected.sum())
                self.generated+=1
                if t==self.task["b"]:
                    self._candidate(route,detected,g)
                    continue
                cheap=g+float(self.task["cheap"](v,t,detected))
                self.stats["cheap_bound_calls"]+=1
                if cheap>=self.score.J+ATOL:
                    self.pruned+=1;continue
                tic=perf_counter()
                priority=g+float(self.task["linear"][t]@detected)
                self.stats["linear_guide_calls"]+=1
                self.stats["linear_guide_wall_s"]+=perf_counter()-tic
                self.task["next"].append(_Node(route,detected,g,priority,self._sequence))
                self._sequence+=1
            advance_peak=max(advance_peak,self.frontier_count)
            if self._reset_pending:
                self._reset()
        self.peak_open=max(self.peak_open,advance_peak)
        replay=self._replay(self.path)
        if abs(replay.J-self.score.J)>ATOL or abs(replay.pd_final-self.score.pd_final)>ATOL:
            raise AssertionError("final proposal replay mismatch")
        self.stats.update(work_expanded=self.expanded,frontier_remaining=self.frontier_count,
            advance_peak_open=advance_peak,deadline_overshoot_s=max(0.,perf_counter()-deadline))
        status="completed" if self.done else "budget_exceeded" if reason=="max_open" else "paused"
        return BurstResult(self.path,self.score.J,self.score.pd_final,self.expanded,self.generated,
            self.pruned,self.peak_open,status,reason,self.source,stats=dict(self.stats),
            incumbent_history=list(self.history),wall_s=perf_counter()-self.started,
            completion_reason="scheduled_window_beams_exhausted" if self.done else None)
