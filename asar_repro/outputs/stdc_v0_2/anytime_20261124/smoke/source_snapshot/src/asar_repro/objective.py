"""Replay and score one feasible path under Eq. (1), (5) and (7)."""

from dataclasses import dataclass

import numpy as np

from .belief import initial_belief, sensor_probabilities
from .grid import GridGraph
from .motion import MatrixMotion, ParticleMotion


@dataclass
class PathScore:
    survival: np.ndarray     # M_0 .. M_T
    g: np.ndarray            # g_0 .. g_T
    delta_pd: np.ndarray     # P(D=t), for t=1 .. T
    final_belief: np.ndarray
    beliefs: np.ndarray | None = None  # Optional b_0 .. b_T for plotting or replay audits.

    @property
    def J(self) -> float:
        return float(self.g[-1])

    @property
    def pd_final(self) -> float:
        return 1.0 - float(self.survival[-1])


def score_path(grid: GridGraph, path, *, start: int, budget: int, p, q,
               motion: MatrixMotion | ParticleMotion, record_beliefs: bool = False) -> PathScore:
    """Score exactly budget four-neighbor moves, starting before any search."""
    grid.validate_path(path, start=start, budget=budget)
    if motion.size != grid.size:
        raise ValueError("transition matrix size must match the grid")
    belief = initial_belief(p, motion.state_size)
    sensor = sensor_probabilities(q, grid.size)
    survival = np.empty(len(path), dtype=np.float64)
    beliefs = np.empty((len(path), motion.state_size)) if record_beliefs else None
    if beliefs is not None:
        beliefs[0] = belief
    survival[0] = belief.sum()
    for step, vertex in enumerate(path[1:], start=1):
        prior = motion.propagate(belief, step=step)
        belief = motion.sense(prior, vertex, sensor, step)
        survival[step] = belief.sum()
        if beliefs is not None:
            beliefs[step] = belief
    g = np.zeros_like(survival)
    np.cumsum(survival[1:], out=g[1:])
    return PathScore(survival, g, -np.diff(survival), belief, beliefs)
