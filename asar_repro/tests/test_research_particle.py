"""Research particle execution/aggregation checked against unchanged scorers."""
import numpy as np
import pytest

from asar_repro.grid import GridGraph
from asar_repro.heuristic import Heuristic
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.research_particle import FutureEquivalentMotion, ParticleGuide


Q_CASES = (0.0, .78, 1.0, (0.0, .3, .78, 1.0))


def case(dynamic=True):
    grid = GridGraph(2, 2)
    columns = np.array([
        [0, 1, 2, 3, 0], [0, 1, 2, 3, 0], [1, 1, 0, 2, 3],
        [6, 6, 1, 2, 3], [5, 5, 5, 5, 5], [6, 6, 1, 2, 3],
        [0, 0, 0, 0, 0], [7, 3, 7, 2, 1], [2, 1, 2, 3, 0], [6, 6, 6, 6, 6],
    ], dtype=np.int64)
    cells = columns.T.copy()
    if not dynamic:
        cells[:] = cells[0]
    p = np.array([.10, .15, .20, .05, .10, .05, .12, .08, .07, .08])
    ids = np.array([f"trajectory-{100+i}" for i in range(len(p))])
    return grid, p, ParticleMotion(cells, grid.size, ids)


def prefixes(grid, start, horizon):
    stack = [(start,)]
    while stack:
        path = stack.pop()
        yield path
        if len(path)-1 < horizon:
            stack.extend(path+(nxt,) for nxt in grid.neighbors(path[-1]))


@pytest.mark.parametrize("dynamic", (False, True))
@pytest.mark.parametrize("q", Q_CASES)
@pytest.mark.parametrize("compressed", (False, True))
@pytest.mark.parametrize("start", (0, 3))
def test_guide_every_legal_prefix_matches_reference_without_mutation(dynamic, q, compressed, start):
    grid, p, original = case(dynamic)
    motion = FutureEquivalentMotion(original, p) if compressed else original
    initial = motion.initial_weights if compressed else p
    fast = ParticleGuide(grid, budget=4, q=q, motion=motion)
    reference = Heuristic(grid, budget=4, q=q, motion=motion, mode="paper_greedy")
    cells_before = motion.cell_ids.copy()
    p_before, q_before = initial.copy(), np.asarray(q).copy()
    for path in prefixes(grid, start, 4):
        score = score_path(grid, path, start=start, budget=len(path)-1, p=initial, q=q, motion=motion)
        b = score.final_belief
        before = b.copy()
        flags_before = b.flags.writeable
        expected_choices, actual_choices = [], []
        expected = reference(path[-1], len(path)-1, b, choices=expected_choices)
        actual = fast(path[-1], len(path)-1, b, choices=actual_choices)
        assert actual == expected
        assert actual_choices == expected_choices
        np.testing.assert_array_equal(b, before)
        assert b.flags.writeable == flags_before
    assert not fast.used_fallback
    np.testing.assert_array_equal(motion.cell_ids, cells_before)
    np.testing.assert_array_equal(initial, p_before)
    np.testing.assert_array_equal(np.asarray(q), q_before)


@pytest.mark.parametrize("dynamic", (False, True))
@pytest.mark.parametrize("q", Q_CASES)
@pytest.mark.parametrize("start", (0, 3))
def test_compression_complete_paths_and_all_prefixes_replay_original_ids(dynamic, q, start):
    grid, p, original = case(dynamic)
    grouped = FutureEquivalentMotion(original, p)
    for path in prefixes(grid, start, 4):
        cfg = dict(start=start, budget=len(path)-1, q=q)
        a = score_path(grid, path, p=p, motion=original, **cfg)
        b = score_path(grid, path, p=grouped.initial_weights, motion=grouped, **cfg)
        assert abs(a.J-b.J) <= 1e-12
        assert abs(a.pd_final-b.pd_final) <= 1e-12
        np.testing.assert_allclose(a.survival, b.survival, atol=1e-12, rtol=0)
        np.testing.assert_allclose(grouped.aggregate_weights(a.final_belief), b.final_belief, atol=1e-12, rtol=0)
        np.testing.assert_allclose(grouped.expand_weights(b.final_belief), a.final_belief, atol=1e-12, rtol=0)
        if len(path) > 1:
            assert not b.final_belief.flags.writeable


