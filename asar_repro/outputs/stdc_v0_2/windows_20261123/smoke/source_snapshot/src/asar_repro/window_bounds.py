"""Fixed-suffix coefficients and lower bounds for a fixed-time path window.

These bounds apply to the chosen endpoint, end time and fixed suffix only.
They do not certify global optimality of the full search-and-rescue route.
All times are absolute frames: frame zero is before any observation.
"""

from dataclasses import dataclass
from math import inf

import numpy as np

from .belief import float_array, sensor_probabilities, undetected_mass
from .grid import GridGraph, integer
from .motion import MatrixMotion, ParticleMotion


WINDOW_MODES = ("zero", "mass_lb", "stdc_lb", "stdc_endpoint_lb")


def _check_motion(grid, motion, horizon):
    if not isinstance(motion, (MatrixMotion, ParticleMotion)):
        raise ValueError("window bounds require MatrixMotion or ParticleMotion")
    if grid.size != motion.size:
        raise ValueError("motion grid size must match the search grid")
    if isinstance(motion, ParticleMotion):
        motion.check_horizon(horizon)
    elif not motion._repeat and horizon > len(motion._matrices):
        raise ValueError(f"missing P_t for step {horizon}")


def _distances(grid, source):
    row, col = grid.coordinates(source)
    vertices = np.arange(grid.size, dtype=np.intp)
    return np.abs(vertices // grid.cols - row) + np.abs(vertices % grid.cols - col)


def _exact_mask(distances, steps, grid_size):
    if steps == 0:
        return distances == 0
    if grid_size == 1:
        return np.zeros(1, dtype=bool)  # A no-wait single vertex has no edges.
    return (distances <= steps) & ((steps - distances) % 2 == 0)


def exact_reachable(grid: GridGraph, source: int, steps: int) -> np.ndarray:
    """Sorted vertex IDs after exactly ``steps`` four-neighbour, no-wait moves.

    Unlike the original STDC helper, zero steps is defined and returns source.
    A one-vertex graph has an empty reachable set at every positive step.
    """
    steps = integer(steps, "steps")
    result = np.flatnonzero(_exact_mask(_distances(grid, source), steps, grid.size))
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class SuffixCoefficients:
    """Nonnegative linear coefficients for an immutable path snapshot.

    cost[d] excludes observations at or before d. Thus a complete candidate's
    objective equals its accumulated g[d] plus cost[d] @ belief[d]. Its final
    remaining mass is survival[d] @ belief[d]. Arrays are read-only.
    """

    cost: np.ndarray
    survival: np.ndarray


def suffix_coefficients(grid: GridGraph, path, *, q,
                        motion: MatrixMotion | ParticleMotion) -> SuffixCoefficients:
    """Build exact fixed-suffix cost and terminal-mass coefficients backwards.

    With row-stochastic P_t, forward beliefs use D_t P_t.T b; its adjoint is
    P_t D_t. This distinction is essential for non-symmetric dynamic kernels.
    Particle weights retain their ID columns and use the supplied absolute
    cell_ids[t]. Special bins never match a legal searched vertex.
    """
    path = tuple(path)
    if not path:
        raise ValueError("path must contain at least its starting vertex")
    horizon = len(path) - 1
    grid.validate_path(path, start=path[0], budget=horizon)
    _check_motion(grid, motion, horizon)
    sensor = sensor_probabilities(q, grid.size)
    cost = np.zeros((horizon + 1, motion.state_size), dtype=np.float64)
    survival = np.ones_like(cost)
    for t in range(horizon, 0, -1):
        vertex = path[t]
        factors = np.ones(motion.state_size, dtype=np.float64)
        if isinstance(motion, ParticleMotion):
            factors[motion.cell_ids[t] == vertex] = 1.0 - sensor[vertex]
            cost[t - 1] = factors * (1.0 + cost[t])
            survival[t - 1] = factors * survival[t]
        else:
            factors[vertex] = 1.0 - sensor[vertex]
            kernel = motion._matrices[0 if motion._repeat else t - 1]
            cost[t - 1] = kernel @ (factors * (1.0 + cost[t]))
            survival[t - 1] = kernel @ (factors * survival[t])
    cost.setflags(write=False)
    survival.setflags(write=False)
    return SuffixCoefficients(cost=cost, survival=survival)


class WindowHeuristic:
    """Remaining window cost plus a fixed suffix's nonnegative terminal cost.

    One instance fixes the endpoint, absolute end time, sensor and tail_cost.
    Geometry is reused only within that instance; no belief-dependent estimate
    is cached. If a caller changes the suffix, it must make a new instance.

    In endpoint mode, every legal completion's kth vertex belongs to the
    intersection of exact-k reachability from the current vertex and exact
    (R-k) reachability from the fixed endpoint. Simultaneously sensing this
    entire intersection gives a componentwise lower undetected belief. The
    STDC mass recurrence lower-bounds each window cost, and tail_cost dotted
    with the relaxed endpoint belief lower-bounds the unchanged suffix cost.
    """

    def __init__(self, grid: GridGraph, *, end_vertex: int, end_depth: int, q,
                 motion: MatrixMotion | ParticleMotion, tail_cost,
                 mode: str = "stdc_endpoint_lb"):
        if mode not in WINDOW_MODES:
            raise ValueError(f"unknown window heuristic: {mode}")
        grid.coordinates(end_vertex)
        self.grid = grid
        self.end_vertex = int(end_vertex)
        self.end_depth = integer(end_depth, "end_depth")
        _check_motion(grid, motion, self.end_depth)
        self.motion = motion
        self.mode = mode
        self.q = sensor_probabilities(q, grid.size).copy()
        self.q.setflags(write=False)
        tail = float_array(tail_cost, "tail_cost")
        if (tail.shape != (motion.state_size,) or not np.all(np.isfinite(tail))
                or np.any(tail < 0)):
            raise ValueError("tail_cost must be a finite nonnegative state-sized vector")
        self.tail_cost = tail.copy()
        self.tail_cost.setflags(write=False)
        self._tail_min = float(self.tail_cost.min())
        self._end_distances = _distances(grid, self.end_vertex)
        self._distances = {self.end_vertex: self._end_distances}
        self._geometry = {}
        # Avoid a division by q and retain the q=0/q=1 edge cases.
        a = 1.0 - float(self.q.max())
        self._mass_factors = [0.0]
        self._mass_powers = [1.0]
        for _ in range(self.end_depth):
            self._mass_factors.append(a * (1.0 + self._mass_factors[-1]))
            self._mass_powers.append(a * self._mass_powers[-1])

    def _feasible(self, vertex, remaining):
        if remaining == 0:
            return vertex == self.end_vertex
        if self.grid.size == 1:
            return False
        distance = int(self._end_distances[vertex])
        return distance <= remaining and (remaining - distance) % 2 == 0

    def _step_geometry(self, vertex, remaining, k):
        key = (vertex, remaining if self.mode == "stdc_endpoint_lb" else None, k)
        cached = self._geometry.get(key)
        if cached is not None:
            return cached
        if vertex not in self._distances:
            self._distances[vertex] = _distances(self.grid, vertex)
        mask = _exact_mask(self._distances[vertex], k, self.grid.size)
        if self.mode == "stdc_endpoint_lb":
            mask &= _exact_mask(self._end_distances, remaining - k, self.grid.size)
        reach = np.flatnonzero(mask)
        # _feasible ensures a complete path exists, hence each intersection is
        # nonempty. Treat an empty set as a model inconsistency, not zero cost.
        if not reach.size:
            raise ValueError("empty reachable set for a feasible window")
        qr = self.q[reach]
        miss = 1.0 - qr
        factors = None
        if isinstance(self.motion, ParticleMotion):
            factors = np.ones(self.motion.bin_count, dtype=np.float64)
            factors[reach] = miss
            factors.setflags(write=False)
        for array in (reach, qr, miss):
            array.setflags(write=False)
        value = (reach, qr, miss, float(qr.max()), factors)
        self._geometry[key] = value
        return value

    def __call__(self, vertex: int, depth: int, belief) -> float:
        self.grid.coordinates(vertex)
        vertex = int(vertex)
        depth = integer(depth, "depth")
        if depth > self.end_depth:
            raise ValueError("depth exceeds window end_depth")
        b = undetected_mass(belief, self.motion.state_size)
        remaining = self.end_depth - depth
        if not self._feasible(vertex, remaining):
            return inf
        if remaining == 0:
            return float(self.tail_cost @ b)
        if self.mode == "zero":
            return 0.0
        mass = float(b.sum())
        if self.mode == "mass_lb":
            return float(mass * self._mass_factors[remaining]
                         + self._tail_min * mass * self._mass_powers[remaining])

        relaxed = b.copy()
        no_search = b.copy()
        ell = mass
        total = 0.0
        particles = isinstance(self.motion, ParticleMotion)
        for k in range(1, remaining + 1):
            t = depth + k
            reach, qr, miss, qmax, factors = self._step_geometry(vertex, remaining, k)
            if particles:
                relaxed *= factors[self.motion.cell_ids[t]]
            else:
                relaxed = self.motion.propagate(relaxed, step=t)
                relaxed[reach] *= miss
                no_search = self.motion.propagate(no_search, step=t)
            a = float(relaxed.sum())
            mu = self.motion.cell_mass(no_search, t)
            u = float(np.max(qr * mu[reach]))
            ell = max(a, (1.0 - qmax) * ell, ell - u)
            total += ell
        return float(total + self.tail_cost @ relaxed)
