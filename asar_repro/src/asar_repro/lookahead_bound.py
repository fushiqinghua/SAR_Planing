"""Budget-aware, admissible finite-prefix lifting of the existing STDC bound.

For k=min(steps, T-depth), enumerate EVERY legal k-step continuation and let
L_k be the minimum of its exact cost plus the unchanged STDC tail bound.
max(H_STDC, L_k) is admissible. Partial enumeration is never a lower bound:
an interruption discards its minimum and returns a previously completed bound.

The mass/STDC/lookahead cascade may stop when an already safe bound reaches a
caller-supplied cutoff. All auxiliary node expansions are reported separately;
the caller must charge them to its shared work ledger. No result here grants
a global epsilon certificate.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import inf, isfinite, isnan
from time import perf_counter

from .belief import sensor_probabilities, undetected_mass
from .grid import GridGraph, integer
from .heuristic import Heuristic
from .motion import MatrixMotion, ParticleMotion


@dataclass(frozen=True)
class LookaheadEvaluation:
    """A safe remaining-cost lower bound and the work used to obtain it.

    value=inf with stage='infeasible' means no legal completion; it is not an
    invalid numerical bound. lookahead_value is None unless every leaf was
    evaluated. completed enumeration does not imply exact optimality unless
    the lookahead reaches T, and never implies a full-route epsilon guarantee.
    """

    value: float
    base_value: float
    lookahead_value: float | None
    stage: str
    status: str
    stop_reason: str | None
    aux_expanded: int
    aux_generated: int
    leaf_evaluations: int
    cutoff_reached: bool
    lookahead_completed: bool
    mass_evaluations: int
    stdc_evaluations: int
    wall_s: float


class _Interrupted(Exception):
    def __init__(self, reason):
        self.reason = reason


class LookaheadBound:
    """Fixed discrete model with on-demand mass -> STDC -> exact-prefix stages.

    Motion uses absolute depth+i; graph reachability uses actual legal moves.
    Input beliefs are unnormalized undetected weights and are never modified.
    Only existing STDC geometry is cached; no belief-dependent value is cached.

    max_aux_expansions is a per-call cap supplied from the caller's remaining
    shared work budget. It counts each auxiliary internal node whose successors
    are evaluated, including the lookahead root. Terminal leaf tail-bound work
    is timed and counted separately, and is not free in the wall-time budget.
    The exact singleton/no-successor check needs no auxiliary tree expansion.
    """

    def __init__(self, grid: GridGraph, *, budget: int, q,
                 motion: MatrixMotion | ParticleMotion, steps: int = 2):
        if not isinstance(motion, (MatrixMotion, ParticleMotion)):
            raise ValueError("lookahead requires MatrixMotion or ParticleMotion")
        self.grid = grid
        self.budget = integer(budget, "budget")
        self.steps = integer(steps, "steps", minimum=1)
        if grid.size != motion.size:
            raise ValueError("motion grid size must match the search grid")
        if isinstance(motion, ParticleMotion):
            motion.check_horizon(self.budget)
        elif not motion._repeat and self.budget > len(motion._matrices):
            raise ValueError(f"missing P_t for step {self.budget}")
        self.motion = motion
        self.q = sensor_probabilities(q, grid.size).copy()
        self.q.setflags(write=False)
        self._mass = Heuristic(grid, budget=self.budget, q=self.q,
                               motion=motion, mode="mass_lb")
        self._stdc = Heuristic(grid, budget=self.budget, q=self.q,
                               motion=motion, mode="stdc_lb")
        self.stats = dict(calls=0, mass_evaluations=0, stdc_evaluations=0,
                          aux_expanded=0, aux_generated=0, leaf_evaluations=0,
                          lookahead_completed=0, lookahead_interrupted=0,
                          mass_cutoffs=0, stdc_cutoffs=0, lookahead_cutoffs=0,
                          deadline_interruptions=0, work_interruptions=0,
                          terminal_calls=0, infeasible_calls=0, wall_s=0.0)

    def evaluate(self, vertex: int, depth: int, belief, *, cutoff=inf,
                 deadline=inf, max_aux_expansions=None) -> LookaheadEvaluation:
        """Return a safe bound even when finite-prefix enumeration is interrupted.

        deadline is an absolute perf_counter timestamp, not a duration.
        cutoff is an already tolerance-adjusted remaining-cost threshold; this
        class does not add a tolerance to any mathematical lower bound.
        An expired call returns the cheap mass bound with an explicit stop.
        """
        started = perf_counter()
        self.grid.coordinates(vertex)
        vertex = int(vertex)
        depth = integer(depth, "depth")
        if depth > self.budget:
            raise ValueError("depth exceeds search budget")
        b = undetected_mass(belief, self.motion.state_size)
        cutoff, deadline = float(cutoff), float(deadline)
        if isnan(cutoff) or isnan(deadline):
            raise ValueError("cutoff and deadline must not be NaN")
        if max_aux_expansions is not None:
            max_aux_expansions = integer(max_aux_expansions, "max_aux_expansions")
        remaining = self.budget - depth
        counts = dict(aux_expanded=0, aux_generated=0, leaf_evaluations=0,
                      mass_evaluations=0, stdc_evaluations=0)
        lookahead_started = False

        def finish(value, base, *, stage, status="completed", reason=None,
                   lifted=None, complete=False):
            elapsed = perf_counter() - started
            reached = value >= cutoff
            result = LookaheadEvaluation(float(value), float(base), lifted, stage,
                status, reason, counts["aux_expanded"], counts["aux_generated"],
                counts["leaf_evaluations"], reached, complete,
                counts["mass_evaluations"], counts["stdc_evaluations"], elapsed)
            self.stats["calls"] += 1
            for key, value in counts.items():
                self.stats[key] += value
            self.stats["wall_s"] += elapsed
            if stage in ("terminal", "infeasible"):
                self.stats[stage + "_calls"] += 1
            if status == "cutoff":
                self.stats[stage + "_cutoffs"] += 1
            if complete:
                self.stats["lookahead_completed"] += 1
            if status == "interrupted":
                self.stats["lookahead_interrupted"] += int(lookahead_started)
                self.stats["deadline_interruptions" if reason == "max_seconds"
                           else "work_interruptions"] += 1
            return result

        def time_check():
            if perf_counter() >= deadline:
                raise _Interrupted("max_seconds")

        def checked_stdc(v, d, state):
            counts["stdc_evaluations"] += 1
            value = float(self._stdc(v, d, state))
            if not isfinite(value) or value < 0:
                raise ValueError("STDC returned an invalid bound on a feasible prefix")
            return value

        if remaining == 0:
            return finish(0.0, 0.0, stage="terminal")
        if not self.grid.neighbors(vertex):
            # No-wait rectangular singleton: every positive-horizon completion
            # is infeasible. Infinity is the exact remaining cost convention.
            return finish(inf, inf, stage="infeasible")
        counts["mass_evaluations"] += 1
        base = float(self._mass(vertex, depth, b))
        if not isfinite(base) or base < 0:
            raise ValueError("mass bound must be finite and nonnegative")
        stage = "mass"
        try:
            time_check()
            if base >= cutoff:
                return finish(base, base, stage=stage, status="cutoff")
            base = max(base, checked_stdc(vertex, depth, b))
            stage = "stdc"
            time_check()
            if base >= cutoff:
                return finish(base, base, stage=stage, status="cutoff")
            lookahead_started = True
            limit = min(self.steps, remaining)
            minimum = inf

            def enumerate_prefix(v, d, state, cost, steps_left):
                nonlocal minimum
                time_check()
                if steps_left == 0:
                    counts["leaf_evaluations"] += 1
                    tail = 0.0 if d == self.budget else checked_stdc(v, d, state)
                    time_check()
                    value = cost + tail
                    if not isfinite(value):
                        raise ValueError("lookahead cost overflow")
                    minimum = min(minimum, value)
                    return
                if (max_aux_expansions is not None
                        and counts["aux_expanded"] >= max_aux_expansions):
                    raise _Interrupted("max_aux_expansions")
                counts["aux_expanded"] += 1
                t = d + 1
                prior = self.motion.propagate(state, step=t)
                for nxt in self.grid.neighbors(v):
                    time_check()
                    child = self.motion.sense(prior, nxt, self.q, t)
                    counts["aux_generated"] += 1
                    enumerate_prefix(nxt, t, child, cost + float(child.sum()), steps_left - 1)

            enumerate_prefix(vertex, depth, b, 0.0, limit)
            time_check()
            value = max(base, minimum)
            return finish(value, base, stage="lookahead",
                          status="cutoff" if value >= cutoff else "completed",
                          lifted=float(minimum), complete=True)
        except _Interrupted as interrupted:
            # Deliberately discard every partially enumerated leaf/minimum.
            # The unexplored branch may be strictly cheaper than all seen ones.
            return finish(base, base, stage=stage, status="interrupted",
                          reason=interrupted.reason)
