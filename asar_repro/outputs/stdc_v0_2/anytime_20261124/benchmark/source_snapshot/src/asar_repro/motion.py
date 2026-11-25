"""Discrete Markov motion, with rows indexing sources and columns destinations."""

import numpy as np
from scipy import sparse

from .belief import MASS_ATOL, check_probabilities, detect, float_array, undetected_mass
from .grid import integer


def _transition(matrix, step):
    name = f"P (matrix {step})"
    # Check original sparse entries before duplicate coordinates are summed.
    coo = sparse.coo_matrix(matrix)
    data = float_array(coo.data, name)
    check_probabilities(data, name)
    P = coo.astype(np.float64, copy=True).tocsr()
    if not P.shape[0] or P.shape[0] != P.shape[1]:
        raise ValueError(f"{name} must be nonempty and square")
    check_probabilities(P.data, name)
    if not np.allclose(P.sum(axis=1), 1.0, atol=MASS_ATOL, rtol=0):
        raise ValueError(f"{name} rows must sum to 1")
    return P


class MatrixMotion:
    def __init__(self, matrices, *, repeat: bool):
        self._matrices = tuple(_transition(P, t) for t, P in enumerate(matrices, 1))
        if not self._matrices or (repeat and len(self._matrices) != 1):
            raise ValueError("provide one repeated P or a nonempty sequence of P_t")
        self.size = self._matrices[0].shape[0]
        self.state_size = self.size
        if any(P.shape != (self.size, self.size) for P in self._matrices):
            raise ValueError("all P_t must have the same shape")
        self._repeat = repeat

    @classmethod
    def identity(cls, size: int):
        """Static target, valid for any number of steps."""
        return cls.stationary(sparse.eye(integer(size, "size", 1), format="csr"))

    @classmethod
    def stationary(cls, matrix):
        """Repeat one transition kernel at every step."""
        return cls([matrix], repeat=True)

    @classmethod
    def time_varying(cls, matrices):
        """The first supplied matrix is P_1, for the transition 0 -> 1."""
        return cls(matrices, repeat=False)

    def propagate(self, belief, *, step: int):
        step = integer(step, "step", 1)
        if not self._repeat and step > len(self._matrices):
            raise ValueError(f"missing P_t for step {step}")
        P = self._matrices[0 if self._repeat else step - 1]
        return P.T @ undetected_mass(belief, self.size)

    def cell_mass(self, state, step):
        return state

    def sense(self, prior, vertex, sensor, step):
        return detect(prior, vertex, sensor)


class ParticleMotion:
    """Fixed ID columns; state entries are joint undetected particle weights."""

    def __init__(self, cell_ids, size, trajectory_ids, *, special_bins=4):
        self.size = integer(size, "grid size", 1)
        self.bin_count = self.size + integer(special_bins, "special bins")
        cells = np.asarray(cell_ids)
        if (cells.ndim != 2 or not cells.size or cells.dtype.kind not in "iu"
                or cells.min() < 0 or cells.max() >= self.bin_count):
            raise ValueError("invalid time-by-particle cell IDs")
        self.state_size = cells.shape[1]
        ids = np.array(trajectory_ids, copy=True)
        if ids.shape != (self.state_size,) or np.unique(ids).size != len(ids):
            raise ValueError("trajectory IDs must uniquely identify each column")
        self.cell_ids = np.array(cells, dtype=np.intp, copy=True)
        self.cell_ids.setflags(write=False)
        self.trajectory_ids = ids
        ids.setflags(write=False)
        # Stable sorting keeps ID order within each cell; offsets avoid per-node scans.
        self._order = self.cell_ids.argsort(axis=1, kind="stable")
        self._offsets = [np.r_[0, np.bincount(frame, minlength=self.bin_count).cumsum()]
                         for frame in self.cell_ids]

    def check_horizon(self, budget):
        if budget >= len(self.cell_ids):
            raise ValueError("particle archive must cover frames 0 through budget")

    def propagate(self, belief, *, step):
        # Positions move at the supplied absolute step; ID-indexed weights do not.
        self.check_horizon(integer(step, "step", 1))
        return belief

    def cell_mass(self, state, step):
        return np.bincount(self.cell_ids[step], weights=state, minlength=self.bin_count)

    def sense(self, prior, vertex, sensor, step):
        offsets = self._offsets[step]
        members = self._order[step, offsets[vertex]:offsets[vertex + 1]]
        posterior = prior.copy()
        posterior[members] *= 1 - sensor[vertex]
        return posterior
