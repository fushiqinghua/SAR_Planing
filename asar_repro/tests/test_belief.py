import numpy as np
import pytest
from scipy import sparse

from asar_repro.belief import detect, initial_belief
from asar_repro.motion import MatrixMotion


@pytest.mark.parametrize("bad", [[np.nan, 0], [np.inf, 0], [-0.1, 1.1],
                                 [0, 1.01], [0.4, 0.5], [[0.3, 0.7]], [1]])
def test_invalid_initial_distribution(bad):
    with pytest.raises(ValueError, match="p"):
        initial_belief(bad, 2)


@pytest.mark.parametrize("matrix", [
    [[1.1, -0.1], [0, 1]], [[np.nan, 0], [0, 1]], [[1, 0], [0, 0.9]],
    sparse.csr_matrix([[1, 0], [np.inf, 0]]), [[1, 0, 0], [0, 1, 0]],
    sparse.coo_matrix(([-0.2, 0.2, 1., 1.], ([0, 0, 0, 1], [0, 0, 0, 1])), shape=(2, 2)),
])
def test_invalid_transition(matrix):
    with pytest.raises(ValueError, match="P"):
        MatrixMotion.stationary(matrix)


def test_sparse_transition_conserves_mass_and_sensor_is_local():
    P = sparse.csr_matrix([[0.75, 0.25], [0.5, 0.5]])
    model = MatrixMotion.stationary(P)
    b = np.array([0.2, 0.4])
    prior = model.propagate(b, step=3)
    np.testing.assert_allclose(prior, [0.35, 0.25], atol=1e-15)
    assert prior.sum() == pytest.approx(b.sum())
    posterior = detect(prior, 1, [0, 0.8])
    np.testing.assert_allclose(posterior, [0.35, 0.05])
    assert prior.sum() - posterior.sum() == pytest.approx(0.8 * prior[1])
    np.testing.assert_array_equal(b, [0.2, 0.4])
    assert prior[1] == pytest.approx(0.25)


@pytest.mark.parametrize("q", [[0, np.nan], [-0.1, 0], [1.1, 0], [0.5]])
def test_invalid_sensor_even_on_unvisited_cells(q):
    with pytest.raises(ValueError, match="q"):
        detect(np.array([0.25, 0.75]), 1, q)


def test_time_varying_schedule_bounds_and_shape():
    model = MatrixMotion.time_varying([np.eye(2)])
    for step in (0, 2):
        with pytest.raises(ValueError, match="step"):
            model.propagate([0.5, 0.5], step=step)
    with pytest.raises(ValueError):
        MatrixMotion.time_varying([np.eye(2), np.eye(3)])
    with pytest.raises(ValueError):
        MatrixMotion.time_varying([])
