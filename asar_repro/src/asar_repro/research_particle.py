"""Opt-in particle execution and exact future-signature state compression.

The archived ParticleMotion, objective and particle IDs are never modified.
Aggregation is lossless in the real-arithmetic discrete model; different
floating summation order still requires comparison with the original scorer.
"""
from __future__ import annotations

import numpy as np

from .belief import MASS_ATOL, initial_belief, sensor_probabilities, undetected_mass
from .grid import integer
from .heuristic import Heuristic
from .motion import ParticleMotion


class ParticleGuide:
    """Paper Algorithm 2 with one private weight copy per nonterminal call.

    Reachability is the paper's distance-radius superset, not a continuity
    constraint between greedily selected cells. Frames are absolute and ties
    use the first ascending cell ID, exactly as Heuristic(paper_greedy).
    Non-particle motion conservatively delegates to the unchanged heuristic.
    This guide is an ordering device, never an admissible pruning certificate.
    """

    def __init__(self, grid, *, budget, q, motion):
        self.grid = grid
        self.budget = integer(budget, "budget")
        self.motion = motion
        self.mode = "paper_greedy"
        if grid.size != motion.size:
            raise ValueError("motion grid size must match the search grid")
        self.q = sensor_probabilities(q, grid.size).copy()
        self.q.setflags(write=False)
        self.used_fallback = not isinstance(motion, ParticleMotion)
        self._fallback = (Heuristic(grid, budget=budget, q=self.q, motion=motion,
                                   mode="paper_greedy") if self.used_fallback else None)
        if not self.used_fallback:
            motion.check_horizon(self.budget)
        self._reachable = {}

    def __call__(self, vertex, depth, belief, *, choices=None):
        if self._fallback is not None:
            return self._fallback(vertex, depth, belief, choices=choices)
        self.grid.coordinates(vertex)
        depth = integer(depth, "depth")
        if depth > self.budget:
            raise ValueError("depth exceeds search budget")
        if depth == self.budget:
            return 0.0
        weights = undetected_mass(belief, self.motion.state_size).copy()
        if vertex not in self._reachable:
            distances = self.grid.distances_from(vertex)
            self._reachable[vertex] = [np.flatnonzero(distances <= k)
                for k in range(min(self.budget, int(distances.max())) + 1)]
        rings = self._reachable[vertex]
        total = 0.0
        for t in range(depth + 1, self.budget + 1):
            reach = rings[min(t-depth, len(rings)-1)]
            mass = np.bincount(self.motion.cell_ids[t], weights=weights,
                               minlength=self.motion.bin_count)
            best = int(reach[np.argmax(self.q[reach] * mass[reach])])
            offsets = self.motion._offsets[t]
            members = self.motion._order[t, offsets[best]:offsets[best+1]]
            weights[members] *= 1.0 - self.q[best]
            # Preserve the reference reduction, rather than subtracting a
            # detection gain from a recursively maintained scalar mass.
            total += float(weights.sum())
            if choices is not None:
                choices.append(best)
        return total


class FutureEquivalentMotion(ParticleMotion):
    """Conservatively aggregate identical complete cell-ID columns.

    All archived frames, including t=0 and exact special-bin labels, are part
    of the signature. Thus every grouped particle has the same detection
    factor for any future path and any scalar/cell-vector q. This fixed
    partition may compress poorly; it does not claim minimal group count.

    `groups` contains original COLUMN indices, `group_trajectory_ids` their
    actual archived IDs, and inherited `trajectory_ids` representative IDs.
    A grouped state is NOT an original-ID state. Final independent replay
    uses original_motion, original_initial_weights and the unchanged path.

    expand_weights restores the initial within-group proportions. It applies
    to states evolved from the supplied initial weights under common group
    factors, not to arbitrary original-ID beliefs after information loss.
    """

    def __init__(self, original: ParticleMotion, initial_weights):
        if not isinstance(original, ParticleMotion):
            raise ValueError("FutureEquivalentMotion requires ParticleMotion")
        if isinstance(original, FutureEquivalentMotion):
            raise ValueError("nested compression would obscure original particle IDs")
        weights = initial_belief(initial_weights, original.state_size)
        _, first, inverse = np.unique(original.cell_ids.T, axis=0,
                                      return_index=True, return_inverse=True)
        order = np.argsort(first, kind="stable")
        remap = np.empty(len(order), dtype=np.intp)
        remap[order] = np.arange(len(order), dtype=np.intp)
        mapping = remap[inverse]
        representatives = first[order]
        super().__init__(original.cell_ids[:, representatives], original.size,
                         original.trajectory_ids[representatives],
                         special_bins=original.bin_count-original.size)
        self.original_motion = original
        self.original_initial_weights = weights
        self.original_trajectory_ids = original.trajectory_ids.copy()
        self.particle_to_group = mapping
        self.representative_columns = representatives
        self.groups = tuple(np.flatnonzero(mapping == group) for group in range(self.state_size))
        self.group_trajectory_ids = tuple(original.trajectory_ids[group].copy() for group in self.groups)
        self.initial_weights = self.aggregate_weights(weights)
        for array in (self.original_initial_weights, self.original_trajectory_ids,
                      self.particle_to_group, self.representative_columns, self.initial_weights,
                      *self.groups, *self.group_trajectory_ids):
            array.setflags(write=False)
        original_n, grouped_n = original.state_size, self.state_size
        self.compression_stats = dict(
            original_particles=original_n, grouped_particles=grouped_n,
            retained_fraction=grouped_n/original_n, reduction_fraction=1-grouped_n/original_n,
            compression_ratio=original_n/grouped_n,
            original_state_bytes=original_n*np.dtype(np.float64).itemsize,
            grouped_state_bytes=grouped_n*np.dtype(np.float64).itemsize,
            signature_frames=len(original.cell_ids),
            signature="all absolute frames; exact cell IDs including frame 0 and special-bin labels",
            grouping="fixed conservative full-column equivalence; not depth-adaptive",
            floating_order="group aggregation may change rounding; original-ID replay remains required")

    def aggregate_weights(self, original_weights):
        """Sum current original-ID weights; no normalization or mass removal."""
        weights = undetected_mass(original_weights, self.original_motion.state_size)
        result = np.bincount(self.particle_to_group, weights=weights, minlength=self.state_size)
        result.setflags(write=False)
        return result

    def expand_weights(self, grouped_weights):
        """Restore reachable grouped states in the archived original-ID order."""
        weights = undetected_mass(grouped_weights, self.state_size)
        initial = self.initial_weights
        if (np.any(weights > initial + MASS_ATOL)
                or np.any((initial == 0) & (weights != 0))):
            raise ValueError("group weights cannot arise from the supplied initial proportions")
        factors = np.zeros(self.state_size, dtype=np.float64)
        np.divide(weights, initial, out=factors, where=initial > 0)
        result = self.original_initial_weights * factors[self.particle_to_group]
        result.setflags(write=False)
        return result

    def sense(self, prior, vertex, sensor, step):
        """Share only an already read-only no-change state; otherwise copy.

        The caller owns immutable search states. No input write flag is ever
        changed. A writable no-op input is copied to avoid mutable aliases.
        """
        offsets = self._offsets[step]
        members = self._order[step, offsets[vertex]:offsets[vertex+1]]
        unchanged = not members.size or sensor[vertex] == 0 or not np.any(prior[members])
        if unchanged and not prior.flags.writeable:
            return prior
        posterior = prior.copy()
        if not unchanged:
            posterior[members] *= 1.0-sensor[vertex]
        posterior.setflags(write=False)
        return posterior
