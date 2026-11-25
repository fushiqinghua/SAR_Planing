"""Integration checks for exact full-task local improvement and budget stops."""
from dataclasses import replace

import numpy as np
import pytest

from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.window_bounds import WINDOW_MODES
import asar_repro.window_search as ws
from audit_window_bounds import enumerate_window_oracle
from test_window_bounds import static_case, dynamic_case, particle_case


def args(case):
    return dict(start=case.reference_path[0], budget=case.horizon,
                p=case.p, q=case.q, motion=case.motion)


@pytest.mark.parametrize('factory', [static_case, dynamic_case, particle_case])
@pytest.mark.parametrize('mode', WINDOW_MODES)
def test_window_matches_independent_full_route_oracle(factory, mode):
    case = factory()
    oracle = enumerate_window_oracle(case)
    result = ws.solve_window(case.grid, **args(case), path=case.reference_path,
                             a=case.window_start, b=case.window_end, mode=mode)
    optimum = oracle.best_full_J_by_prefix[case.reference_path[:case.window_start+1]]
    replay = score_path(case.grid, result.path, **args(case))
    assert result.status == 'completed' and result.stop_reason is None
    assert result.J == pytest.approx(optimum, abs=1e-10, rel=0)
    assert result.J == replay.J and result.Pd == replay.pd_final
    assert result.path[:case.window_start+1] == case.reference_path[:case.window_start+1]
    assert result.path[case.window_end:] == case.reference_path[case.window_end:]
    assert not result.theory_certified


@pytest.mark.parametrize('mode', WINDOW_MODES)
def test_fixed_suffix_changes_best_window_and_is_counted(mode):
    case = static_case()
    result = ws.solve_window(case.grid, **args(case), path=case.reference_path,
                             a=0, b=2, mode=mode)
    assert result.path == (0, 2, 3, 1)
    assert result.J == 1.0 and result.Pd == 1.0
    assert result.improvements[-1]['prediction_error_J'] == 0


def test_original_J_can_improve_while_final_Pd_decreases():
    grid = GridGraph(2, 2)
    # First route detects .2 early and the other .8 at t=2 (J=.8, Pd=1).
    # Rewritten route detects .8 early, leaving .2 outside (J=.4, Pd=.8).
    motion = ParticleMotion(np.array([[0, 0], [1, 2], [3, 4]]), 4, [11, 22])
    cfg = dict(start=0, budget=2, p=[.8, .2], q=1., motion=motion)
    before = score_path(grid, (0, 2, 3), **cfg)
    result = ws.solve_window(grid, **cfg, path=(0, 2, 3), a=0, b=2)
    assert result.J == pytest.approx(.4) and before.J == pytest.approx(.8)
    assert result.Pd == pytest.approx(.8) and before.pd_final == 1.
    assert result.Pd < before.pd_final  # No concealed Pd constraint/objective change.


@pytest.mark.parametrize('mode', WINDOW_MODES)
def test_no_detection_preserves_route_and_zero_improvements(mode):
    case = static_case(q=0.)
    result = ws.solve_window(case.grid, **args(case), path=case.reference_path,
                             a=0, b=2, mode=mode)
    assert result.path == case.reference_path
    assert result.J == case.horizon and result.Pd == 0.
    assert result.improvements == [] and result.status == 'completed'


@pytest.mark.parametrize('limit,reason', [({'max_expansions': 0}, 'max_expansions'),
                                        ({'max_seconds': 0}, 'max_seconds'),
                                        ({'max_open': 0}, 'max_open')])
def test_local_budget_preserves_complete_original(limit, reason):
    case = static_case()
    result = ws.solve_window(case.grid, **args(case), path=case.reference_path,
                             a=0, b=2, **limit)
    assert result.path == case.reference_path
    assert result.J == 1.5 and result.status == 'budget_exceeded'
    assert result.stop_reason == reason and not result.theory_certified


def test_deadline_keeps_just_generated_improvement(monkeypatch):
    case = static_case()
    clock = [0.]
    original_scorer = ws.score_path
    def replay(grid, path, **kwargs):
        answer = original_scorer(grid, path, **kwargs)
        if tuple(path) == (0, 2, 3, 1):
            clock[0] = 2.
        return answer
    monkeypatch.setattr(ws, 'perf_counter', lambda: clock[0])
    monkeypatch.setattr(ws, 'score_path', replay)
    result = ws.solve_window(case.grid, **args(case), path=case.reference_path,
                             a=0, b=2, mode='zero', max_seconds=1.)
    assert result.status == 'budget_exceeded' and result.stop_reason == 'max_seconds'
    assert result.J == 1.0 and result.path == (0, 2, 3, 1)
    assert result.incumbent_source == 'window[0:2]'
    assert result.deadline_overshoot_s == 1. and not result.theory_certified


