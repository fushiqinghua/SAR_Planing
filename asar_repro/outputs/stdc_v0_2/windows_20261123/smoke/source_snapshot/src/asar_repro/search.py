"""A^SAR search over distinct path states, ordered by g + epsilon * h."""

from dataclasses import dataclass
from collections import OrderedDict
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
    state_key: tuple | None = None


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
                max_open=None, initial_path=None, exact_dominance: bool = False,
                heuristic_cache_size: int = 0, reuse_stats: dict | None = None) -> SearchResult:
    """Algorithm 1. p is cell mass for matrices, ID-column weights for particles.

    initial_path is replayed before search as a feasible upper bound. Limits
    are optional; wall time is checked cooperatively at node/heuristic boundaries.
    A budget stop with no complete solution returns path=None and J=None.

    Research optimizations are opt-in. The exact state identity includes depth,
    vertex and every belief byte; motion, sensor and horizon are fixed for this
    search. An equal state with no smaller g is dominated, regardless of h or
    epsilon. A smaller g reopens the state; previously queued larger-g copies
    become stale. No tolerance or hash-only identity is used. The optional LRU
    caches h only, not g, and is bounded by heuristic_cache_size entries.

    reuse_stats receives counters without changing SearchResult. The dominance
    table retains one g per encountered exact state (its size is reported).
    OPEN limits count physical heap entries, including not-yet-popped stale
    entries; stale pops consume time but not an expansion. Trace callbacks in
    this opt-in mode may see dominance_prune (h/f are None) and stale events.
    """
    started = perf_counter()
    if not isinstance(exact_dominance, bool):
        raise ValueError("exact_dominance must be a bool")
    heuristic_cache_size = integer(heuristic_cache_size, "heuristic_cache_size")
    if reuse_stats is not None and not isinstance(reuse_stats, dict):
        raise ValueError("reuse_stats must be a dict or None")
    stats = dict(heuristic_requests=0, heuristic_evaluations=0,
                 heuristic_cache_hits=0, heuristic_cache_misses=0,
                 heuristic_cache_evictions=0, heuristic_cache_peak_entries=0,
                 heuristic_cache_key_bytes=0, heuristic_cache_peak_key_bytes=0,
                 dominance_key_bytes=0,
                 dominance_pruned=0, stale_pops=0, improved_state_records=0)
    collect_stats = reuse_stats is not None
    best_g = {} if exact_dominance else None
    h_cache = OrderedDict() if heuristic_cache_size else None
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
        if collect_stats:
            reuse_stats.update(stats, heuristic_cache_entries=len(h_cache) if h_cache is not None else 0,
                               state_records=len(best_g) if best_g is not None else 0,
                               state_records_peak=len(best_g) if best_g is not None else 0,
                               key_byte_scope="belief payload bytes in each table; excludes Python/heap overhead and shared references",
                               exact_dominance=exact_dominance,
                               heuristic_cache_size=heuristic_cache_size)
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
        if exact_dominance or h_cache is not None:
            node.state_key = (node.depth, node.vertex, node.belief.dtype.str,
                              node.belief.shape, node.belief.tobytes(order="C"))
        if exact_dominance:
            previous_g = best_g.get(node.state_key)
            if previous_g is not None and previous_g <= node.g:
                pruned += 1
                if collect_stats:
                    stats['dominance_pruned'] += 1
                record("dominance_prune", node, None, None)
                return
            if previous_g is not None and collect_stats:
                stats['improved_state_records'] += 1
            if previous_g is None and collect_stats:
                stats['dominance_key_bytes'] += len(node.state_key[-1])
            best_g[node.state_key] = node.g
        if collect_stats:
            stats['heuristic_requests'] += 1
        if h_cache is not None and node.state_key in h_cache:
            h = h_cache.pop(node.state_key)
            h_cache[node.state_key] = h
            if collect_stats:
                stats['heuristic_cache_hits'] += 1
        else:
            h = estimate(node.vertex, node.depth, node.belief)
            if collect_stats:
                stats['heuristic_evaluations'] += 1
            if h_cache is not None:
                h_cache[node.state_key] = h
                if collect_stats:
                    stats['heuristic_cache_misses'] += 1
                    stats['heuristic_cache_key_bytes'] += len(node.state_key[-1])
                if len(h_cache) > heuristic_cache_size:
                    evicted_key, _ = h_cache.popitem(last=False)
                    if collect_stats:
                        stats['heuristic_cache_evictions'] += 1
                        stats['heuristic_cache_key_bytes'] -= len(evicted_key[-1])
                if collect_stats:
                    stats['heuristic_cache_peak_entries'] = max(
                        stats['heuristic_cache_peak_entries'], len(h_cache))
                    stats['heuristic_cache_peak_key_bytes'] = max(
                        stats['heuristic_cache_peak_key_bytes'], stats['heuristic_cache_key_bytes'])
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
        if not exact_dominance:
            # An LRU eviction must also release its key payload when caching is
            # the only enabled optimization; the heap does not need that key.
            node.state_key = None
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
        if exact_dominance and node.g > best_g[node.state_key]:
            if collect_stats:
                stats['stale_pops'] += 1
            record("stale", node, h, f)
            continue
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
