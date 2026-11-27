"""Physical-model regression specifications; run locally before experiments.

These tests are deliberately separate from the archived discrete model.  They
check the common clock, constant speed, sensor geometry, and scoring contract.
"""

import json
from math import sqrt

import numpy as np
import pytest

from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path
from asar_repro.physical_model import PhysicalProblem, replay


def _problem(horizon=2, positions=None, searchable=None, weights=(1.0,), **overrides):
    if positions is None:
        positions = np.full((horizon + 1, len(weights), 2), 100.0)
    if searchable is None:
        searchable = np.ones(np.asarray(positions).shape[:2], dtype=bool)
    arguments = dict(rows=3, cols=3, cell_width_m=1.0, speed_m_s=1.0,
                     times_s=np.arange(horizon + 1, dtype=float),
                     positions_xy=positions, searchable=searchable,
                     initial_weights=weights, start=4, q=0.78)
    arguments.update(overrides)
    return PhysicalProblem(**arguments)


def test_metric_coordinates_neighbor_sets_and_sqrt_two_duration():
    problem = _problem(cell_width_m=185.2, speed_m_s=20.0,
                       times_s=np.arange(3) * 9.26)
    np.testing.assert_allclose(problem.vertex_xy(0), [-185.2, 185.2])
    np.testing.assert_allclose(problem.vertex_xy(4), [0.0, 0.0])
    assert set(problem.neighbors(4, 4)) == {1, 3, 5, 7}
    assert set(problem.neighbors(4, 8)) == {0, 1, 2, 3, 5, 6, 7, 8}
    assert set(problem.neighbors(0, 8)) == {1, 3, 4}
    assert problem.edge_duration_s(4, 5, 4) == pytest.approx(9.26)
    assert problem.edge_duration_s(4, 2, 8) == pytest.approx(sqrt(2) * 9.26)
    with pytest.raises(ValueError, match="illegal"):
        problem.edge_duration_s(4, 2, 4)


def test_partial_terminal_diagonal_keeps_command_and_true_position():
    problem = _problem(horizon=1)
    state = problem.advance(problem.initial_state(), 2, connectivity=8)
    score = replay(problem, [4, 2], connectivity=8)
    expected_xy = [1 / sqrt(2), 1 / sqrt(2)]
    assert state.vertex == 2
    assert state.terminal and state.last_edge_partial
    assert state.time_s == pytest.approx(1.0)
    np.testing.assert_allclose(state.actual_xy, expected_xy)
    assert score["waypoints"] == [4, 2]
    assert score["arrival_times_s"] == [0.0]
    assert score["planned_arrival_times_s"] == pytest.approx([0.0, sqrt(2)])
    assert score["physical_duration_s"] == pytest.approx(1.0)
    assert score["distance_m"] == pytest.approx(1.0)
    assert score["diagonal_distance_fraction"] == pytest.approx(1.0)
    assert score["observation_count"] == 1
    assert score["observation_times_s"] == [1.0]
    np.testing.assert_allclose(score["final_xy"], expected_xy)
    np.testing.assert_allclose(score["observations"][0]["aircraft_xy"], expected_xy)
    assert score["observations"][0]["fraction_of_edge"] == pytest.approx(1 / sqrt(2))
    with pytest.raises(ValueError, match="horizon"):
        problem.advance(state, 1, connectivity=8)


def test_diagonal_clock_is_independent_of_waypoint_arrivals():
    problem = _problem()
    diagonal = problem.replay([4, 2, 1], connectivity=8)
    cardinal = problem.replay([4, 1, 2], connectivity=4)
    assert diagonal["arrival_times_s"] == pytest.approx([0, sqrt(2)])
    assert diagonal["planned_arrival_times_s"] == pytest.approx([0, sqrt(2), sqrt(2) + 1])
    assert diagonal["observation_times_s"] == cardinal["observation_times_s"] == [1.0, 2.0]
    assert diagonal["J"] == cardinal["J"] == 2.0
    np.testing.assert_allclose(diagonal["observations"][0]["aircraft_xy"],
                               [1 / sqrt(2), 1 / sqrt(2)])
    np.testing.assert_allclose(diagonal["observations"][1]["aircraft_xy"],
                               [sqrt(2) - 1, 1])
    for score in (diagonal, cardinal):
        assert score["distance_m"] == pytest.approx(2.0)
        assert score["physical_duration_s"] == pytest.approx(2.0)
        for edge in score["segments"]:
            assert edge["flown_distance_m"] / (edge["end_time_s"] - edge["start_time_s"]) == pytest.approx(1.0)


