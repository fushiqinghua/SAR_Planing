"""Independent route/score and mechanism checks for bounded event proposals."""
import unittest

import numpy as np

from asar_repro.final_event_candidates import search_event_candidates
from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path


def independent_score(path, p, q, cells, size):
    weights = np.array(p, dtype=float, copy=True)
    sensor = np.broadcast_to(np.asarray(q), (size,))
    cost = 0.
    for t in range(1, len(path)):
        for i in range(len(weights)):
            if cells[t, i] == path[t]:
                weights[i] *= 1-sensor[path[t]]
        cost += float(sum(weights))
    return cost, 1-float(sum(weights))


def all_routes(grid, start, budget):
    if budget == 0:
        yield (start,)
    else:
        for path in all_routes(grid, start, budget-1):
            for nxt in grid.neighbors(path[-1]):
                yield path+(nxt,)


class TestFinalEventCandidates(unittest.TestCase):
    def test_root_release_crosses_zero_reward_transit_and_changes_order(self):
        grid = GridGraph(1, 12)
        cells = np.tile([0, 11], (18, 1))
        motion = ParticleMotion(cells, grid.size, [91, 7])
        cfg = dict(start=5, budget=17, p=[.6, .4], q=1., motion=motion)
        initial = tuple(range(5, 12))+tuple(range(10, -1, -1))
        self.assertAlmostEqual(score_path(grid, initial, **cfg).J, 11.6)
        result = search_event_candidates(grid, **cfg, initial_path=initial,
            event_sequences=[[(0, 5), (11, 16)]], max_seconds=2.)
        self.assertAlmostEqual(result.J, 8.4)
        self.assertEqual(result.Pd, 1.)
        self.assertEqual(result.path[1], 4)
        self.assertEqual(result.stats["complete_candidates"], 2)
        self.assertEqual(result.stats["early_divergence_candidates"], 2)
        self.assertTrue(all(r["first_divergence"] == 1 for r in result.candidate_archive))
        self.assertTrue(all(r["hard_events_satisfied"] for r in result.candidate_archive))
        self.assertEqual(result.stats["protected_prefix_length"], 0)
        self.assertFalse(result.theory_certified)

    def test_automatic_events_find_the_root_release_witness(self):
        grid = GridGraph(1, 12)
        motion = ParticleMotion(np.tile([0, 11], (18, 1)), grid.size, [91, 7])
        initial = tuple(range(5, 12))+tuple(range(10, -1, -1))
        result = search_event_candidates(grid, start=5, budget=17, p=[.6,.4], q=1.,
            motion=motion, initial_path=initial, max_seconds=2.)
        self.assertAlmostEqual(result.J, 8.4)
        self.assertLessEqual(result.stats["complete_candidates"], 24)
        self.assertGreater(result.stats["unique_new_routes"], 0)
        self.assertTrue(any("then" in f for f in result.stats["generated_event_families"]))
        for candidate in result.candidate_archive:
            self.assertAlmostEqual(sum(c["detected_mass"] for c in candidate["actual_cluster_detections"]),
                                   candidate["Pd"])

    def test_local_windows_cannot_find_that_witness(self):
        grid = GridGraph(1, 12)
        cells = np.tile([0, 11], (18, 1))
        initial = tuple(range(5, 12))+tuple(range(10, -1, -1))
        cost = independent_score(initial, [.6, .4], 1., cells, grid.size)[0]
        replacements = 0
        for a in range(17):
            for length in range(1, min(10, 17-a)+1):
                for window in all_routes(grid, initial[a], length):
                    if window[-1] == initial[a+length]:
                        replacements += 1
                        route = initial[:a]+window+initial[a+length+1:]
                        score = independent_score(route, [.6,.4], 1., cells, grid.size)[0]
                        self.assertGreaterEqual(score+1e-10, cost)
        self.assertEqual(replacements, 1884)

    def test_random_small_dynamic_archive_replay_and_global_oracle_lower_bound(self):
        grid = GridGraph(2, 3)
        routes = list(all_routes(grid, 0, 5))
        for seed in range(12):
            with self.subTest(seed=seed):
                rng = np.random.default_rng(seed+3201)
                cells = rng.integers(0, grid.size+4, size=(6, 5))
                p = rng.dirichlet(np.ones(5))
                q = rng.choice([0., .78, 1.], size=grid.size)
                motion = ParticleMotion(cells, grid.size, [93, 1, 45, 17, 29])
                original_cells, original_p = cells.copy(), p.copy()
                initial = routes[seed]
                result = search_event_candidates(grid, start=0, budget=5, p=p, q=q,
                    motion=motion, initial_path=initial, max_seconds=2.)
                costs = [independent_score(route, p, q, cells, grid.size)[0] for route in routes]
                self.assertGreaterEqual(result.J+1e-10, min(costs))
                self.assertLessEqual(result.J, independent_score(initial, p, q, cells, grid.size)[0]+1e-10)
                for item in result.candidate_archive:
                    grid.validate_path(item["path"], start=0, budget=5)
                    expected = independent_score(item["path"], p, q, cells, grid.size)
                    self.assertAlmostEqual(item["J"], expected[0], places=12)
                    self.assertAlmostEqual(item["Pd"], expected[1], places=12)
                    self.assertTrue(all(item["path"][t] == v for v,t in item["events"]))
                columns = [i for record in result.stats["cluster_records"] for i in record["particle_columns"]]
                self.assertEqual(len(columns), len(set(columns)))
                np.testing.assert_array_equal(motion.cell_ids, original_cells)
                np.testing.assert_array_equal(p, original_p)

    def test_special_mass_time_zero_and_absolute_dynamic_times(self):
        grid = GridGraph(1, 3)
        # Particle 0 is at the starting cell only at frame zero: it must not
        # be detected there. Particle 2 remains outside and retains its mass.
        cells = np.array([[0,2,3], [2,1,3], [1,2,3], [0,1,3]])
        motion = ParticleMotion(cells, grid.size, [1,8,4])
        cfg = dict(start=0, budget=3, p=[.2,.5,.3], q=1., motion=motion)
        result = search_event_candidates(grid, **cfg, initial_path=(0,1,0,1),
            event_sequences=[[(2,2)]], max_seconds=2.)
        for item in result.candidate_archive:
            score = score_path(grid, item["path"], **cfg)
            self.assertAlmostEqual(score.final_belief[2], .3)
            self.assertEqual(score.survival[0], 1.)
            expected = independent_score(item["path"], cfg["p"], 1., cells, grid.size)
            self.assertAlmostEqual(item["J"], expected[0])
        self.assertLessEqual(result.Pd, .7+1e-10)

    def test_zero_sensor_and_all_special_have_no_invented_gain(self):
        grid = GridGraph(1, 2)
        for cells, q in [(np.tile([0,1], (4,1)), 0.),
                         (np.tile([2,3], (4,1)), 1.)]:
            motion = ParticleMotion(cells, 2, [2,9])
            result = search_event_candidates(grid, start=0, budget=3, p=[.4,.6], q=q,
                motion=motion, initial_path=(0,1,0,1), max_seconds=2.)
            self.assertEqual(result.J, 3.)
            self.assertEqual(result.Pd, 0.)
            self.assertEqual(result.stats["complete_candidates"], 0)
            self.assertIsNone(result.stats["duplicate_fraction"])

    def test_deadline_zero_preserves_paid_initial_route(self):
        grid = GridGraph(1, 2)
        motion = ParticleMotion(np.tile([1], (4,1)), 2, [7])
        result = search_event_candidates(grid, start=0, budget=3, p=[1.], q=.78,
            motion=motion, initial_path=(0,1,0,1), max_seconds=0.)
        self.assertEqual(result.status, "budget_exceeded")
        self.assertEqual(result.stop_reason, "max_seconds")
        self.assertEqual(result.path, (0,1,0,1))
        self.assertEqual(result.stats["complete_candidates"], 0)
        self.assertEqual(result.stats["initial_replays"], 1)
        self.assertGreaterEqual(result.stats["deadline_overshoot_s"], 0.)

    def test_cap_duplicates_and_explicit_events(self):
        grid = GridGraph(1, 2)
        motion = ParticleMotion(np.tile([1], (4,1)), 2, [7])
        result = search_event_candidates(grid, start=0, budget=3, p=[1.], q=.78,
            motion=motion, initial_path=(0,1,0,1), max_candidates=3,
            event_sequences=[[(1,1)],[(1,3)]], max_seconds=2.)
        self.assertEqual(result.stats["complete_candidates"], 3)
        self.assertEqual(result.stats["unique_complete_candidates"], 1)
        self.assertEqual(result.stats["duplicate_candidates"], 2)
        self.assertEqual(result.stats["equals_initial_candidates"], 3)
        self.assertEqual(result.stats["unique_new_routes"], 0)

    def test_invalid_event_times_and_parity_are_rejected(self):
        grid = GridGraph(1, 3)
        motion = ParticleMotion(np.tile([2], (4,1)), 3, [7])
        cfg = dict(start=0, budget=3, p=[1.], q=.78, motion=motion,
                   initial_path=(0,1,2,1), max_seconds=2.)
        for sequence in [[(0,1)],[(1,0)],[(2,4)],[(1,1),(2,1)],[],[(1,1),(2,2),(1,3)]]:
            with self.subTest(sequence=sequence), self.assertRaises(ValueError):
                search_event_candidates(grid, **cfg, event_sequences=[sequence])

    def test_single_vertex_zero_horizon_and_zero_candidate_cap(self):
        grid = GridGraph(1,1)
        motion = ParticleMotion([[0]], 1, [17])
        result = search_event_candidates(grid, start=0, budget=0, p=[1.], q=1.,
                                         motion=motion, initial_path=(0,))
        self.assertEqual(result.J, 0.)
        self.assertEqual(result.Pd, 0.)
        self.assertEqual(result.stats["complete_candidates"], 0)
        grid = GridGraph(1,2)
        motion = ParticleMotion([[0],[1]], 2, [17])
        result = search_event_candidates(grid, start=0, budget=1, p=[1.], q=1.,
            motion=motion, initial_path=(0,1), max_candidates=0)
        self.assertEqual(result.J, 0.)
        self.assertEqual(result.stats["complete_candidates"], 0)

    def test_cap_and_numeric_validation(self):
        grid = GridGraph(1,2)
        motion = ParticleMotion([[0],[1]], 2, [17])
        cfg = dict(start=0, budget=1, p=[1.], q=1., motion=motion, initial_path=(0,1))
        for changes in [dict(max_candidates=25),dict(max_clusters=4),dict(max_seconds=-1),
                        dict(max_seconds=float("nan")),dict(max_candidates=True)]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                search_event_candidates(grid, **cfg, **changes)


if __name__ == "__main__":
    unittest.main()
