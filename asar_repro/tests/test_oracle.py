import pytest

from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion
from asar_repro.oracle import enumerate_oracle


def test_full_binary_tree_and_all_ties():
    result = enumerate_oracle(GridGraph(2, 2), start=0, budget=4, p=[1, 0, 0, 0],
                              q=0, motion=MatrixMotion.identity(4))
    assert result.J == 4
    assert result.expanded == 15
    assert result.generated == 30
    assert result.complete_paths == len(set(result.tied_paths)) == 16
    for path in result.tied_paths:
        GridGraph(2, 2).validate_path(path, start=0, budget=4)


def test_tolerance_groups_paths_but_preserves_exact_minimum():
    result = enumerate_oracle(GridGraph(2, 2), start=0, budget=1,
                              p=[0, 0.5 - 2e-13, 0.5 + 2e-13, 0],
                              q=1, motion=MatrixMotion.identity(4))
    assert result.path == (0, 2)
    assert set(result.tied_paths) == {(0, 1), (0, 2)}
    assert result.J < 0.5


@pytest.mark.parametrize("shape,T", [((1, 17), 1), ((2, 2), 9)])
def test_small_grid_guard(shape, T):
    with pytest.raises(ValueError, match="16 vertices"):
        enumerate_oracle(GridGraph(*shape), start=0, budget=T, p=[], q=0,
                         motion=MatrixMotion.identity(1))