@pytest.mark.parametrize("q", Q_CASES)
def test_matrix_motion_fallback_keeps_dynamic_absolute_clock(q):
    grid = GridGraph(2, 2)
    kernel = np.arange(1, 17, dtype=float).reshape(4, 4)
    kernel /= kernel.sum(axis=1, keepdims=True)
    motion = MatrixMotion.time_varying([np.roll(kernel, t, axis=1) for t in range(4)])
    p = np.array([.1, .2, .3, .4])
    guide = ParticleGuide(grid, budget=4, q=q, motion=motion)
    ref = Heuristic(grid, budget=4, q=q, motion=motion, mode="paper_greedy")
    for path in prefixes(grid, 0, 4):
        b = score_path(grid, path, start=0, budget=len(path)-1, p=p, q=q, motion=motion).final_belief
        left, right = [], []
        assert guide(path[-1], len(path)-1, b, choices=left) == ref(path[-1], len(path)-1, b, choices=right)
        assert left == right
    assert guide.used_fallback


def test_guide_ties_are_ascending_and_greedy_steps_need_not_be_contiguous():
    grid = GridGraph(1, 3)
    motion = ParticleMotion(np.array([[0, 1, 2]]*3), 3, [100, 101, 102])
    choices = []
    guide = ParticleGuide(grid, budget=2, q=1.0, motion=motion)
    assert guide(1, 0, np.array([.5, 0., .5]), choices=choices) == .5
    assert choices == [0, 2]
    assert 2 not in grid.neighbors(0)  # Algorithm 2 deliberately allows this.


def test_group_membership_preserves_actual_ids_initial_distribution_and_frame_zero():
    grid, p, motion = case()
    cells_before, ids_before, weights_before = motion.cell_ids.copy(), motion.trajectory_ids.copy(), p.copy()
    grouped = FutureEquivalentMotion(motion, p)
    assert grouped.state_size == 8
    assert grouped.particle_to_group[0] == grouped.particle_to_group[1]
    assert grouped.particle_to_group[3] == grouped.particle_to_group[5]
    assert grouped.particle_to_group[0] != grouped.particle_to_group[8]  # Only frame 0 differs.
    assert grouped.particle_to_group[4] != grouped.particle_to_group[9]  # Preserve distinct special labels.
    for index, members in enumerate(grouped.groups):
        np.testing.assert_array_equal(grouped.group_trajectory_ids[index], motion.trajectory_ids[members])
        np.testing.assert_array_equal(grouped.cell_ids[:, index], motion.cell_ids[:, members[0]])
        assert grouped.trajectory_ids[index] == motion.trajectory_ids[members[0]]
    for t in range(5):
        np.testing.assert_allclose(grouped.cell_mass(grouped.initial_weights, t),
                                   motion.cell_mass(p, t), atol=1e-12, rtol=0)
    np.testing.assert_allclose(grouped.expand_weights(grouped.initial_weights), p, atol=1e-12, rtol=0)
    assert grouped.compression_stats["compression_ratio"] == 10/8
    assert grouped.compression_stats["grouped_state_bytes"] == 8*8
    assert grouped.original_motion is motion
    for array in (grouped.initial_weights, grouped.particle_to_group, grouped.original_initial_weights,
                  grouped.original_trajectory_ids, *grouped.groups, *grouped.group_trajectory_ids):
        assert not array.flags.writeable
    np.testing.assert_array_equal(motion.cell_ids, cells_before)
    np.testing.assert_array_equal(motion.trajectory_ids, ids_before)
    np.testing.assert_array_equal(p, weights_before)


def test_special_bins_can_return_and_are_not_dropped_or_sensed_early():
    grid = GridGraph(1, 2)
    motion = ParticleMotion(np.array([[2, 2, 3], [2, 2, 3], [1, 1, 3]]), 2, [10, 11, 12])
    p = np.array([.2, .3, .5])
    grouped = FutureEquivalentMotion(motion, p)
    score = score_path(grid, (1, 0, 1), start=1, budget=2, p=grouped.initial_weights, q=1., motion=grouped)
    np.testing.assert_array_equal(score.survival, [1., 1., .5])
    assert score.J == 1.5 and score.pd_final == .5
    np.testing.assert_array_equal(grouped.expand_weights(score.final_belief), [0., 0., .5])


