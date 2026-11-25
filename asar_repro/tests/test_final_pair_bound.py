"""Independent enumerated-suffix checks for the limited pair-bound diagnostic."""
import unittest
from unittest.mock import patch

import numpy as np

from asar_repro.final_pair_bound import pair_shared_bound, partition_pair_bound
from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.stdc_heuristic import STDCHeuristic


def paths(grid, start, steps):
    if steps == 0:
        yield (start,)
    else:
        for nxt in grid.neighbors(start):
            for suffix in paths(grid, nxt, steps-1):
                yield (start,)+suffix


def direct_cost(path, depth, weights, cells, q):
    """No DP tables, heuristic, source scorer, or normalization."""
    b = np.array(weights, dtype=float, copy=True)
    total = 0.
    for t, v in enumerate(path[1:], start=depth+1):
        b[cells[t] == v] *= 1.-q
        total += float(b.sum())
    return total, b


class TestSharedPairBound(unittest.TestCase):
    def assertClose(self, a, b):
        self.assertAlmostEqual(a, b, delta=1e-10)

    def test_path_coupling_strictly_strengthens_both_singleton_and_stdc(self):
        grid = GridGraph(1, 4)
        motion = ParticleMotion([[0, 3]]*3, 4, [71, 97])
        cfg = dict(vertex=1, depth=0, budget=2, q=.78,
                   motion=motion, belief=[.5, .5])
        item = pair_shared_bound(grid, **cfg, pair=(0, 1))
        self.assertEqual(item.status, "completed")
        self.assertClose(item.bound, 1.22)
        self.assertClose(item.independent_bound, .83)
        self.assertClose(item.coupling_gain, .39)
        self.assertEqual(item.stats["trajectory_ids"], [71, 97])
        grouped = partition_pair_bound(grid, **cfg, pairs=[(0, 1)])
        self.assertClose(grouped.full_stdc_bound, .83)
        self.assertClose(grouped.grouped_bound, 1.22)
        self.assertClose(grouped.bound, 1.22)
        self.assertFalse(grouped.stats["all_singleton_dominance_claim"])

    def test_random_dynamic_all_prefixes_exact_pair_and_admissible_partition(self):
        checked = 0
        for seed in [42, 1059, 20261125]:
            rng = np.random.default_rng(seed)
            grid, T, N = GridGraph(2, 2), 4, 6
            cells = rng.integers(0, grid.size+4, (T+1, N))
            # A permanent special bin must keep its current mass throughout.
            cells[:, -1] = grid.size+3
            motion = ParticleMotion(cells, grid.size, np.arange(N)*5+17)
            p = rng.dirichlet(np.ones(N))
            for q in [0., .78, 1.]:
                prefixes = {route[:d+1] for route in paths(grid, 0, T)
                            for d in range(T+1)}
                for prefix in prefixes:
                    d, v = len(prefix)-1, prefix[-1]
                    _, b = direct_cost(prefix, 0, p, cells, q)
                    original = b.copy()
                    suffixes = list(paths(grid, v, T-d))
                    pair_weights = b.copy()
                    pair_weights[2:] = 0.
                    pair_oracle = min(direct_cost(s, d, pair_weights, cells, q)[0]
                                      for s in suffixes)
                    full_oracle = min(direct_cost(s, d, b, cells, q)[0]
                                      for s in suffixes)
                    single = 0.
                    for i in [0, 1]:
                        w = np.zeros(N)
                        w[i] = b[i]
                        single += min(direct_cost(s, d, w, cells, q)[0]
                                      for s in suffixes)
                    cfg = dict(vertex=v, depth=d, budget=T, q=q,
                               motion=motion, belief=b)
                    pair = pair_shared_bound(grid, **cfg, pair=(0, 1))
                    self.assertClose(pair.bound, pair_oracle)
                    self.assertClose(pair.independent_bound, single)
                    grouped = partition_pair_bound(grid, **cfg,
                                                   pairs=[(0, 1), (2, 3)])
                    self.assertEqual(grouped.status, "completed")
                    self.assertGreaterEqual(grouped.bound, -1e-10)
                    self.assertLessEqual(grouped.bound, full_oracle+1e-10)
                    self.assertGreaterEqual(grouped.bound+1e-10,
                                            grouped.full_stdc_bound)
                    self.assertTrue(np.array_equal(b, original))
                    checked += 1
        self.assertEqual(checked, 279)

    def test_weights_are_path_dependent_not_cached_by_vertex_time(self):
        grid = GridGraph(1, 4)
        motion = ParticleMotion([[0, 3]]*3, 4, [9, 10])
        cfg = dict(vertex=1, depth=0, budget=2, q=.78,
                   motion=motion, pair=(0, 1))
        left = pair_shared_bound(grid, **cfg, belief=[.9, .1])
        right = pair_shared_bound(grid, **cfg, belief=[.1, .9])
        self.assertClose(left.bound, .596)
        self.assertClose(right.bound, 1.298)
        small = pair_shared_bound(grid, **cfg, belief=[.09, .01])
        self.assertClose(small.bound, left.bound*.1)

    def test_absolute_frame_and_no_t0_detection(self):
        grid = GridGraph(1, 3)
        cells = np.array([[0, 0], [2, 1], [0, 2], [1, 0]])
        motion = ParticleMotion(cells, 3, [33, 49])
        for d, v, b in [(0, 0, [.8, .2]), (1, 1, [.4, .04]),
                        (2, 0, [.2, .1])]:
            item = pair_shared_bound(grid, vertex=v, depth=d, budget=3,
                                     q=.78, motion=motion, belief=b, pair=(0, 1))
            oracle = min(direct_cost(p, d, b, cells, .78)[0]
                         for p in paths(grid, v, 3-d))
            self.assertClose(item.bound, oracle)

    def test_special_mass_zero_mass_and_zero_horizon(self):
        grid = GridGraph(1, 2)
        motion = ParticleMotion([[2, 5]]*5, 2, [1, 2])
        for q in [0, .78, 1]:
            cfg = dict(vertex=0, depth=1, budget=4, q=q, motion=motion,
                       pair=(0, 1))
            self.assertClose(pair_shared_bound(grid, **cfg, belief=[.2, .3]).bound, 1.5)
            self.assertEqual(pair_shared_bound(grid, **cfg, belief=[0, 0]).bound, 0.)
        terminal = pair_shared_bound(grid, vertex=0, depth=4, budget=4,
                                     q=.78, motion=motion, belief=[.2, .3], pair=(0, 1))
        self.assertEqual(terminal.bound, 0.)

    def test_infeasible_no_wait_graph(self):
        grid = GridGraph(1, 1)
        motion = ParticleMotion([[0, 1]]*3, 1, [1, 2])
        cfg = dict(vertex=0, depth=0, budget=2, q=1., motion=motion, belief=[0, 0])
        item = pair_shared_bound(grid, **cfg, pair=(0, 1))
        self.assertEqual(item.status, "infeasible")
        self.assertIsNone(item.bound)
        self.assertEqual(partition_pair_bound(grid, **cfg, pairs=[(0, 1)]).status,
                         "infeasible")

    def test_limits_publish_no_partial_bound(self):
        grid = GridGraph(2, 2)
        motion = ParticleMotion([[1, 2]]*10, 4, [1, 2])
        cfg = dict(vertex=0, depth=0, budget=9, q=.78, motion=motion, belief=[.5, .5])
        for limits, reason in [({"max_seconds": 0}, "max_seconds"),
                               ({"max_memory_bytes": 0}, "max_memory_bytes")]:
            item = pair_shared_bound(grid, **cfg, pair=(0, 1), **limits)
            self.assertEqual(item.status, "budget_exceeded")
            self.assertEqual(item.stop_reason, reason)
            self.assertIsNone(item.bound)
            self.assertIsNone(item.independent_bound)
            grouped = partition_pair_bound(grid, **cfg, pairs=[(0, 1)], **limits)
            self.assertEqual(grouped.status, "budget_exceeded")
            self.assertIsNone(grouped.bound)

    def test_mid_computation_time_stop_does_not_publish_partial_table(self):
        grid = GridGraph(2, 2)
        motion = ParticleMotion([[1, 2]]*4, 4, [1, 2])
        ticks = iter(np.arange(1, 1000, dtype=float)*.001)
        with patch("asar_repro.final_pair_bound.perf_counter",
                   side_effect=lambda: next(ticks)):
            item = pair_shared_bound(grid, vertex=0, depth=0, budget=3,
                                     q=.78, motion=motion, belief=[.5, .5],
                                     pair=(0, 1), max_seconds=.017)
        self.assertEqual(item.status, "budget_exceeded")
        self.assertGreater(item.stats["completed_pair_layers"], 0)
        self.assertLess(item.stats["completed_pair_layers"], 3)
        self.assertIsNone(item.bound)
        self.assertIsNone(item.independent_bound)
        self.assertNotIn("raw_pair_value", item.stats)

    def test_nonuniform_q_overlap_and_invalid_indices_rejected(self):
        grid = GridGraph(1, 3)
        motion = ParticleMotion([[0, 1, 2]]*3, 3, [1, 2, 3])
        cfg = dict(vertex=1, depth=0, budget=2, motion=motion, belief=[.2, .3, .5])
        with self.assertRaisesRegex(ValueError, "uniform"):
            pair_shared_bound(grid, **cfg, q=[.78, .77, .78], pair=(0, 1))
        uniform = pair_shared_bound(grid, **cfg, q=[.78]*3, pair=(0, 1))
        self.assertEqual(uniform.status, "completed")
        with self.assertRaisesRegex(ValueError, "disjoint"):
            partition_pair_bound(grid, **cfg, q=.78, pairs=[(0, 1), (1, 2)])
        for pair in [(0, 0), (0, 3), (True, 1), (0, 1, 2)]:
            with self.assertRaises(ValueError):
                pair_shared_bound(grid, **cfg, q=.78, pair=pair)


if __name__ == "__main__":
    unittest.main()
