"""Feasible comparison paths on the same time-indexed motion model as A^SAR."""

from itertools import pairwise

import numpy as np

from .belief import initial_belief, sensor_probabilities
from .objective import score_path


def parallel_track(grid, *, start, budget, p, q, motion):
    """Track the central 90% marginal envelope, scanning east/west one row apart.

    Before reaching the envelope use legal transit moves (rows first). Each
    arrival and each turn uses that step's predicted *undetected* mass. Tiny
    tails and special bins retain their weights in the underlying scorer.
    """
    weights = initial_belief(p, motion.state_size)
    sensor = sensor_probabilities(q, grid.size)
    row, col = grid.coordinates(start)
    path = [start]
    east, south = 1, 1
    entered = False

    def interval(marginal):
        cdf = np.cumsum(marginal)
        return np.searchsorted(cdf, cdf[-1] * np.array([.05, .95]))

    for t in range(1, budget + 1):
        prior = motion.propagate(weights, step=t)
        gains = sensor * motion.cell_mass(prior, t)[:grid.size]
        image = gains.reshape(grid.rows, grid.cols)
        north, bottom, west, right = 0, grid.rows - 1, 0, grid.cols - 1
        if gains.sum() > 0:
            north, bottom = interval(image.sum(axis=1))
            west, right = interval(image.sum(axis=0))
        if not entered and not north <= row <= bottom:
            row += 1 if row < north else -1
        elif not entered and not west <= col <= right:
            col += 1 if col < west else -1
        else:
            if not entered:
                east = 1 if right - col >= col - west else -1
                south = 1 if bottom - row >= row - north else -1
            entered = True
            if (east > 0 and col < right) or (east < 0 and col > west):
                col += east
            else:
                if row >= bottom:
                    south = -1
                elif row <= north:
                    south = 1
                if not 0 <= row + south < grid.rows:
                    south *= -1
                if 0 <= row + south < grid.rows:
                    row += south
                elif grid.cols > 1:
                    col += -1 if col == grid.cols - 1 else (1 if col == 0 else -east)
                else:
                    raise ValueError("no legal next move")
                east *= -1
        vertex = grid.vertex(row, col)
        weights = motion.sense(prior, vertex, sensor, t)
        path.append(vertex)
    return tuple(path)


def aco_inspired(grid, args, settings, seed):
    """Local ant system with directed edge trails and a positive exploration floor."""
    motion = args["motion"]
    sensor = sensor_probabilities(args["q"], grid.size)
    rng = np.random.default_rng(seed)
    trail = {}
    best_path, best_cost = None, np.inf
    for _ in range(settings["generations"]):
        leaders = []
        for _ in range(settings["ants"]):
            weights = args["p"]
            path = [args["start"]]
            for step in range(1, args["budget"] + 1):
                prior = motion.propagate(weights, step=step)
                mass = motion.cell_mass(prior, step)
                source = path[-1]
                neighbors = grid.neighbors(source)
                # A trail of zero means no reinforcement; the unit baseline
                # and exploration floor give every adjacent move support.
                odds = [(1 + trail.get((source, v), 0.0)) *
                        (settings["exploration_mass"] + sensor[v] * mass[v]) for v in neighbors]
                cumulative = np.cumsum(odds)
                v = neighbors[cumulative.searchsorted(rng.random() * cumulative[-1], side="right")]
                weights = motion.sense(prior, v, sensor, step)
                path.append(v)
            cost = score_path(grid, path, **args).J
            leaders.append((cost, tuple(path)))
            if cost < best_cost:
                best_cost, best_path = cost, tuple(path)
        trail = {edge: value * (1 - settings["evaporation"]) for edge, value in trail.items()}
        cost, winner = min(leaders, key=lambda item: item[0])
        for edge in pairwise(winner):
            trail[edge] = trail.get(edge, 0.) + args["budget"] / max(cost, 1.0)
    return best_path