@pytest.mark.parametrize('mode', WINDOW_MODES)
def test_seed_subquota_then_local_improvement_share_totals(mode):
    case = static_case()
    result = ws.improve_with_windows(case.grid, **args(case), initial_path=case.reference_path,
        mode=mode, seed_max_expansions=0, window_lengths=(2,), max_expansions=1000,
        max_seconds=None)
    assert result.seed['status'] == 'budget_exceeded'
    assert result.seed['stop_reason'] == 'max_expansions'
    assert result.seed['continuing_after_subquota']
    assert result.J <= 1.0 and result.status == 'completed'
    assert result.completion_reason == 'local_stalled_at_tolerance'
    assert not result.theory_certified
    for field in ('expanded', 'generated', 'pruned'):
        assert getattr(result, field) == result.seed[field] + sum(w[field] for w in result.windows)
    assert result.peak_open == max(result.seed['peak_open'], *[w['peak_open'] for w in result.windows])
    assert all(i['J'] < i['old_J'] - ws.ATOL for i in result.improvements)


@pytest.mark.parametrize('limit,reason', [({'max_expansions': 0}, 'max_expansions'),
                                        ({'max_seconds': 0}, 'max_seconds'),
                                        ({'max_open': 0}, 'max_open')])
def test_seed_global_budget_cannot_be_reset_for_windows(limit, reason):
    case = static_case()
    result = ws.improve_with_windows(case.grid, **args(case), initial_path=case.reference_path,
                                    window_lengths=(2,), **limit)
    assert result.status == 'budget_exceeded' and result.stop_reason == reason
    assert result.windows == [] and result.path == case.reference_path
    assert not result.theory_certified


def test_total_expansion_cap_and_complete_incumbent():
    case = static_case()
    result = ws.improve_with_windows(case.grid, **args(case), initial_path=case.reference_path,
        mode='zero', seed_max_expansions=0, window_lengths=(2,), max_expansions=1)
    assert result.expanded == 1 and result.stop_reason == 'max_expansions'
    assert result.J == score_path(case.grid, result.path, **args(case)).J


def test_overlapping_windows_rebuild_beliefs_and_suffix_after_acceptance():
    case = static_case()
    expected_path = case.reference_path
    expected_J = score_path(case.grid, expected_path, **args(case)).J
    # A separate exhaustive coordinate descent, using only full-path replays.
    while True:
        changed = False
        for a in range(case.horizon-1):
            local = replace(case, reference_path=expected_path, window_start=a, window_end=a+2)
            oracle = enumerate_window_oracle(local)
            root = expected_path[:a+1]
            candidate_J = oracle.best_full_J_by_prefix[root]
            if candidate_J < expected_J-ws.ATOL:
                expected_path = oracle.best_full_path_by_prefix[root]
                expected_J = candidate_J
                changed = True
        if not changed:
            break
    result = ws.improve_with_windows(case.grid, **args(case), initial_path=case.reference_path,
        seed_max_expansions=0, window_lengths=(2,), max_expansions=None, max_seconds=None)
    assert result.J == pytest.approx(expected_J, abs=1e-10, rel=0)
    assert result.windows[0]['improvements'] > 0
    assert result.windows[1]['initial_J'] == result.windows[0]['final_J']


def test_no_window_that_fits_reports_local_stall_only():
    case = static_case()
    result = ws.improve_with_windows(case.grid, **args(case), initial_path=case.reference_path,
        seed_max_expansions=0, window_lengths=(4, 6), max_seconds=None)
    assert not result.windows and result.status == 'completed'
    assert result.completion_reason == 'local_stalled_at_tolerance'
    assert result.seed['phase_budget_exceeded'] and not result.theory_certified


@pytest.mark.parametrize('kwargs', [dict(a=-1, b=2), dict(a=2, b=2), dict(a=0, b=4),
                                   dict(a=0, b=2, mode='paper_greedy')])
def test_invalid_window_rejected(kwargs):
    case = static_case()
    with pytest.raises(ValueError):
        ws.solve_window(case.grid, **args(case), path=case.reference_path, **kwargs)
