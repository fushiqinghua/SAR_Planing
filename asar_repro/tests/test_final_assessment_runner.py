"""Small independent checks of node-specific grouping and fixed pair selection."""

import importlib.util
from pathlib import Path
import unittest

import numpy as np

from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path


_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_stdc_final_assessment.py"
_SPEC = importlib.util.spec_from_file_location("stdc_final_assessment_runner", _SCRIPT)
_RUNNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RUNNER)


def _suffixes(grid, start, steps):
    if steps == 0:
        yield (start,)
    else:
        for nxt in grid.neighbors(start):
            for suffix in _suffixes(grid, nxt, steps-1):
                yield (start,)+suffix


def _particle_cost(cells, weights, depth, suffix, q):
    """Independent scalar, per-particle recurrence; never normalize mass."""
    total = 0.
    final = []
    for column, weight in enumerate(weights):
        remaining = float(weight)
        for frame, vertex in enumerate(suffix[1:], depth+1):
            if int(cells[frame, column]) == vertex:
                remaining *= 1.-q
            total += remaining
        final.append(remaining)
    return total, np.asarray(final)


class TestFinalAssessmentRunner(unittest.TestCase):
    def test_interpreter_path_is_normalized_before_environment_comparison(self):
        from unittest.mock import patch
        import os
        with patch.object(_RUNNER.sys, 'executable', '/tmp/example/../venv/bin/python'):
            self.assertEqual(_RUNNER.environment()['executable'],
                             os.path.abspath('/tmp/example/../venv/bin/python'))

    def test_budget_filter_preserves_seed_and_excludes_late_improvement(self):
        seed = dict(J=10., elapsed_s=0., path=[0])
        history = [dict(J=8., elapsed_s=4.9, path=[1]),
                   dict(J=7., elapsed_s=5.00001, path=[2])]
        best, available = _RUNNER.budgeted_incumbents(history, seed, 5.)
        self.assertEqual(best['J'], 8.)
        self.assertEqual(len(available), 2)
        best, _ = _RUNNER.budgeted_incumbents(history, seed, 0.)
        self.assertEqual(best, seed)

    def test_zero_pair_budget_does_not_select_a_pair(self):
        motion = ParticleMotion(np.tile([0, 1], (3, 1)), 2, [10, 20])
        self.assertEqual(_RUNNER.select_pairs(GridGraph(1, 2), motion, np.array([.5, .5]),
                                             0, 2, 2, 0), ([], []))

    def test_all_zero_mass_keeps_a_legal_zero_representative(self):
        motion = ParticleMotion(np.tile([0, 2], (3, 1)), 2, [10, 20])
        _, weights, _ = _RUNNER.exact_future_groups(GridGraph(1, 2), motion,
                                                    np.zeros(2), 0, 2)
        self.assertEqual(float(weights.sum()), 0.)
        self.assertGreater(len(weights), 0)

    def setUp(self):
        self.grid = GridGraph(2, 2)
        self.cells = np.array([
            [0, 3, 1, 2, 0],
            [1, 2, 3, 4, 3],
            [0, 3, 1, 5, 2],
            [2, 2, 1, 6, 0],
            [0, 0, 3, 7, 1],
        ])
        self.motion = ParticleMotion(self.cells, self.grid.size, [17, 31, 43, 59, 71])

    def test_future_identical_different_past_merge_current_weights_without_normalization(self):
        weights = np.array([.02, .11, .07, .05, 0.])
        original = weights.copy()
        grouped, mass, members = _RUNNER.exact_future_groups(
            self.grid, self.motion, weights, depth=2, budget=4)
        self.assertEqual(members, [[2], [0, 1], [3]])
        np.testing.assert_allclose(mass, [.07, .13, .05], rtol=0., atol=1e-15)
        self.assertAlmostEqual(float(mass.sum()), .25)
        self.assertFalse(np.array_equal(self.cells[:3, 0], self.cells[:3, 1]))
        np.testing.assert_array_equal(grouped.cell_ids[3:, 1], self.cells[3:, 0])
        np.testing.assert_array_equal(grouped.trajectory_ids, [43, 17, 59])
        np.testing.assert_array_equal(weights, original)
        # Zero-mass groups are discarded; original membership/ID order is stable.
        repeated = _RUNNER.exact_future_groups(self.grid, self.motion, weights, 2, 4)
        self.assertEqual(repeated[2], members)
        np.testing.assert_array_equal(repeated[0].trajectory_ids, grouped.trajectory_ids)
        np.testing.assert_array_equal(repeated[1], mass)

    def test_every_legal_suffix_matches_original_full_path_and_independent_particle_score(self):
        initial = np.array([.3, .2, .15, .35, 0.])
        prefix = (0, 1, 3)
        checked = 0
        for q in (0., .78, 1.):
            for suffix in _suffixes(self.grid, prefix[-1], 2):
                route = prefix+suffix[1:]
                scored = score_path(self.grid, route, start=0, budget=4,
                                    p=initial, q=q, motion=self.motion,
                                    record_beliefs=True)
                current = scored.beliefs[2]
                grouped, weights, members = _RUNNER.exact_future_groups(
                    self.grid, self.motion, current, 2, 4)
                original_cost, original_final = _particle_cost(
                    self.cells, current, 2, suffix, q)
                grouped_cost, grouped_final = _particle_cost(
                    grouped.cell_ids, weights, 2, suffix, q)
                self.assertAlmostEqual(original_cost, scored.J-scored.g[2], delta=1e-12)
                self.assertAlmostEqual(grouped_cost, original_cost, delta=1e-12)
                np.testing.assert_allclose(
                    grouped_final,
                    [original_final[columns].sum() for columns in members],
                    rtol=0., atol=1e-12)
                checked += 1
        self.assertEqual(checked, 12)

    def test_special_bins_contribute_no_searchable_distance(self):
        grid = GridGraph(1, 4)
        motion = ParticleMotion([[0, 3, 7], [0, 3, 7], [7, 7, 0]], 4, [1, 2, 3])
        pairs, records = _RUNNER.select_pairs(
            grid, motion, np.array([.1, .1, .7]), 0, 2, top_groups=3, max_pairs=2)
        # The high-mass third column is never in-grid at the same time as
        # another column.  Special-bin IDs must not become geometric positions.
        self.assertEqual(pairs, [(0, 1)])
        self.assertEqual(records[0]["separation"], 3.)
        self.assertAlmostEqual(records[0]["score"], .6)
        self.assertAlmostEqual(records[0]["mass"], .2)

    def test_pair_selection_is_disjoint_and_ties_have_stable_column_order(self):
        grid = GridGraph(2, 2)
        motion = ParticleMotion([[0, 1, 2, 3]]*3, 4, [40, 30, 20, 10])
        weights = np.full(4, .1)
        for _ in range(3):
            pairs, records = _RUNNER.select_pairs(
                grid, motion, weights, 0, 2, top_groups=4, max_pairs=2)
            self.assertEqual(pairs, [(0, 3), (1, 2)])
            self.assertEqual(len({i for pair in pairs for i in pair}), 2*len(pairs))
            self.assertEqual([item["pair"] for item in records], [[0, 3], [1, 2]])
        limited, _ = _RUNNER.select_pairs(
            grid, motion, weights, 0, 2, top_groups=3, max_pairs=2)
        self.assertEqual(limited, [(1, 2)])


if __name__ == "__main__":
    unittest.main()
