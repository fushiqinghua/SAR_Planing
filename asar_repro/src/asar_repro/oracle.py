"""Small-grid truth by exhaustive depth-first traversal and full path replay."""

from dataclasses import dataclass
from math import inf, isfinite

from .grid import GridGraph, integer
from .motion import MatrixMotion, ParticleMotion
from .objective import score_path


@dataclass
class OracleResult:
    path: tuple[int, ...]
    J: float
    tied_paths: tuple[tuple[int, ...], ...]
    complete_paths: int
    expanded: int
    generated: int
    peak_open: int


def enumerate_oracle(grid: GridGraph, *, start: int, budget: int, p, q,
                     motion: MatrixMotion | ParticleMotion, tie_atol: float = 1e-12, prefix=None) -> OracleResult:
    """Score every legal completion of prefix, returning full path and full cost."""
    grid.coordinates(start)
    budget = integer(budget, "budget")
    if grid.size > 16 or budget > 8:
        raise ValueError("exhaustive oracle supports at most 16 vertices and budget <= 8")
    if not isfinite(tie_atol) or tie_atol < 0:
        raise ValueError("tie_atol must be finite and nonnegative")

    prefix = (start,) if prefix is None else tuple(prefix)
    grid.validate_path(prefix, start=start, budget=len(prefix) - 1)
    if len(prefix) > budget + 1:
        raise ValueError("prefix exceeds budget")
    stack = [prefix]
    best_cost = inf
    best_path = None
    candidates = []
    complete_paths = expanded = generated = 0
    peak_open = 1
    while stack:
        path = stack.pop()
        if len(path) == budget + 1:
            complete_paths += 1
            cost = score_path(grid, path, start=start, budget=budget, p=p, q=q,
                              motion=motion).J
            if cost < best_cost:
                best_cost, best_path = cost, path
            if cost - best_cost <= tie_atol:
                candidates.append((cost, path))
            continue

        expanded += 1
        for vertex in reversed(grid.neighbors(path[-1])):
            stack.append(path + (vertex,))
            generated += 1
        peak_open = max(peak_open, len(stack))

    if best_path is None:
        raise ValueError("no feasible path of the requested length")
    tied = tuple(path for cost, path in candidates if cost - best_cost <= tie_atol)
    return OracleResult(best_path, best_cost, tied, complete_paths, expanded,
                        generated, peak_open)