def test_tick_at_arrival_belongs_to_incoming_edge_exactly_once():
    score = _problem().replay([4, 1, 2], connectivity=4)
    records = score["observations"]
    assert [record["tick"] for record in records] == [1, 2]
    assert [record["source_vertex"] for record in records] == [4, 1]
    assert [record["target_vertex"] for record in records] == [1, 2]
    np.testing.assert_allclose([record["heading_xy"] for record in records],
                               [[0, 1], [1, 0]])
    assert [record["fraction_of_edge"] for record in records] == pytest.approx([1, 1])
    assert score["arrival_times_s"] == pytest.approx([0, 1, 2])
    assert not score["last_edge_partial"]


def test_t_zero_is_never_observed():
    positions = np.zeros((2, 1, 2))
    score = _problem(horizon=1, positions=positions, q=1.0).replay([4, 5])
    assert score["survival"] == pytest.approx([1, 1])
    assert score["J"] == pytest.approx(1)
    assert score["pd_final"] == pytest.approx(0)
    assert score["observation_times_s"] == [1.0]


def test_two_ticks_in_one_edge_use_distinct_absolute_particle_frames():
    positions = np.full((5, 1, 2), 100.0)
    positions[3, 0] = (3 / sqrt(2) - 2, 3 / sqrt(2) - 2)
    positions[4, 0] = (4 / sqrt(2) - 2, 4 / sqrt(2) - 2)
    score = _problem(horizon=4, positions=positions, q=0.5).replay([4, 2, 4, 2], 8)
    assert score["survival"] == pytest.approx([1, 1, 1, 0.5, 0.25])
    assert score["J"] == pytest.approx(2.75)
    assert score["observations"][2]["source_vertex"] == 4
    assert score["observations"][3]["source_vertex"] == 4
    assert score["observations"][2]["target_vertex"] == 2
    assert score["observations"][3]["target_vertex"] == 2
    assert score["observations"][2]["time_s"] == 3.0
    assert score["observations"][3]["time_s"] == 4.0


def test_special_bin_mass_is_kept_and_never_sensed():
    positions = np.array([[[1, 0], [np.nan, np.nan]],
                          [[1, 0], [np.nan, np.nan]]])
    searchable = np.array([[True, False], [True, False]])
    problem = _problem(horizon=1, positions=positions, searchable=searchable,
                       weights=(0.6, 0.4), q=1.0, trajectory_ids=[101, 202])
    score = problem.replay([4, 5])
    assert score["survival"] == pytest.approx([1, 0.4])
    assert score["final_weights"] == pytest.approx([0, 0.4])
    assert score["pd_final"] == pytest.approx(0.6)
    assert score["observations"][0]["sensed_trajectory_ids"] == [101]


def test_residual_particle_weights_remain_joint_unnormalised_mass():
    positions = np.full((3, 2, 2), 100.0)
    positions[1, 0] = (1, 0)
    positions[2, 0] = (0, 0)
    score = _problem(positions=positions, weights=(0.6, 0.4), q=0.5).replay([4, 5, 4])
    assert score["survival"] == pytest.approx([1, 0.7, 0.55])
    assert score["J"] == pytest.approx(1.25)
    assert score["final_weights"] == pytest.approx([0.15, 0.4])
    assert score["pd_final"] == pytest.approx(0.45)


@pytest.mark.parametrize("footprint", ["axis_square", "heading_square"])
def test_square_half_open_boundaries(footprint):
    frame = np.array([[-0.5, 0], [0.5, 0], [0, -0.5], [0, 0.5]])
    problem = _problem(horizon=1, positions=np.stack([frame, frame]),
                       weights=(0.25,) * 4, footprint=footprint)
    np.testing.assert_array_equal(problem.observation_mask(1, [0, 0], [1, 0]),
                                  [True, False, True, False])
    if footprint == "heading_square":
        np.testing.assert_array_equal(problem.observation_mask(1, [0, 0], [0, 1]),
                                      [False, True, True, False])


def test_heading_square_rotates_while_axis_square_does_not():
    frame = np.array([[0.6, 0], [0.49, 0.49]])
    inputs = dict(horizon=1, positions=np.stack([frame, frame]), weights=(0.5, 0.5))
    heading = _problem(**inputs, footprint="heading_square")
    axis = _problem(**inputs, footprint="axis_square")
    np.testing.assert_array_equal(heading.observation_mask(1, [0, 0], [1, 1]), [True, False])
    np.testing.assert_array_equal(axis.observation_mask(1, [0, 0], [1, 1]), [False, True])


