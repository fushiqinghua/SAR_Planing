"""Provably admissible spatio-temporal / detection-capacity lower bounds.

Research extension for A^SAR baseline-v1.1; does NOT replace paper_greedy.

Models and timing must agree with the baseline:
  * t=0: no sensing; at t=1...T: drift first, then sense one destination;
  * grid is a four-neighbour rectangular graph, with no waiting;
  * motion is exogenous, nonnegative and mass-preserving;
  * non-searchable particle bins retain their undetected mass.

The exact-k reachability formula requires at least TWO grid vertices.
For a single-vertex grid and a nonzero remainder, no legal completion exists.
"""

from __future__ import annotations

from collections import OrderedDict

import numpy as np

from .belief import sensor_probabilities, undetected_mass
from .grid import GridGraph, integer
from .motion import MatrixMotion, ParticleMotion


STDC_MODES = (
    "reach_lb",        # relaxed sensor simultaneously covers all exactly-k reachable cells
    "capacity_lb",     # one-cell-per-step detection capacity, propagated through time
    "stepwise_lb",     # per-time max(reach bound, capacity bound), no cross-coupling
    "stdc_lb",         # temporal coupling + exactly-k reachable cells
    "stdc_radius_lb",  # temporal coupling + dist <= k (ablation only)
)


