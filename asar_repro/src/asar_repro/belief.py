"""Unconditional, undetected target mass. All vectors use float64."""

import numpy as np

from .grid import integer


MASS_ATOL = 1e-12


def float_array(values, name):
    if np.iscomplexobj(values):
        raise ValueError(f"{name} must be real")
    return np.asarray(values, dtype=np.float64)


def check_probabilities(values, name):
    if not np.all(np.isfinite(values)) or np.any(values < 0) or np.any(values > 1):
        raise ValueError(f"{name} entries must be finite probabilities in [0, 1]")


def initial_belief(p, size: int):
    values = float_array(p, "p")
    if values.shape != (size,):
        raise ValueError(f"p must have shape ({size},)")
    check_probabilities(values, "p")
    if not np.isclose(values.sum(), 1.0, atol=MASS_ATOL, rtol=0):
        raise ValueError("p must sum to 1")
    return values.copy()


def undetected_mass(values, size: int):
    b = float_array(values, "belief")
    if b.shape != (size,) or not np.all(np.isfinite(b)) or np.any(b < 0):
        raise ValueError("belief must be a finite nonnegative vector of grid size")
    if b.sum() > 1 + MASS_ATOL:
        raise ValueError("undetected belief mass must be at most 1")
    return b


def sensor_probabilities(q, size: int):
    values = float_array(q, "q")
    if values.shape not in ((), (size,)):
        raise ValueError(f"q must be a scalar or have shape ({size},)")
    check_probabilities(values, "q")
    return np.broadcast_to(values, (size,))


def detect(prior, vertex: int, q):
    """Apply one glimpse to a copy. Only its visited entry changes."""
    prior = np.asarray(prior)
    if prior.ndim != 1:
        raise ValueError("prior must be a vector")
    belief = undetected_mass(prior, prior.size).copy()
    vertex = integer(vertex, "vertex")
    if vertex >= belief.size:
        raise ValueError("vertex outside the belief vector")
    probabilities = sensor_probabilities(q, belief.size)
    belief[vertex] *= 1.0 - probabilities[vertex]
    return belief
