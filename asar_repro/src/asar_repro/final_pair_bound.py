"""Small shared-route particle-pair diagnostics for the final STDC assessment.

This is an opt-in diagnostic, not a production-search heuristic replacement.
For a pair i,j, the real-arithmetic value is

    min_legal_suffix sum_{r=1..H} [b_i*a**n_i(r) + b_j*a**n_j(r)],

where a=1-q and both particles use the SAME suffix.  Its singleton relaxation
may use a different suffix for each particle.  All positions use absolute
ParticleMotion frames, including unchanged special-bin mass; t=0 is not sensed.

At relative time k, factor a**min(n_i,n_j) out of the remaining value and keep
delta=n_i-n_j.  The normalized pair weights are b_i*a**max(delta,0) and
b_j*a**max(-delta,0).  If the next move has hit indicators e_i,e_j, write
delta'=delta+e_i-e_j and m=min(max(delta,0)+e_i,max(-delta,0)+e_j).  The backup is

    F_k(v,delta) = min_u a**m * (normalized_mass(delta') + F_{k+1}(u,delta')).

The boundary is F_H=0, the query is F_0(vertex,0), and delta is in [-k,k].
All powers are nonnegative, so q=1 also works with 0**0=1.  Arrays roll over
time: O(|V| H**2) arithmetic and O(|V| H) managed memory for one pair.

The current b_i,b_j are part of EVERY query.  No scalar (time,vertex) cache is
reused across beliefs.  A completed exact-DP value gets a small downward
floating-point guard.  The real-arithmetic proof and finite floating-point
Oracle evidence are distinct; this module does not certify the full search.

For disjoint selected pairs, their exact group values plus STDC evaluated on
the remaining-particle group form an additive lower bound.  Taking max with
full-mass STDC is safe.  Adding a pair's gain directly to full STDC is NOT safe.
The mixed remainder-STDC construction need not dominate all-singleton DP.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import inf, isfinite
from time import perf_counter

import numpy as np

from .belief import sensor_probabilities, undetected_mass
from .grid import GridGraph, integer
from .motion import ParticleMotion
from .stdc_heuristic import STDCHeuristic


@dataclass
class PairBoundResult:
    pair: tuple[int, int]
    bound: float | None
    independent_bound: float | None
    coupling_gain: float | None
    status: str
    stop_reason: str | None
    wall_s: float
    stats: dict = field(default_factory=dict)


@dataclass
class PartitionPairBoundResult:
    bound: float | None
    grouped_bound: float | None
    full_stdc_bound: float | None
    remainder_bound: float | None
    status: str
    stop_reason: str | None
    wall_s: float
    pair_results: list[PairBoundResult] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


class _Stop(Exception):
    pass


def _validate(grid, vertex, depth, budget, q, motion, belief, max_seconds,
              max_memory_bytes):
    if not isinstance(grid, GridGraph) or not isinstance(motion, ParticleMotion):
        raise ValueError("pair diagnostics require GridGraph and ParticleMotion")
    grid.coordinates(vertex)
    vertex = int(vertex)
    depth, budget = integer(depth, "depth"), integer(budget, "budget")
    if depth > budget or motion.size != grid.size:
        raise ValueError("incompatible depth, budget or motion grid")
    motion.check_horizon(budget)
    b = undetected_mass(belief, motion.state_size)
    sensor = sensor_probabilities(q, grid.size)
    if not np.all(sensor == sensor[0]):
        raise ValueError("shared-pair relative-count DP requires uniform q")
    scalar_q = float(sensor[0])
    if max_seconds is not None and (not isfinite(max_seconds) or max_seconds < 0):
        raise ValueError("max_seconds must be finite and nonnegative")
    if max_memory_bytes is not None:
        max_memory_bytes = integer(max_memory_bytes, "max_memory_bytes")
    return vertex, depth, budget, scalar_q, b


def _pair_indices(pair, size):
    try:
        values = tuple(pair)
    except TypeError as exc:
        raise ValueError("pair must contain two different column indices") from exc
    if len(values) != 2:
        raise ValueError("pair must contain two different column indices")
    i, j = (integer(v, "particle column") for v in values)
    if i == j or max(i, j) >= size:
        raise ValueError("pair must contain two different valid particle columns")
    return i, j


def _neighbors(grid):
    vertices = np.arange(grid.size, dtype=np.intp)
    rows, cols = vertices // grid.cols, vertices % grid.cols
    raw = np.stack((vertices-grid.cols, vertices-1,
                    vertices+1, vertices+grid.cols))
    valid = np.stack((rows > 0, cols > 0,
                      cols+1 < grid.cols, rows+1 < grid.rows))
    # Invalid lookups use a finite valid array element, then are masked.  This
    # avoids 0*inf in the q=1 backup without inventing any stay edges.
    return np.where(valid, raw, 0), valid


def pair_shared_bound(grid: GridGraph, *, vertex: int, depth: int, budget: int,
                      q, motion: ParticleMotion, belief, pair,
                      max_seconds=None, max_memory_bytes=128*1024*1024):
    """Exactly solve one pair and its singleton relaxation, or publish no bound.

    `budget` is the absolute final frame, not the remaining horizon.  `pair`
    uses ParticleMotion column indices, whose stable IDs are reported in stats.
    A zero/expired time or memory budget returns budget_exceeded with bound=None.
    Memory limits cover the conservative managed-buffer reserve, not OS RSS,
    caller motion arrays, Python overhead, or external library allocations.
    """
    begun = perf_counter()
    vertex, depth, budget, q, b = _validate(
        grid, vertex, depth, budget, q, motion, belief,
        max_seconds, max_memory_bytes)
    i, j = _pair_indices(pair, motion.state_size)
    H, V = budget-depth, grid.size
    weights = np.array([b[i], b[j]], dtype=np.float64)
    mass = float(weights.sum())
    deadline = inf if max_seconds is None else begun+max_seconds
    # Two pair layers, one candidate, one minimum-result reserve, neighbor
    # maps/masks, singleton arrays and small normalized-delta vectors.
    reserve = int(4*(2*H+1)*V*8 + 4*V*9 + 6*V*8 + (16*H+64)*8)
    stats = dict(vertex=vertex, depth=depth, budget=budget, remaining_steps=H,
                 grid_vertices=V, pair_columns=[i, j],
                 trajectory_ids=[motion.trajectory_ids[i].item()
                                 if isinstance(motion.trajectory_ids[i], np.generic)
                                 else motion.trajectory_ids[i],
                                 motion.trajectory_ids[j].item()
                                 if isinstance(motion.trajectory_ids[j], np.generic)
                                 else motion.trajectory_ids[j]],
                 pair_weights=weights.tolist(), q=q,
                 estimated_peak_managed_bytes=reserve,
                 max_memory_bytes=max_memory_bytes,
                 completed_pair_layers=0, pair_state_backups=0,
                 singleton_state_backups=0, no_partial_table_published=True,
                 state="relative hit-count delta, min-count common scaling",
                 memory_scope="conservative pair-DP buffer reserve; not process RSS",
                 global_epsilon_certified=False)

    def finish(status, reason=None, raw=None, independent=None):
        wall = perf_counter()-begun
        stats["deadline_overshoot_s"] = max(0., begun+wall-deadline)
        bound = gain = independent_bound = None
        if raw is not None:
            if not isfinite(raw) or not isfinite(independent):
                raise FloatingPointError("nonfinite completed pair value")
            guard = 256*np.finfo(np.float64).eps*max(1, H)*mass
            bound = max(0., float(np.nextafter(raw-guard, -np.inf))) if raw else 0.
            independent_bound = max(0., float(np.nextafter(independent-guard, -np.inf))) if independent else 0.
            gain = float(raw-independent)
            if gain < -max(1e-10, guard):
                raise AssertionError("pair value fell below singleton relaxation")
            gain = max(0., gain)
            stats.update(raw_pair_value=float(raw), raw_independent_value=float(independent),
                         downward_guard=float(guard),
                         guard_scope="floating-point engineering guard; real-arithmetic proof is separate")
        return PairBoundResult((i, j), bound, independent_bound, gain,
                               status, reason, wall, stats)

    def time_check():
        if perf_counter() >= deadline:
            raise _Stop("max_seconds")

    try:
        time_check()
        if H == 0:
            return finish("completed", raw=0., independent=0.)
        if V == 1:
            return finish("infeasible", "no_legal_nonwaiting_suffix")
        if q == 0 or mass == 0:
            stats["analytic_shortcut"] = "zero_detection_or_zero_group_mass"
            stats["estimated_peak_managed_bytes"] = int(weights.nbytes)
            return finish("completed", raw=H*mass, independent=H*mass)
        if max_memory_bytes is not None and reserve > max_memory_bytes:
            raise _Stop("max_memory_bytes")
        neighbors, valid = _neighbors(grid)
        a = 1.-q
        # Weighted singleton values use their OWN routes.  No H-by-V-by-N
        # table is built, even when the caller's archive has 500 particles.
        singleton = np.zeros((2, V), dtype=np.float64)
        for t in range(budget-1, depth-1, -1):
            time_check()
            current = np.full_like(singleton, inf)
            cells = motion.cell_ids[t+1, [i, j]]
            for neighbor, available in zip(neighbors, valid):
                candidate = (weights[:, None]+singleton[:, neighbor])
                candidate *= 1.-q*(cells[:, None] == neighbor[None, :])
                candidate[:, ~available] = inf
                np.minimum(current, candidate, out=current)
            singleton = current
            stats["singleton_state_backups"] += 2*V
        independent = float(singleton[:, vertex].sum())
        del singleton, current, candidate
        time_check()
        powers = np.power(a, np.arange(H+1, dtype=np.intp))
        offsets = np.arange(-H, H+1, dtype=np.intp)
        normalized_mass = (weights[0]*powers[np.maximum(offsets, 0)]
                           + weights[1]*powers[np.maximum(-offsets, 0)])
        following = np.zeros((2*H+1, V), dtype=np.float64)
        for k in range(H-1, -1, -1):
            time_check()
            delta = np.arange(-k, k+1, dtype=np.intp)
            current = np.full((2*k+1, V), inf, dtype=np.float64)
            c_i, c_j = motion.cell_ids[depth+k+1, [i, j]]
            for neighbor, available in zip(neighbors, valid):
                time_check()
                # Most edges hit neither particle.  A rectangular graph has
                # at most two exceptional source columns per direction.
                candidate = following[1:-1, neighbor] + normalized_mass[delta+H, None]
                hit_columns = np.flatnonzero(available & ((neighbor == c_i) | (neighbor == c_j)))
                for col in hit_columns:
                    e_i, e_j = int(neighbor[col] == c_i), int(neighbor[col] == c_j)
                    updated_delta = delta+e_i-e_j
                    common_increment = np.minimum(np.maximum(delta, 0)+e_i,
                                                  np.maximum(-delta, 0)+e_j)
                    # common_increment is exactly 0 or 1.  np.power defines
                    # a**0=1 also when q=1 and a=0.
                    candidate[:, col] = powers[common_increment] * (
                        normalized_mass[updated_delta+H]
                        + following[updated_delta+k+1, neighbor[col]])
                candidate[:, ~available] = inf
                np.minimum(current, candidate, out=current)
            following = current
            stats["completed_pair_layers"] += 1
            stats["pair_state_backups"] += (2*k+1)*V
        time_check()
        raw = float(following[0, vertex])
        return finish("completed", raw=raw, independent=independent)
    except _Stop as stop:
        return finish("budget_exceeded", str(stop))
    except MemoryError:
        stats["allocation_failed"] = True
        return finish("budget_exceeded", "memory_allocation_failed")


def partition_pair_bound(grid: GridGraph, *, vertex: int, depth: int,
                         budget: int, q, motion: ParticleMotion, belief,
                         pairs, remainder_mode="stdc", max_seconds=None,
                         max_memory_bytes=128*1024*1024):
    """Combine disjoint exact pairs and a remaining-mass STDC group.

    Every group retains the original set of legal suffixes.  Different groups
    may choose different routes, so sum(group optima) <= full optimum.  STDC on
    the remainder underestimates that group's optimum.  `bound` is the maximum
    of the additive grouped bound and ordinary full-mass STDC.  It need not
    dominate the all-singleton DP bound.  Time covers every pair and both STDC
    evaluations; STDC's existing call is cooperative only at its boundary.
    Any interrupted group/evaluation makes the whole diagnostic unpublished.
    """
    begun = perf_counter()
    vertex, depth, budget, q, b = _validate(
        grid, vertex, depth, budget, q, motion, belief,
        max_seconds, max_memory_bytes)
    if remainder_mode != "stdc":
        raise ValueError("only the documented remainder_mode='stdc' is supported")
    pairs = tuple(_pair_indices(pair, motion.state_size) for pair in pairs)
    members = [x for pair in pairs for x in pair]
    if len(set(members)) != len(members):
        raise ValueError("pairs must be disjoint; double-counting mass is invalid")
    deadline = inf if max_seconds is None else begun+max_seconds
    results = []
    stats = dict(pairs=[list(pair) for pair in pairs], remainder_mode=remainder_mode,
                 selected_particle_count=len(members), global_epsilon_certified=False,
                 combined_rule="max(full_STDC, sum(shared_pair_bounds)+STDC(remainder))",
                 all_singleton_dominance_claim=False,
                 max_memory_scope="pair DP managed buffers; existing STDC caches excluded")

    def result(status, reason=None, grouped=None, full=None, remainder=None):
        wall = perf_counter()-begun
        stats["deadline_overshoot_s"] = max(0., begun+wall-deadline)
        combined = None if grouped is None or full is None else max(grouped, full)
        return PartitionPairBoundResult(combined, grouped, full, remainder,
                                        status, reason, wall, results, stats)

    if perf_counter() >= deadline:
        return result("budget_exceeded", "max_seconds")
    if grid.size == 1 and depth < budget:
        return result("infeasible", "no_legal_nonwaiting_suffix")
    for pair in pairs:
        remaining = None if deadline == inf else max(0., deadline-perf_counter())
        item = pair_shared_bound(grid, vertex=vertex, depth=depth, budget=budget,
                                 q=q, motion=motion, belief=b, pair=pair,
                                 max_seconds=remaining, max_memory_bytes=max_memory_bytes)
        results.append(item)
        if item.status != "completed":
            return result(item.status, item.stop_reason)
    if perf_counter() >= deadline:
        return result("budget_exceeded", "max_seconds")
    bound = STDCHeuristic(grid, budget=budget, q=q, motion=motion)
    full = bound(vertex, depth, b)
    remaining_b = b.copy()
    remaining_b[members] = 0.
    remainder = bound(vertex, depth, remaining_b) if np.any(remaining_b) else 0.
    if perf_counter() >= deadline:
        return result("budget_exceeded", "max_seconds")
    grouped = float(sum(item.bound for item in results)+remainder)
    stats.update(full_stdc_calls=1, remainder_stdc_calls=int(np.any(remaining_b)),
                 exact_pair_sum=float(sum(item.bound for item in results)),
                 remainder_mass=float(remaining_b.sum()),
                 selected_mass=float(b[members].sum()),
                 gain_over_full_stdc=max(0., grouped-full))
    return result("completed", grouped=grouped, full=float(full), remainder=float(remainder))