def test_no_identical_full_signatures_reports_no_compression():
    original = ParticleMotion(np.array([[0, 1, 2], [1, 2, 0]]), 3, [100, 200, 300])
    grouped = FutureEquivalentMotion(original, [.2, .3, .5])
    assert grouped.state_size == original.state_size
    assert grouped.compression_stats["compression_ratio"] == 1.0
    assert grouped.compression_stats["reduction_fraction"] == 0.0
    np.testing.assert_array_equal(grouped.initial_weights, [.2, .3, .5])


def test_expand_weights_retains_zero_initial_members_and_rejects_unreachable_mass():
    original = ParticleMotion(np.array([[0, 0, 1], [1, 1, 0]]), 2, [5, 7, 9])
    grouped = FutureEquivalentMotion(original, [0., 1., 0.])
    np.testing.assert_array_equal(grouped.expand_weights([.5, 0.]), [0., .5, 0.])
    with pytest.raises(ValueError, match="initial proportions"):
        grouped.expand_weights([.5, .1])
    with pytest.raises(ValueError):
        grouped.expand_weights([1.01, 0.])


def test_readonly_noop_belief_sharing_and_writable_alias_safety():
    _, p, motion = case()
    grouped = FutureEquivalentMotion(motion, p)
    readonly = grouped.initial_weights
    before = readonly.copy()
    assert grouped.sense(readonly, 0, np.zeros(4), 1) is readonly
    writable = readonly.copy()
    posterior = grouped.sense(writable, 0, np.zeros(4), 1)
    assert not posterior.flags.writeable and not np.shares_memory(posterior, writable)
    writable[:] = 0
    np.testing.assert_array_equal(posterior, before)
    changed = grouped.sense(readonly, 1, np.ones(4), 1)
    assert not changed.flags.writeable and not np.shares_memory(changed, readonly)
    np.testing.assert_array_equal(readonly, before)
    zero_hits = readonly.copy()
    zero_hits[grouped.cell_ids[1] == 1] = 0
    zero_hits.setflags(write=False)
    assert grouped.sense(zero_hits, 1, np.ones(4), 1) is zero_hits


def test_guide_terminal_zero_and_validation_errors():
    grid, p, motion = case()
    guide = ParticleGuide(grid, budget=4, q=.78, motion=motion)
    assert guide(0, 4, None) == 0.0  # Same terminal convention as Heuristic.
    with pytest.raises(ValueError):
        guide(0, 5, p)
    with pytest.raises(ValueError):
        guide(0, -1, p)
    with pytest.raises(ValueError):
        guide(9, 0, p)
    with pytest.raises(ValueError):
        guide(0, 0, [-1.]+[0.]*9)
    with pytest.raises(ValueError):
        ParticleGuide(grid, budget=5, q=.78, motion=motion)
    with pytest.raises(ValueError):
        ParticleGuide(GridGraph(1, 3), budget=4, q=.78, motion=motion)
    with pytest.raises(ValueError):
        ParticleGuide(grid, budget=4, q=1.1, motion=motion)


@pytest.mark.parametrize("weights", ([1., 0.], [0.]*10, [-.1]+[1.1]+[0.]*8))
def test_compression_rejects_invalid_initial_weights(weights):
    _, _, motion = case()
    with pytest.raises(ValueError):
        FutureEquivalentMotion(motion, weights)


def test_compression_rejects_matrix_and_nested_particle_aggregation():
    with pytest.raises(ValueError, match="requires ParticleMotion"):
        FutureEquivalentMotion(MatrixMotion.identity(2), [.5, .5])
    _, p, motion = case()
    grouped = FutureEquivalentMotion(motion, p)
    with pytest.raises(ValueError, match="nested compression"):
        FutureEquivalentMotion(grouped, grouped.initial_weights)
