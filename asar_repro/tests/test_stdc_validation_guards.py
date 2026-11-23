"""Negative controls: replay errors and invalid certificates must stop a run."""
from dataclasses import replace

import pytest

from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion
from asar_repro.search import search_asar
from stdc_validation_guards import replay_result


@pytest.fixture
def stopped():
    grid=GridGraph(2,2)
    cfg=dict(start=0,budget=4,p=[.1,.2,.3,.4],q=.78,motion=MatrixMotion.identity(4))
    result=search_asar(grid,**cfg,heuristic='stdc_lb',max_expansions=0,
                       initial_path=(0,1,0,1,0))
    return grid,cfg,result


def test_replay_rejects_reported_cost_corruption(stopped):
    grid,cfg,result=stopped
    with pytest.raises(AssertionError,match='independent J replay'):
        replay_result(grid,cfg,replace(result,J=result.J+.01))


def test_replay_rejects_certificate_on_budget_stop(stopped):
    grid,cfg,result=stopped
    with pytest.raises(AssertionError,match='invalid certification'):
        replay_result(grid,cfg,replace(result,theory_certified=True))


def test_replay_rejects_illegal_route(stopped):
    grid,cfg,result=stopped
    with pytest.raises(ValueError):
        replay_result(grid,cfg,replace(result,path=(0,0,0,0,0)))


def test_replay_rejects_paper_certificate(stopped):
    grid,cfg,result=stopped
    with pytest.raises(AssertionError,match='invalid certification'):
        replay_result(grid,cfg,replace(result,status='completed',stop_reason=None,
                       heuristic_mode='paper_greedy',theory_certified=True))
