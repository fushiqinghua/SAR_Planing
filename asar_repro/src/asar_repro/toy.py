"""Synthetic inputs and feasible comparison paths for the stage 4 toys."""

import numpy as np

from .belief import detect, initial_belief, sensor_probabilities
from .grid import GridGraph, integer
from .motion import MatrixMotion


def gaussian_prior(grid, spec, seed):
    rng = np.random.default_rng(seed)
    rows, cols = np.indices((grid.rows, grid.cols))
    weights = np.zeros(rows.shape)
    for peak in spec["peaks"]:
        center = np.asarray(peak["center_rc"]) + rng.normal(0, spec["center_jitter_std_cells"], 2)
        sigma, amplitude = peak["sigma_cells"], peak["amplitude"]
        if sigma <= 0 or amplitude <= 0:
            raise ValueError("Gaussian peak width and amplitude must be positive")
        squared = (rows - center[0])**2 + (cols - center[1])**2
        weights += amplitude * np.exp(-squared / (2 * sigma**2))
    if not np.isfinite(weights.sum()) or weights.sum() <= 0:
        raise ValueError("Gaussian mixture requires positive finite total mass")
    return initial_belief((weights / weights.sum()).ravel(), grid.size)


def build_motion(grid, spec, budget):
    if spec["kind"] == "static":
        return MatrixMotion.identity(grid.size)
    if spec["kind"] != "local_drift":
        raise ValueError("unknown toy motion model")
    directions = {"stay": (0, 0), "north": (-1, 0), "south": (1, 0),
                  "west": (0, -1), "east": (0, 1)}
    matrices = []
    for phase in spec["phases"]:
        end = integer(phase["through"], "through", 1)
        if not len(matrices) < end <= budget:
            raise ValueError("phase endpoints must increase within the budget")
        probabilities = [phase[name] for name in directions]
        if min(probabilities) < 0 or not np.isclose(sum(probabilities), 1, rtol=0, atol=1e-12):
            raise ValueError("drift probabilities must be nonnegative and sum to one")
        matrix = np.zeros((grid.size, grid.size))
        for u in range(grid.size):
            row, col = grid.coordinates(u)
            for direction, (dr, dc) in directions.items():
                r, c = row + dr, col + dc
                dest = grid.vertex(r, c) if 0 <= r < grid.rows and 0 <= c < grid.cols else u
                matrix[u, dest] += phase[direction]
        matrices.extend([matrix] * (end - len(matrices)))
    if len(matrices) != budget:
        raise ValueError("drift phases must cover the full path budget")
    return MatrixMotion.time_varying(matrices)


def toy_problem(config):
    grid = GridGraph(*config["grid"])
    T = integer(config["budget"], "budget")
    args = dict(start=grid.vertex(*config["start_rc"]), budget=T,
                p=gaussian_prior(grid, config["prior"], config["seed"]), q=config["q"],
                motion=build_motion(grid, config["motion"], T))
    return grid, args


def baseline_path(grid, *, start, budget, p, q, motion, method):
    """Serpentine legs or greedy one-step detection using the next-step prior."""
    if method not in ("serpentine", "greedy"):
        raise ValueError("unknown toy baseline")
    row, col = grid.coordinates(start)
    direction = -1 if col == grid.cols - 1 else 1
    b = initial_belief(p, grid.size)
    sensor = sensor_probabilities(q, grid.size)
    path = [start]
    for t in range(1, budget + 1):
        prior = motion.propagate(b, step=t)
        if method == "greedy":
            adjacent = grid.neighbors(path[-1])
            if not adjacent:
                raise ValueError("no legal next move")
            dest = max(adjacent, key=lambda v: sensor[v] * prior[v])
        elif 0 <= col + direction < grid.cols:
            dest = grid.vertex(row, col + direction)
        else:
            # At a row end choose a neighboring scanline by its predicted
            # detectable mass, then traverse that chosen row in the other direction.
            rows = [r for r in (row - 1, row + 1) if 0 <= r < grid.rows]
            if rows:
                row_gain = (sensor * prior).reshape(grid.rows, grid.cols).sum(axis=1)
                row = max(rows, key=lambda r: row_gain[r])
                dest = grid.vertex(row, col)
            elif grid.cols > 1:
                dest = grid.vertex(row, col - direction)
            else:
                raise ValueError("no legal next move")
            direction *= -1
        b = detect(prior, dest, sensor)
        row, col = grid.coordinates(dest)
        path.append(dest)
    return tuple(path)


def order_control(grid, reference_path):
    """Swap two closed excursions, then append one identical feasible suffix."""
    start = reference_path[0]
    r, c = grid.coordinates(start)
    reach = min(grid.cols - 1 - c, r)
    if reach < 1:
        raise ValueError("order experiment needs an east and a north excursion")
    east = [grid.vertex(r, c + k) for k in range(1, reach + 1)]
    north = [grid.vertex(r - k, c) for k in range(1, reach + 1)]

    def round_trip(outward):
        return outward + list(reversed(outward[:-1])) + [start]

    a, b = round_trip(east), round_trip(north)
    remaining = len(reference_path) - 1 - len(a) - len(b)
    if remaining < 0:
        raise ValueError("budget too short for both order-control excursions")
    tail = list(reference_path[1:remaining + 1])
    paths = {"east_first": (start, *a, *b, *tail), "north_first": (start, *b, *a, *tail)}
    return paths, len(a) + len(b)
