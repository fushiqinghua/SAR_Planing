"""Short-window proposals: independent Oracle, exact suffix and shared budgets."""
from itertools import product
from math import inf
from time import perf_counter

import numpy as np
import pytest

import asar_repro.short_window_rollout as burst
from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.research_particle import FutureEquivalentMotion


def case(kind="dynamic", T=5):
    grid=GridGraph(2,3)
    rng=np.random.default_rng(2441)
    motion=MatrixMotion.time_varying(rng.dirichlet(np.full(6,.7),size=(T,6)))
    p=rng.dirichlet(np.full(6,.7))
    if kind=="static":motion=MatrixMotion.identity(6)
    if kind=="particle":
        cells=rng.integers(0,6,size=(T+1,6))
        cells[:,4]=6
        cells[:,5]=7
        cells[-1,5]=2
        motion=ParticleMotion(cells,6,[90,17,5,81,4,99])
    cfg=dict(start=0,budget=T,p=p,q=[.2,.78,1.,.4,.6,0.],motion=motion)
    initial=tuple([0]+[1 if t%2 else 0 for t in range(1,T+1)])
    return grid,cfg,initial


def check(grid,cfg,result):
    score=score_path(grid,result.path,**cfg)
    assert result.J==pytest.approx(score.J,abs=1e-10,rel=0)
    assert result.Pd==pytest.approx(score.pd_final,abs=1e-10,rel=0)
    assert not result.theory_certified
    assert not result.stats["state_merging"]
    assert not result.stats["guide_used_for_pruning"]
    assert result.stats["bound_is_unweighted"]
    old=inf
    for row in result.incumbent_history:
        replay=score_path(grid,row["path"],**cfg)
        assert row["J"]==pytest.approx(replay.J,abs=1e-10,rel=0)
        assert row["Pd"]==pytest.approx(replay.pd_final,abs=1e-10,rel=0)
        assert row["J"]<old
        old=row["J"]
    return score


def window_oracle(grid,cfg,path,a,b):
    scores=[]
    def visit(prefix):
        t=len(prefix)-1
        if t==b:
            if prefix[-1]==path[b]:
                candidate=prefix+path[b+1:]
                scores.append(score_path(grid,candidate,**cfg).J)
            return
        for v in grid.neighbors(prefix[-1]):visit(prefix+(v,))
    visit(path[:a+1])
    return min(scores)


@pytest.mark.parametrize("kind",["static","dynamic","particle"])
@pytest.mark.parametrize("lazy",[False,True])
@pytest.mark.parametrize("extra",[0,4])
def test_full_window_wide_beam_matches_fixed_endpoint_oracle(kind,lazy,extra):
    grid,cfg,initial=case(kind,T=4)
    original=cfg["p"].copy()
    session=burst.BurstRollout(grid,**cfg,initial_path=initial,windows=[(0,4)],
        quality_width=1000,diversity_slots=extra,lazy_bound=lazy)
    result=session.advance()
    check(grid,cfg,result)
    assert result.status=="completed"
    # Even [0,T] retains the supplied endpoint. The independent local DFS
    # therefore has that same constraint; the global Oracle has a free end.
    assert result.J==pytest.approx(window_oracle(grid,cfg,initial,0,4),abs=1e-10,rel=0)
    assert enumerate_oracle(grid,**cfg).J<=result.J+1e-10
    np.testing.assert_array_equal(cfg["p"],original)
    assert session.frontier_count==0


@pytest.mark.parametrize("kind",["static","dynamic","particle"])
@pytest.mark.parametrize("a,b",[(1,4),(2,5)])
def test_absolute_window_exact_suffix_matches_independent_enumeration(kind,a,b):
    grid,cfg,initial=case(kind,T=6)
    result=burst.BurstRollout(grid,**cfg,initial_path=initial,windows=[(a,b)],quality_width=1000).advance()
    check(grid,cfg,result)
    assert result.path[:a+1]==initial[:a+1]
    assert result.path[b:]==initial[b:]
    assert result.J==pytest.approx(window_oracle(grid,cfg,initial,a,b),abs=1e-10,rel=0)


@pytest.mark.parametrize("kind",["static","dynamic","particle"])
@pytest.mark.parametrize("extra",[0,4])
def test_eager_lazy_keep_identical_quality_and_diverse_paths(kind,extra):
    grid,cfg,initial=case(kind,T=6)
    traces=[];results=[]
    for lazy in (False,True):
        trace=[]
        session=burst.BurstRollout(grid,**cfg,initial_path=initial,quality_width=2,
            diversity_slots=extra,lazy_bound=lazy,trace=trace.append,windows=[(0,6)])
        result=session.advance()
        check(grid,cfg,result)
        traces.append([(x["quality_paths"],x["retained_paths"]) for x in trace if x["event"]=="beam_select"])
        results.append(result)
    assert traces[0]==traces[1]
    assert results[0].path==results[1].path
    assert results[0].expanded==results[1].expanded
    assert results[1].stats["bound_calls"]<=results[0].stats["bound_calls"]


def test_lazy_bound_avoids_queries_for_discarded_states():
    grid,cfg,initial=case("dynamic",T=6)
    eager=burst.BurstRollout(grid,**cfg,initial_path=initial,quality_width=1,lazy_bound=False,
                            windows=[(0,6)]).advance()
    lazy=burst.BurstRollout(grid,**cfg,initial_path=initial,quality_width=1,lazy_bound=True,
                           windows=[(0,6)]).advance()
    assert eager.path==lazy.path
    assert lazy.stats["unqueried_bound_discarded"]>0
    assert lazy.stats["bound_calls"]<eager.stats["bound_calls"]


