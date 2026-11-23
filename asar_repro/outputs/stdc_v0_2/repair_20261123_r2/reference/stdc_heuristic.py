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
        self.motion = motion
        self.mode = mode
        self._use_exact = mode != "stdc_radius_lb"
        if isinstance(motion, ParticleMotion):
            motion.check_horizon(self.budget)
        self._distances: dict[int, np.ndarray] = {}
        self._reach: dict[tuple[int, int], np.ndarray] = {}
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
        key = (vertex, k)
        result = self._reach.get(key)
        if result is not None:
            return result
        if vertex not in self._distances:
            self._distances[vertex] = self.grid.distances_from(vertex)
        dist = self._distances[vertex]
        mask = dist <= k
        if self._use_exact:
            mask &= ((k - dist) % 2 == 0)
        result = np.flatnonzero(mask)
        # Do not mutate or cache a partially valid answer for a disconnected
        # or one-cell no-wait graph. Exact-k availability is a model premise.
        if result.size == 0:
            raise ValueError("no legal continuation at this remaining step")
        self._reach[key] = result
        return result

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
            reach = self.reachable(vertex, k)
            qr = self.q[reach]
            qmax = float(qr.max())

            if is_particles:
                # OpenDrift particle ID-weight vector is unchanged by drift;
                # absolute frame t gives each ID's new cell.
                cells = self.motion.cell_ids[t]
                if self.mode != "capacity_lb":
                    factors = self._particle_factors_template.copy()
                    factors[reach] = 1.0 - qr
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
                    relaxed[reach] *= (1.0 - qr)
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
