"""Regenerate the guide Appendix B witness; tests only load the frozen arrays."""

from pathlib import Path

import numpy as np

from asar_repro.grid import GridGraph
from asar_repro.heuristic import Heuristic
from asar_repro.motion import MatrixMotion
from asar_repro.oracle import enumerate_oracle


FIXTURE = Path(__file__).resolve().parents[1] / "data/fixtures/heuristic_dynamic_counterexample.npz"


def main():
    grid = GridGraph(3, 3)
    start, T, q, seed = 4, 4, 0.78, 5
    rng = np.random.default_rng(seed)
    for trial in range(36):  # Trial 35 (zero based) is the guide's published witness.
        p = rng.dirichlet(np.ones(grid.size) * rng.uniform(0.03, 1.0))
        matrices = np.zeros((T, grid.size, grid.size))
        for P in matrices:
            for u in range(grid.size):
                cells = [*sorted(grid.neighbors(u)), u]
                P[u, cells] = rng.dirichlet(np.ones(len(cells)) * rng.uniform(0.1, 2.0))
        motion = MatrixMotion.time_varying(matrices)
        greedy = Heuristic(grid, budget=T, q=q, motion=motion, mode="paper_greedy")
        h = greedy(start, 0, p)
        exact = enumerate_oracle(grid, start=start, budget=T, p=p, q=q, motion=motion)
        if h > exact.J + 1e-8:
            np.testing.assert_allclose([h, exact.J], [2.6170801771, 2.5417333379],
                                       rtol=0, atol=1e-9)
            FIXTURE.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(FIXTURE, p=p, P=matrices, start=start, T=T, q=q,
                                seed=seed, trial=trial)
            print(f"Trial {trial}, h={h:.12f}, exact={exact.J:.12f}, gap={h-exact.J:.12f}")
            return
    raise RuntimeError("Appendix B witness was not reproduced; check NumPy RNG version")


if __name__ == "__main__":
    main()