def test_extra_diversity_never_replaces_quality_slots():
    grid,cfg,initial=case("particle",T=6)
    trace=[]
    result=burst.BurstRollout(grid,**cfg,initial_path=initial,quality_width=2,
        diversity_slots=4,trace=trace.append,windows=[(0,6)]).advance()
    check(grid,cfg,result)
    selections=[x for x in trace if x["event"]=="beam_select"]
    assert selections
    for row in selections:
        assert set(row["quality_paths"]).issubset(row["retained_paths"])
        assert len(row["quality_paths"])<=2
        assert len(row["retained_paths"])<=len(row["quality_paths"])+4


@pytest.mark.parametrize("kind",["static","dynamic","particle"])
@pytest.mark.parametrize("lazy",[False,True])
def test_slice_resume_matches_continuous_execution(kind,lazy):
    grid,cfg,initial=case(kind,T=6)
    common=dict(initial_path=initial,quality_width=3,lazy_bound=lazy,windows=[(0,6)])
    whole=burst.BurstRollout(grid,**cfg,**common).advance()
    session=burst.BurstRollout(grid,**cfg,**common)
    for _ in range(10000):
        split=session.advance(max_expansions=1)
        if split.status=="completed":break
        assert split.status=="paused"
    else:pytest.fail("finite window schedule did not finish")
    assert split.path==whole.path
    assert split.expanded==whole.expanded
    assert split.generated==whole.generated
    assert split.stats["bound_calls"]==whole.stats["bound_calls"]
    check(grid,cfg,split)


def test_zero_work_and_elapsed_deadline_keep_valid_incumbent():
    grid,cfg,initial=case()
    session=burst.BurstRollout(grid,**cfg,initial_path=initial)
    zero=session.advance(max_expansions=0)
    assert zero.expanded==0 and zero.stop_reason=="slice_expansions"
    timed=session.advance(deadline=perf_counter()-1)
    assert timed.expanded==0 and timed.stop_reason=="slice_time"
    assert zero.path==timed.path==initial
    check(grid,cfg,timed)


def test_open_cap_reserves_atomic_children_and_can_resume():
    grid,cfg,initial=case(T=6)
    session=burst.BurstRollout(grid,**cfg,initial_path=initial,windows=[(0,6)])
    limited=session.advance(max_open=1)
    assert limited.stop_reason=="max_open"
    assert session.frontier_count==1
    assert limited.expanded==0
    resumed=session.advance(max_open=10000)
    assert resumed.status=="completed"
    check(grid,cfg,resumed)


def test_lowered_open_cap_does_not_drop_existing_states():
    grid,cfg,initial=case(T=6)
    session=burst.BurstRollout(grid,**cfg,initial_path=initial,windows=[(0,6)])
    session.advance(max_expansions=1,max_open=10000)
    count=session.frontier_count
    assert count>0
    stopped=session.advance(max_open=0)
    assert stopped.stop_reason=="max_open"
    assert session.frontier_count==count


@pytest.mark.parametrize("q",[0.,1.])
def test_q_extremes_and_special_particle_mass(q):
    grid,cfg,initial=case("particle",T=4)
    cfg["q"]=q
    result=burst.BurstRollout(grid,**cfg,initial_path=initial,windows=[(0,4)],quality_width=1000).advance()
    score=check(grid,cfg,result)
    assert score.final_belief[4]==cfg["p"][4]
    assert result.J==pytest.approx(window_oracle(grid,cfg,initial,0,4),abs=1e-10,rel=0)
    assert enumerate_oracle(grid,**cfg).J<=result.J+1e-10


def test_original_id_replay_for_exact_compression():
    grid=GridGraph(1,3)
    cells=np.array([[0,0,3],[1,1,3],[2,2,3],[1,1,3],[0,0,3]])
    cfg=dict(start=0,budget=4,p=np.array([.2,.5,.3]),q=.78,
        motion=ParticleMotion(cells,3,[90,2,700]))
    initial=(0,1,0,1,0)
    grouped=FutureEquivalentMotion(cfg["motion"],cfg["p"])
    packed=dict(cfg,p=grouped.initial_weights,motion=grouped)
    result=burst.BurstRollout(grid,**packed,initial_path=initial,replay_cfg=cfg,
        windows=[(0,4)],quality_width=1000).advance()
    check(grid,cfg,result)
    with pytest.raises(ValueError,match="original replay"):
        burst.BurstRollout(grid,**packed,initial_path=initial)


def test_external_better_incumbent_replays_and_rebuilds_proposals():
    grid,cfg,initial=case("static",T=4)
    session=burst.BurstRollout(grid,**cfg,initial_path=initial)
    session.advance(max_expansions=1)
    best=enumerate_oracle(grid,**cfg)
    assert session.set_incumbent(best.path)
    assert session.frontier_count==0
    assert session.stats["external_updates"]==1
    assert not session.set_incumbent(initial)
    assert not session.set_incumbent(best.path)
    result=session.advance()
    check(grid,cfg,result)
    assert result.J==pytest.approx(best.J,abs=1e-10,rel=0)


def test_reject_invalid_configuration():
    grid,cfg,initial=case()
    for settings in ({"quality_width":0},{"diversity_slots":-1},{"lazy_bound":1},
                     {"window_lengths":()},{"windows":[(2,1)]}):
        with pytest.raises(ValueError):burst.BurstRollout(grid,**cfg,initial_path=initial,**settings)


def test_zero_horizon_needs_no_search():
    grid=GridGraph(1,1)
    cfg=dict(start=0,budget=0,p=[1.],q=1.,motion=MatrixMotion.identity(1))
    result=burst.BurstRollout(grid,**cfg,initial_path=(0,)).advance()
    assert result.status=="completed"
    assert result.J==0 and result.Pd==0 and result.expanded==0