def test_axis_four_neighbor_replay_matches_legacy_particle_scoring():
    cells = np.array([[4, 5, 9], [5, 1, 9], [5, 8, 9], [7, 8, 7]])
    weights = np.array([0.2, 0.3, 0.5])
    ids = np.array([11, 12, 13])
    positions = np.stack(((cells % 3 + 0.5 - 1.5) * 2.0,
                          (1.5 - cells // 3 - 0.5) * 2.0), axis=-1)
    positions[cells >= 9] = np.nan
    physical = _problem(horizon=3, positions=positions, searchable=cells < 9,
                        weights=weights, cell_width_m=2.0, speed_m_s=2.0,
                        trajectory_ids=ids, footprint="axis_square", q=0.78)
    route = [4, 5, 8, 7]
    legacy = score_path(GridGraph(3, 3), route, start=4, budget=3, p=weights,
                        q=0.78, motion=ParticleMotion(cells, 9, ids))
    result = physical.replay(route, connectivity=4)
    np.testing.assert_allclose(result["survival"], legacy.survival, rtol=0, atol=1e-14)
    np.testing.assert_allclose(result["final_weights"], legacy.final_belief, rtol=0, atol=1e-14)
    assert result["J"] == pytest.approx(legacy.J)
    assert result["pd_final"] == pytest.approx(legacy.pd_final)


def test_complete_horizon_is_required_and_extra_commands_are_rejected():
    with pytest.raises(ValueError, match="before"):
        _problem(horizon=2).replay([4, 5])
    with pytest.raises(ValueError, match="after"):
        _problem(horizon=1).replay([4, 5, 4])
    with pytest.raises(ValueError, match="start"):
        _problem(horizon=1).replay([3, 4])


@pytest.mark.parametrize("connectivity", [4, 8])
def test_waits_jumps_and_noninteger_vertices_are_rejected(connectivity):
    problem = _problem(horizon=1, start=0)
    for target in (0, 2, 3.0, True, -1, 9):
        with pytest.raises(ValueError):
            problem.advance(problem.initial_state(), target, connectivity)


@pytest.mark.parametrize("overrides", [
    {"q": np.nan}, {"q": -0.1}, {"q": 1.1}, {"q": True},
    {"cell_width_m": 0}, {"cell_width_m": np.inf}, {"speed_m_s": 0},
    {"rows": 1.5}, {"start": True}, {"start": 9}, {"footprint": "disk"},
    {"times_s": [0, 1, 2.1]}, {"times_s": [0, 1, 1]},
    {"times_s": [0.1, 1.1, 2.1]}, {"times_s": [0, 1, np.nan]},
    {"positions": np.full((3, 1, 2), np.nan)},
    {"positions": np.zeros((3, 1, 3))},
    {"searchable": np.ones((3, 1), dtype=int)},
    {"searchable": np.ones((2, 1), dtype=bool)},
    {"weights": (0.9,)}, {"weights": (1.1, -0.1)},
    {"weights": (1.0 + 1.0j,)},
    {"trajectory_ids": [np.nan]},
])
def test_invalid_physical_inputs_are_rejected(overrides):
    with pytest.raises(ValueError):
        _problem(**overrides)


def test_duplicate_ids_and_inconsistent_speed_cadence_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        _problem(weights=(0.5, 0.5), trajectory_ids=[9, 9])
    with pytest.raises(ValueError, match="cadence"):
        _problem(speed_m_s=sqrt(2))
    with pytest.raises(ValueError, match="cadence"):
        _problem(cell_width_m=1e-20, speed_m_s=1.0,
                 times_s=np.array([0, 1.1e-20, 2.2e-20]))


def test_problem_copies_arrays_and_states_cannot_cross_problems():
    positions = np.full((3, 1, 2), 100.0)
    first = _problem(positions=positions)
    positions[:] = 0
    np.testing.assert_array_equal(first.positions_xy, np.full((3, 1, 2), 100.0))
    state = first.initial_state()
    with pytest.raises(ValueError):
        first.initial_weights[0] = 0
    with pytest.raises(ValueError):
        state.weights[0] = 0
    with pytest.raises(ValueError, match="belong"):
        _problem().advance(state, 5)


def test_replay_evidence_is_json_serialisable_and_proxy_label_is_explicit():
    positions = np.array([[[1, 0]], [[1, 0]]])
    problem = _problem(horizon=1, positions=positions, trajectory_ids=np.array([b"target-1"]))
    result = problem.replay([4, 5])
    encoded = json.dumps(result, allow_nan=False)
    assert "controlled_geometric_proxy_not_camera_calibrated" in encoded
    assert result["observations"][0]["sensed_trajectory_ids"] == ["target-1"]
    assert not result["formal_certificate"]
    assert result["J_time_scaled_s"] == pytest.approx(result["J"] * problem.delta_s)
    assert "not exact continuous-time MTTD" in result["J_time_scaled_interpretation"]
