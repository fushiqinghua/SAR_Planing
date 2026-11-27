"""Local correctness gate for the new route solvers; not a performance study.

These tests are committed without being executed in the preparation session.
They use fixed work limits or controlled clocks, never assert a speed advantage.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path
from asar_repro.route_optimizers import solve_cem, solve_ils


MODULE = "asar_repro.route_optimizers"


class RouteOptimizerContractTests(unittest.TestCase):
    def test_original_mass_timing_special_bins_and_input_immutability(self):
        grid = GridGraph(1, 3)
        cells = np.tile([0, 2, 3], (3, 1))  # third particle is unsearchable
        motion = ParticleMotion(cells, grid.size, np.arange(3))
        p = np.array([0.5, 0.3, 0.2])
        before_p, before_cells = p.copy(), motion.cell_ids.copy()
        for solver in (solve_ils, solve_cem):
            with self.subTest(solver=solver.__name__):
                result = solver(grid, start=1, budget=2, p=p, q=0.78, motion=motion,
                                initial_path=[1, 0, 1], max_seconds=60, seed=7,
                                options={"max_evaluations": 1})
                self.assertAlmostEqual(result["J"], 1.22)
                self.assertAlmostEqual(result["pd_final"], 0.39)
                np.testing.assert_allclose(result["survival"], [1.0, 0.61, 0.61])
                self.assertEqual(result["stop_reason"], "max_evaluations")
                np.testing.assert_array_equal(p, before_p)
                np.testing.assert_array_equal(motion.cell_ids, before_cells)

    def test_every_cem_sample_is_a_complete_legal_path_and_replays(self):
        grid = GridGraph(2, 3)
        cells = np.array([[0, 5], [1, 4], [2, 3], [5, 0],
                          [4, 1], [3, 2], [0, 5]])
        motion = ParticleMotion(cells, grid.size, [10, 11])
        cfg = dict(start=0, budget=6, p=[0.6, 0.4], q=0.78, motion=motion)
        evaluated = []

        def audit_score(g, path, **kwargs):
            evaluated.append(tuple(path))
            return score_path(g, path, **kwargs)

        with patch(MODULE + ".score_path", side_effect=audit_score):
            result = solve_cem(grid, **cfg, initial_path=[0, 1, 2, 5, 4, 3, 0],
                               max_seconds=60, seed=12,
                               options={"population": 8, "components": 2,
                                        "max_generations": 2, "trace_limit": 1})
        self.assertEqual(len(evaluated), 17)  # initial + 2 total populations of 8
        self.assertEqual(result["stats"]["samples_scored"], 16)
        self.assertEqual(result["stats"]["component_updates"], 4)
        self.assertEqual(result["stats"]["trace_dropped"], 16)
        for path in evaluated:
            grid.validate_path(path, start=0, budget=6)
        for row in result["history"]:
            replay = score_path(grid, row["path"], **cfg)
            self.assertAlmostEqual(row["J"], replay.J)
            self.assertAlmostEqual(row["pd_final"], replay.pd_final)
        self.assertTrue(all(b["J"] < a["J"] - 1e-10
                            for a, b in zip(result["history"], result["history"][1:])))

    def test_ils_can_cross_a_worse_state_without_losing_best(self):
        grid = GridGraph(1, 3)
        motion = ParticleMotion(np.tile([0, 2], (5, 1)), grid.size, [0, 1])
        initial = [1, 0, 1, 0, 1]  # J=0.8
        worse = [1, 2, 1, 2, 1]    # J=3.2
        better = [1, 0, 1, 2, 1]   # J=0.4
        cfg = dict(start=1, budget=4, p=[0.8, 0.2], q=1.0, motion=motion)
        with patch(MODULE + "._make_ils_proposal", side_effect=[tuple(worse), tuple(better)]), \
             patch(MODULE + ".np.random.default_rng", return_value=SimpleNamespace(random=lambda: 0.0)):
            result = solve_ils(grid, **cfg, initial_path=initial,
                               max_seconds=60, seed=0,
                               options={"max_iterations": 2, "polish_trials": 0,
                                        "temperature_fraction": 1.0,
                                        "temperature_final_ratio": 1.0})
        self.assertEqual(result["path"], better)
        self.assertEqual(result["stats"]["accepted_worse"], 1)
        self.assertEqual(result["stats"]["worse_lineages_with_best"], 1)
        np.testing.assert_allclose([row["J"] for row in result["history"]], [0.8, 0.4])

    def test_score_completed_after_deadline_is_excluded(self):
        grid = GridGraph(1, 2)
        motion = ParticleMotion([[1], [1]], grid.size, [0])
        for solver in (solve_ils, solve_cem):
            clock = SimpleNamespace(value=0.0)

            def slow_score(g, path, **kwargs):
                result = score_path(g, path, **kwargs)
                clock.value = 2.0
                return result

            with self.subTest(solver=solver.__name__), \
                 patch(MODULE + ".perf_counter", side_effect=lambda: clock.value), \
                 patch(MODULE + ".score_path", side_effect=slow_score):
                result = solver(grid, start=0, budget=1, p=[1.0], q=0.78,
                                motion=motion, initial_path=[0, 1], max_seconds=1, seed=1)
            self.assertIsNone(result["path"])
            self.assertIsNone(result["J"])
            self.assertEqual(result["history"], [])
            self.assertEqual(result["stats"]["completed_after_deadline"], 1)
            self.assertEqual(result["stop_reason"], "max_seconds")

    def test_fixed_work_seed_reproducibility_and_nonlocal_operator_cycle(self):
        grid = GridGraph(3, 3)
        cells = np.tile([0, 2, 6, 8], (7, 1))
        motion = ParticleMotion(cells, grid.size, np.arange(4))
        cfg = dict(start=4, budget=6, p=[0.1, 0.4, 0.2, 0.3], q=0.78, motion=motion,
                   initial_path=[4, 1, 0, 3, 6, 7, 8], max_seconds=60, seed=27,
                   options={"max_iterations": 3, "polish_trials": 0})
        first, second = solve_ils(grid, **cfg), solve_ils(grid, **cfg)
        self.assertEqual(first["path"], second["path"])
        self.assertEqual(first["J"], second["J"])
        self.assertEqual(first["stats"]["operator_counts"],
                         {"root_restart": 1, "early_rebuild": 1, "reorder_waypoints": 1})
        self.assertEqual([r["route_hash"] for r in first["candidate_trace"]],
                         [r["route_hash"] for r in second["candidate_trace"]])

    def test_cem_rejects_zero_exploration_and_unknown_options(self):
        grid = GridGraph(1, 2)
        motion = ParticleMotion([[1], [1]], 2, [0])
        cfg = dict(start=0, budget=1, p=[1.0], q=0.78, motion=motion,
                   initial_path=[0, 1], max_seconds=60, seed=1)
        for options in ({"exploration_probability": 0}, {"silently_ignored": True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                solve_cem(grid, **cfg, options=options)


if __name__ == "__main__":
    unittest.main()
