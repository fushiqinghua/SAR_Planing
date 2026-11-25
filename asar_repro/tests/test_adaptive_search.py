"""Shared-budget regression tests; original evaluator and oracle are independent."""
from math import inf
from time import perf_counter
import numpy as np
import pytest
from asar_repro.adaptive_search import search_adaptive
from asar_repro.grid import GridGraph
from asar_repro.motion import ParticleMotion
from asar_repro.objective import score_path
from asar_repro.oracle import enumerate_oracle
from asar_repro.research_search import search_research

def case(T=4):
    grid=GridGraph(2,3)
    cells=np.array([[0,1,4,5] if t%2==0 else [1,2,3,4] for t in range(T+1)])
    cfg=dict(start=0,budget=T,p=np.array([.1,.2,.3,.4]),q=.78,
             motion=ParticleMotion(cells,grid.size,np.arange(4)))
    path=tuple(0 if t%2==0 else 1 for t in range(T+1))
    return grid,cfg,path

@pytest.mark.parametrize("T",[0,1,3,5])
def test_direct_complete_matches_independent_oracle(T):
    grid,cfg,path=case(T)
    result,phases,prep,wall=search_adaptive(grid,**cfg,initial_path=path,max_seconds=20,
        global_chunk=2)
    expected=enumerate_oracle(grid,**cfg)
    assert result.status=="completed"
    assert result.J==pytest.approx(expected.J,abs=1e-10)
    assert score_path(grid,result.path,**cfg).pd_final==pytest.approx(result.Pd,abs=1e-10)
    assert result.expanded==sum(p["expanded"] for p in phases)
    assert not result.theory_certified

@pytest.mark.parametrize('dp_kind',['dense','compact'])
def test_dp_memory_abort_returns_to_real_stdc_search(dp_kind):
    grid,cfg,path=case(5)
    control,*_=search_adaptive(grid,**cfg,initial_path=path,max_seconds=20)
    result,phases,prep,wall=search_adaptive(grid,**cfg,initial_path=path,
        dp_kind=dp_kind,dp_memory_bytes=1,max_seconds=20)
    assert prep["dp_fallback"] and prep["dp"]["stop_reason"]=="max_memory_bytes"
    assert result.expanded>0 and result.stats["global_expanded"]>0
    assert result.J==pytest.approx(control.J,abs=1e-10)
    assert result.status=="completed"
    assert result.incumbent_source!="initial_path"

def test_exhausted_local_proposals_give_unused_work_back(monkeypatch):
    import asar_repro.midpoint_rollout as midpoint
    grid,cfg,path=case(12)
    calls=[]
    def finite_empty_proposals(graph,**kwargs):
        calls.append(kwargs)
        result=search_research(graph,**cfg,initial_path=kwargs["initial_path"],max_expansions=0)
        result.status="completed";result.stop_reason=None
        return result
    monkeypatch.setattr(midpoint,"search_midpoint",finite_empty_proposals)
    result,phases,prep,wall=search_adaptive(grid,**cfg,initial_path=path,
        schedule="recycle",max_expansions=20,max_seconds=20,max_open=1000)
    assert calls
    assert result.expanded==20
    assert result.stats["local_expanded"]==0
    assert result.stats["global_resumed_after_rollout"]
    assert result.status=="budget_exceeded" and result.stop_reason=="max_expansions"
    assert phases[-1]["name"]=="global_stdc"
    assert calls[0]["max_open"]<1000  # retained global OPEN uses same physical capacity
    control=search_research(grid,**cfg,initial_path=path,max_expansions=20,max_seconds=20,max_open=1000)
    assert result.J==pytest.approx(control.J,abs=1e-10)

@pytest.mark.parametrize("cap",[0,1,7])
def test_total_work_cap_and_retained_complete_incumbent(cap):
    grid,cfg,path=case(8)
    result,phases,prep,wall=search_adaptive(grid,**cfg,initial_path=path,
        max_expansions=cap,max_seconds=20)
    assert result.expanded<=cap
    assert result.path is not None
    assert result.J<=score_path(grid,path,**cfg).J+1e-10
    assert result.stats["work_expanded"]==result.expanded

def test_zero_time_is_explicit_and_keeps_pt():
    grid,cfg,path=case()
    result,phases,prep,wall=search_adaptive(grid,**cfg,initial_path=path,
        dp_kind="dense",max_seconds=0)
    assert result.status=="budget_exceeded" and result.stop_reason=="max_seconds"
    assert result.expanded==0 and result.path==path

@pytest.mark.parametrize("lazy,extra",[(False,0),(True,0),(True,4)])
def test_interleaved_bursts_complete_global_oracle_and_exact_work(lazy,extra):
    grid,cfg,path=case(5)
    result,phases,prep,wall=search_adaptive(grid,**cfg,initial_path=path,
        schedule="bursts",lazy_rollout=lazy,diversity_slots=extra,
        global_chunk=2,burst_work=3,local_fraction=.5,max_seconds=20,max_open=20000)
    assert result.status=="completed"
    assert result.J==pytest.approx(enumerate_oracle(grid,**cfg).J,abs=1e-10)
    assert result.expanded==sum(p["expanded"] for p in phases)
    assert result.expanded==result.stats["global_expanded"]+result.stats["local_expanded"]
    work=[e["work_expanded"] for e in result.incumbent_history]
    assert work==sorted(work) and max(work)<=result.expanded
    assert result.peak_open<=20000
    assert not result.theory_certified

@pytest.mark.parametrize("cap",[20,80,180])
def test_shared_work_and_open_with_live_global_and_local_frontiers(cap):
    grid,cfg,path=case(8)
    result,phases,prep,wall=search_adaptive(grid,**cfg,initial_path=path,
        schedule="bursts",global_chunk=2,burst_work=3,local_fraction=.5,
        max_expansions=cap,max_open=120,max_seconds=20)
    assert result.expanded<=cap and result.peak_open<=120
    assert result.expanded==sum(p["expanded"] for p in phases)
    assert result.J<=score_path(grid,path,**cfg).J+1e-10
    assert result.status in ("completed","budget_exceeded")
    if result.status=="budget_exceeded":
        assert result.stop_reason in ("max_expansions","max_open","max_seconds")

def test_sparse_guide_preserves_direct_stdc_work_result():
    grid,cfg,path=case(8)
    control,*_=search_adaptive(grid,**cfg,initial_path=path,max_expansions=100)
    fast,*_=search_adaptive(grid,**cfg,initial_path=path,max_expansions=100,efficient_guide=True)
    assert fast.J==pytest.approx(control.J,abs=1e-10)
    assert fast.Pd==pytest.approx(control.Pd,abs=1e-10)
    assert fast.path==control.path and fast.expanded==control.expanded

@pytest.mark.parametrize("seconds",[-1,float("inf"),float("nan")])
def test_invalid_shared_time_cap_rejected(seconds):
    grid,cfg,path=case()
    with pytest.raises(ValueError):
        search_adaptive(grid,**cfg,initial_path=path,max_seconds=seconds)