class STDCHeuristic:
    """Evaluate admissible remaining truncated expected detection-time costs.

    Each call uses the input node's *path-dependent* undetected belief. A cached
    (vertex, relative k) reachability set is safe; a cached whole h keyed only
    by (vertex, depth) would NOT be safe.
    """

    def __init__(self, grid: GridGraph, *, budget: int, q,
                 motion: MatrixMotion | ParticleMotion, mode: str = "stdc_lb"):
        if mode not in STDC_MODES:
            raise ValueError(f"unknown STDC heuristic: {mode}")
        if grid.size != motion.size:
            raise ValueError("motion grid size must match search grid size")
        self.grid = grid
        self.budget = integer(budget, "budget")
        self.q = sensor_probabilities(q, grid.size).copy()
        self.q.setflags(write=False)
        self.motion = motion
        self.mode = mode
        self._use_exact = mode != "stdc_radius_lb"
        if isinstance(motion, ParticleMotion):
            motion.check_horizon(self.budget)
        self._distances: dict[int, np.ndarray] = {}
        self._saturation: dict[int, int] = {}
        self._reach: dict[tuple[int, int], np.ndarray] = {}
        # Geometry and sensor parameters are independent of path belief and
        # absolute time. Cache ONLY these; never cache h by (depth, vertex).
        # LRU bounds the extra float arrays, independently of T and particle N.
        self._geometry = OrderedDict()
        self._geometry_bytes = 0
        self._geometry_limit = 16 * 1024 * 1024
        self._geometry_hits = self._geometry_misses = 0
        # The native particle array can also represent inactive, land and
        # outside particles with IDs >= grid.size; they MUST NOT be sensed.
        self._particle_factors_template = (
            np.ones(motion.bin_count, dtype=np.float64)
            if isinstance(motion, ParticleMotion) else None
        )

    def reachable(self, vertex: int, relative_step: int) -> np.ndarray:
        """Searchable vertex IDs reachable after exactly k legal moves.

        stdc_radius_lb intentionally uses a superset (<= k) as an ablation.
        """
        self.grid.coordinates(vertex)
        k = integer(relative_step, "relative_step", 1)
        return self._reachable(self._reach_key(vertex, k))

    def _reach_key(self, vertex, k):
        """Unchecked internal lookup, after the public call validates inputs."""
        if vertex not in self._distances:
            dist = self.grid.distances_from(vertex)
            self._distances[vertex] = dist
            self._saturation[vertex] = int(dist.max())
        last = self._saturation[vertex]
        if k > last:
            # Beyond the farthest cell, exact reachability alternates between
            # the two graph parities; radius reachability no longer changes.
            k = last + ((k - last) % 2) if self._use_exact else last
        return (vertex, k)

    def _reachable(self, key):
        result = self._reach.get(key)
        if result is not None:
            return result
        vertex, k = key
        dist = self._distances[vertex]
        mask = dist <= k
        if self._use_exact:
            mask &= ((k - dist) % 2 == 0)
        result = np.flatnonzero(mask)
        # Do not mutate or cache a partially valid answer for a disconnected
        # or one-cell no-wait graph. Exact-k availability is a model premise.
        if result.size == 0:
            raise ValueError("no legal continuation at this remaining step")
        result.setflags(write=False)
        self._reach[key] = result
        return result

    def _step_geometry(self, vertex, k):
        key = self._reach_key(vertex, k)
        cached = self._geometry.get(key)
        if cached is not None:
            self._geometry_hits += 1
            self._geometry.move_to_end(key)
            return cached[0]
        self._geometry_misses += 1
        reach = self._reachable(key)
        qr = self.q[reach]
        miss = 1.0 - qr
        qmax = float(qr.max())
        factors = None
        if self._particle_factors_template is not None and self.mode != "capacity_lb":
            factors = self._particle_factors_template.copy()
            factors[reach] = miss
            factors.setflags(write=False)
        qr.setflags(write=False)
        miss.setflags(write=False)
        value = (reach, qr, miss, qmax, factors)
        size = qr.nbytes + miss.nbytes + (0 if factors is None else factors.nbytes)
        if size <= self._geometry_limit:
            while self._geometry and self._geometry_bytes + size > self._geometry_limit:
                _, (_, removed_size) = self._geometry.popitem(last=False)
                self._geometry_bytes -= removed_size
            self._geometry[key] = (value, size)
            self._geometry_bytes += size
        return value

    def geometry_cache_info(self):
        """Diagnostic counters; excludes the pre-existing integer reach arrays."""
        return dict(hits=self._geometry_hits, misses=self._geometry_misses,
                    entries=len(self._geometry), array_bytes=self._geometry_bytes,
                    array_byte_limit=self._geometry_limit,
                    reach_array_bytes=sum(a.nbytes for a in self._reach.values()))

    def __call__(self, vertex: int, depth: int, belief, *, choices=None) -> float:
        self.grid.coordinates(vertex)
        depth = integer(depth, "depth")
        if depth > self.budget:
            raise ValueError("depth exceeds search budget")
        if depth == self.budget:
            return 0.0

        b = undetected_mass(belief, self.motion.state_size)
        relaxed = b.copy()  # ideal multi-cell observer belief
        no_search = b.copy()  # must NEVER be attenuated by future sensing
        mass0 = float(np.sum(b))
        capacity_prev = mass0
        coupled_prev = mass0
        total = 0.0
        is_particles = isinstance(self.motion, ParticleMotion)

        for k in range(1, self.budget - depth + 1):
            t = depth + k  # motion uses ABSOLUTE time; reach uses RELATIVE k
            reach, qr, miss, qmax, factors = self._step_geometry(vertex, k)

            if is_particles:
                # OpenDrift particle ID-weight vector is unchanged by drift;
                # absolute frame t gives each ID's new cell.
                cells = self.motion.cell_ids[t]
                if self.mode != "capacity_lb":
                    relaxed *= factors[cells]
                    a = float(relaxed.sum())
                else:
                    a = 0.0
                if self.mode != "reach_lb":
                    mu = self.motion.cell_mass(no_search, t)
                    u = float(np.max(qr * mu[reach]))
                else:
                    u = 0.0
            else:
                if self.mode != "capacity_lb":
                    relaxed = self.motion.propagate(relaxed, step=t)
                    relaxed[reach] *= miss
                    a = float(relaxed.sum())
                else:
                    a = 0.0
                if self.mode != "reach_lb":
                    no_search = self.motion.propagate(no_search, step=t)
                    mu = self.motion.cell_mass(no_search, t)
                    u = float(np.max(qr * mu[reach]))
                else:
                    u = 0.0

            if self.mode == "reach_lb":
                ell = a
            else:
                capacity_prev = max((1.0 - qmax) * capacity_prev,
                                    capacity_prev - u)
                if self.mode == "capacity_lb":
                    ell = capacity_prev
                elif self.mode == "stepwise_lb":
                    ell = max(a, capacity_prev)
                else:
                    coupled_prev = max(a,
                                       (1.0 - qmax) * coupled_prev,
                                       coupled_prev - u)
                    ell = coupled_prev
            # Round-off is handled by small test tolerances. No epsilon is
            # added to h: doing so would INVALIDATE admissibility.
            total += ell
        return float(total)
