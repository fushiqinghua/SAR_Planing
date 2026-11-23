import numpy as np
import pytest

from asar_repro.grid import GridGraph


def test_rectangular_row_major_indices_and_four_neighbors():
    grid = GridGraph(3, 4)
    for v in range(12):
        assert grid.coordinates(v) == divmod(v, 4)
        assert grid.vertex(*grid.coordinates(v)) == v
    assert set(grid.neighbors(0)) == {1, 4}
    assert set(grid.neighbors(3)) == {2, 7}
    assert set(grid.neighbors(5)) == {1, 4, 6, 9}
    assert grid.dist(0, 0) == 0
    assert grid.dist(np.int64(3), 8) == 5
    assert not GridGraph(1, 1).neighbors(0)


@pytest.mark.parametrize("path,start,T", [
    ([0, 5], 0, 1), ([3, 4], 3, 1), ([0, 0], 0, 1),
    ([0, 1], 1, 1), ([0, 1], 0, 2), ([], 0, 0),
    ([0, -1], 0, 1), ([0, 1.0], 0, 1), ([0], 0, -1),
])
def test_reject_invalid_path(path, start, T):
    with pytest.raises(ValueError):
        GridGraph(3, 4).validate_path(path, start=start, budget=T)


def test_grid_bounds():
    with pytest.raises(ValueError):
        GridGraph(0, 1)
    grid = GridGraph(3, 4)
    with pytest.raises(ValueError):
        grid.vertex(0, 4)
    with pytest.raises(ValueError):
        grid.coordinates(-1)
