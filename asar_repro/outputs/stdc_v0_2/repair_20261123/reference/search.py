"""A^SAR search over distinct path states, ordered by g + epsilon * h."""

from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from math import inf, isfinite
from time import perf_counter

import numpy as np

from .belief import initial_belief, sensor_probabilities
from .grid import GridGraph, integer
from .heuristic import BOUND_MODES, Heuristic
from .motion import MatrixMotion, ParticleMotion
from .objective import score_path


@dataclass(slots=True)
class _Node:
    vertex: int
    depth: int
    belief: np.ndarray
    g: float
    parent: "_Node | None"


@dataclass
class SearchResult:
    path: tuple[int, ...] | None
    J: float | None
    expanded: int
    generated: int
    pruned: int
    peak_open: int
    heuristic_mode: str
    epsilon: float
    theory_certified: bool   # Conditional on the documented discrete-model assumptions
    status: str = "completed"
    stop_reason: str | None = None
    incumbent_source: str | None = None


def search_zero(grid: GridGraph, *, start: int, budget: int, p, q,
                motion: MatrixMotion, prune: bool = False) -> SearchResult:
    """Use uniform-cost search, optionally pruning against a queued complete path."""
    return search_asar(grid, start=start, budget=budget, p=p, q=q, motion=motion,
                       heuristic="zero", epsilon=1.0, prune=prune)


def search_asar(grid: GridGraph, *, start: int, budget: int, p, q,
                motion: MatrixMotion | ParticleMotion, heuristic: str = "zero", epsilon: float = 1.0,
                prune: bool = True, trace=None, max_expansions=None, max_seconds=None,
                max_open=None, initial_path=None) -> SearchResult:
    """Algorithm 1. p is cell mass for matrices, ID-column weights for particles.

    initial_path is replayed before search as a feasible upper bound. Limits
    are optional; wall time is checked cooperatively at node/heuristic boundaries.
    A budget stop with no complete solution returns path=None and J=None.
    """
    started = perf_counter()
    if max_expansions is not None:
        integer(max_expansions, "max_expansions")
    if max_open is not None:
        integer(max_open, "max_open")
    if max_seconds is not None and (not isfinite(max_seconds) or max_seconds < 0):
        raise ValueError("max_seconds must be finite and nonnegative")
    deadline = inf if max_seconds is None else started + max_seconds
    grid.coordinates(start)
    budget = integer(budget, "budget")
    if not isfinite(epsilon) or epsilon < 1:
        raise ValueError("epsilon must be finite and >= 1")
    estimate = Heuristic(grid, budget=budget, q=q, motion=motion, mode=heuristic)
    root = _Node(start, 0, initial_belief(p, motion.state_size), 0.0, None)
    sensor = sensor_probabilities(q, grid.size)
    sequence = count()
    queue = []
    expanded = generated = pruned = 0
    peak_open = 0
    incumbent = inf
    best_goal = None
    if initial_path is not None:
        initial_path = tuple(initial_path)
        incumbent = score_path(grid, initial_path, start=start, budget=budget,
                               p=p, q=q, motion=motion).J

    def finish(reason=None):
        path = initial_path
        source = "initial_path" if path is not None else None
        if best_goal is not None:
            ancestor = best_goal
            vertices = []
            while ancestor is not None:
                vertices.append(ancestor.vertex)
                ancestor = ancestor.parent
            path = tuple(reversed(vertices))
            source = "search"
        return SearchResult(path, incumbent if path is not None else None, expanded, generated,
                            pruned, peak_open, heuristic, epsilon,
                            reason is None and heuristic in BOUND_MODES,
                            "budget_exceeded" if reason else "completed", reason, source)

    def record(event, node, h, f):
        if trace is not None:
            trace(dict(event=event, vertex=node.vertex, depth=node.depth, g=node.g,
                       h=h, f_weighted=f))

    def enqueue(node):
        nonlocal incumbent, best_goal, pruned, peak_open
        if node.depth == budget and node.g < incumbent:
            # Preserve a newly generated full solution even if it cannot be queued.
            incumbent, best_goal = node.g, node
        if perf_counter() >= deadline:
            return "max_seconds"
        h = estimate(node.vertex, node.depth, node.belief)
        f = node.g + epsilon * h
        if not isfinite(f):
            raise ValueError("weighted evaluation overflow; use a smaller epsilon")
        if perf_counter() >= deadline:
            return "max_seconds"
        if prune and f >= incumbent and node is not best_goal:
            pruned += 1
            record("prune", node, h, f)
            return
        if max_open is not None and len(queue) >= max_open:
            return "max_open"
        heappush(queue, (f, next(sequence), h, node))
        peak_open = max(peak_open, len(queue))
        record("push", node, h, f)

    reason = enqueue(root)
    if reason:
        return finish(reason)

    while queue:
        if perf_counter() >= deadline:
            return finish("max_seconds")
        f, _, h, node = heappop(queue)
        record("pop", node, h, f)
        if node.depth == budget:
            return finish()

        if max_expansions is not None and expanded >= max_expansions:
            return finish("max_expansions")
        expanded += 1
        depth = node.depth + 1
        prior = motion.propagate(node.belief, step=depth)
        for vertex in grid.neighbors(node.vertex):
            generated += 1
            belief = motion.sense(prior, vertex, sensor, depth)
            g = node.g + float(belief.sum())
            child = _Node(vertex, depth, belief, g, node)
            reason = enqueue(child)
            if reason:
                return finish(reason)

    if initial_path is not None:
        return finish()
    raise ValueError("no feasible path of the requested length")
