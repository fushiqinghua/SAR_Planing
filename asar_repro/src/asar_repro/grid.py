"""Rectangular four-connected grid with row-major vertex IDs."""

from collections import deque
from dataclasses import dataclass
from numbers import Integral


def integer(value, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


@dataclass(frozen=True)
class GridGraph:
    rows: int
    cols: int

    def __post_init__(self):
        object.__setattr__(self, "rows", integer(self.rows, "rows", 1))
        object.__setattr__(self, "cols", integer(self.cols, "cols", 1))

    @property
    def size(self) -> int:
        return self.rows * self.cols

    def vertex(self, row: int, col: int) -> int:
        row, col = integer(row, "row"), integer(col, "col")
        if row >= self.rows or col >= self.cols:
            raise ValueError("coordinates outside the grid")
        return row * self.cols + col

    def coordinates(self, vertex: int) -> tuple[int, int]:
        vertex = integer(vertex, "vertex")
        if vertex >= self.size:
            raise ValueError("vertex outside the grid")
        return divmod(vertex, self.cols)

    def neighbors(self, vertex: int) -> tuple[int, ...]:
        row, col = self.coordinates(vertex)
        adjacent = ((row - 1, col), (row, col - 1), (row, col + 1), (row + 1, col))
        return tuple(r * self.cols + c for r, c in adjacent
                     if 0 <= r < self.rows and 0 <= c < self.cols)

    def dist(self, source: int, target: int) -> int:
        """BFS shortest distance measured in edges."""
        self.coordinates(source)
        self.coordinates(target)
        queue = deque([(source, 0)])
        seen = {source}
        while queue:
            vertex, depth = queue.popleft()
            if vertex == target:
                return depth
            for neighbor in self.neighbors(vertex):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append((neighbor, depth + 1))
        raise RuntimeError("rectangular grid is disconnected")

    def distances_from(self, source):
        """All four-neighbor BFS distances in one traversal."""
        import numpy as np

        self.coordinates(source)
        distances = np.full(self.size, -1, dtype=int)
        distances[source] = 0
        queue = deque([source])
        while queue:
            v = queue.popleft()
            for u in self.neighbors(v):
                if distances[u] < 0:
                    distances[u] = distances[v] + 1
                    queue.append(u)
        return distances

    def validate_path(self, path, *, start: int, budget: int) -> None:
        budget = integer(budget, "budget")
        self.coordinates(start)
        if len(path) != budget + 1 or path[0] != start:
            raise ValueError("path must contain budget + 1 vertices and begin at start")
        for vertex in path:
            self.coordinates(vertex)
        for source, target in zip(path, path[1:]):
            if target not in self.neighbors(source):
                raise ValueError(f"illegal four-neighbor edge {source} -> {target}")
