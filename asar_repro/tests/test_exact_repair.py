"""Frozen-score, independent DFS checks for particle MILP repair."""
from types import SimpleNamespace

import numpy as np
import pytest

import asar_repro.exact_repair as module
from asar_repro.exact_repair import solve_exact_repair
from asar_repro.grid import GridGraph
from asar_repro.motion import MatrixMotion, ParticleMotion
from asar_repro.objective import score_path

ATOL = 1e-10


@pytest.mark.parametrize('seed', [1041,1042,1043,1044,1059,1087])
@pytest.mark.parametrize('warm,cutoff', [(False,True),(True,False),(True,True)])
def test_start_and_cutoff_ablation_matches_independent_oracle(seed,warm,cutoff):
    from audit_exact_repair import toy_case,independent_dfs,check_completed
    grid,cfg,path=toy_case(seed)
    a=cfg['budget']//2
    exact=independent_dfs(grid,cfg,path,a,0)
    r=solve_exact_repair(grid,**cfg,initial_path=path,prefix_depth=a,corridor_radius=0,
                         warm_start=warm,objective_cutoff=cutoff)
    check_completed(r,grid,cfg,path,a,0,exact)
    assert r.stats['mip_start_submitted'] is warm
    assert r.stats['mip_start_roundtrip_verified'] is warm
    assert r.stats['mip_start_replay_error']<=ATOL
    assert r.stats['mip_start_constraint_violation']<=ATOL
    assert r.stats['solver_options']['presolve'] is False
    if cutoff:
        assert r.stats['objective_cutoff_total_J']>=r.stats['initial_J']-ATOL
        assert r.stats['candidate_J']<=r.stats['initial_J']+ATOL


@pytest.mark.parametrize('T',[49,60])
@pytest.mark.parametrize('q',[0.,.78,1.])
def test_warm_start_long_horizon_zero_tiny_and_outside_mass(T,q):
    grid=GridGraph(1,2)
    cfg=dict(start=0,budget=T,p=[.8,.2],q=q,
        motion=ParticleMotion(np.tile([1,2],(T+1,1)),2,[81,4]))
    path=tuple(t%2 for t in range(T+1))
    r=solve_exact_repair(grid,**cfg,initial_path=path,warm_start=True,objective_cutoff=True)
    assert r.status=='completed',(r.stop_reason,r.stats)
    assert r.J==pytest.approx(score_path(grid,path,**cfg).J,abs=ATOL,rel=0)
    assert r.stats['mip_start_roundtrip_verified']
    assert not r.theory_certified


def test_seeded_repair_can_improve_supplied_route_with_cutoff():
    grid=GridGraph(1,3)
    cfg=dict(start=0,budget=2,p=[1.],q=.78,motion=ParticleMotion([[0],[1],[2]],3,[7]))
    r=solve_exact_repair(grid,**cfg,initial_path=(0,1,0),warm_start=True,objective_cutoff=True)
    assert r.status=='completed'
    assert tuple(r.path)==(0,1,2)
    assert r.J==pytest.approx(.2684,abs=ATOL,rel=0)
    assert r.Pd==pytest.approx(.9516,abs=ATOL,rel=0)
    assert r.incumbent_source=='milp_replayed_candidate'


def test_native_start_rejection_blocks_without_cold_fallback(monkeypatch):
    def rejected(*args,**kwargs):raise RuntimeError('setSolution rejected')
    def cold(*args,**kwargs):raise AssertionError('must not silently fall back')
    monkeypatch.setattr(module,'milp_with_start',rejected)
    monkeypatch.setattr(module,'milp',cold)
    grid,cfg,path=case(1043)
    r=solve_exact_repair(grid,**cfg,initial_path=path,warm_start=True,objective_cutoff=True)
    assert r.status=='blocked' and r.stop_reason=='model_or_solver_error'
    assert 'setSolution rejected' in r.stats['exception']
    assert tuple(r.path)==path and not r.theory_certified


@pytest.mark.parametrize('options',[dict(max_seconds=0),dict(max_memory_bytes=0),dict(node_limit=0)])
def test_warm_requested_budget_precheck_is_reported_without_false_submission(options):
    grid,cfg,path=case(1043)
    r=solve_exact_repair(grid,**cfg,initial_path=path,warm_start=True,objective_cutoff=True,**options)
    assert r.status=='budget_exceeded' and not r.stats['mip_start_submitted']
    assert tuple(r.path)==path and not r.theory_certified


@pytest.mark.parametrize('option',[dict(warm_start=1),dict(objective_cutoff='yes')])
def test_warm_switches_reject_nonboolean(option):
    grid,cfg,path=case(1043)
    with pytest.raises(ValueError):solve_exact_repair(grid,**cfg,initial_path=path,**option)


@pytest.mark.parametrize("detection", [.6,.78,1.])
@pytest.mark.parametrize("order", [(0,1,2,3),(1,0,3,2)])
def test_seed1059_false_native_optimum_regression(detection,order):
    # Presolve reported J=3.149565... despite a feasible J=3.074434... .
    grid=GridGraph(3,3)
    cells=np.array([[5,5,7,12],[5,5,0,12],[5,7,12,12],[5,9,4,12],
                    [5,5,1,12],[5,5,11,12],[5,5,0,12],[5,5,0,12]])
    ids=np.array([13,30,47,64]);p=np.array([7.,11.,1.,4.])/23
    q=np.linspace(.1,.9,9);q[5]=detection
    ix=np.array(order)
    cfg=dict(start=4,budget=7,p=p[ix],q=q,motion=ParticleMotion(cells[:,ix],9,ids[ix]))
    path=(4,5,2,1,2,5,8,7)
    result=completed(grid,cfg,path,a=3,radius=0)
    assert result.stats['solver_options']['presolve'] is False
    assert result.stats['solver_options']['mip_feasibility_tolerance']==1e-10
    assert result.stats['solver_options']['small_matrix_value']==1e-12
    if detection==.6:
        assert result.J==pytest.approx(3.0744347826086957,abs=ATOL,rel=0)
        assert result.Pd==pytest.approx(.7325217391304348,abs=ATOL,rel=0)
        assert result.restricted_lower_bound<=3.0744347826086957+ATOL


def oracle(grid, cfg, path, a=0, radius=None):
    # Independent complete-path DFS: no MILP geometry/grouping/bounds reused.
    centers = [divmod(v, grid.cols) for v in path[a:]]
    allowed = set(range(grid.size)) if radius is None else {
        v for v in range(grid.size)
        if any(abs(v//grid.cols-r)+abs(v%grid.cols-c)<=radius for r,c in centers)}
    values = []
    def dfs(route):
        if len(route)==cfg["budget"]+1:
            values.append((score_path(grid,route,**cfg).J,route));return
        for v in grid.neighbors(route[-1]):
            if v in allowed:dfs(route+(v,))
    dfs(tuple(path[:a+1]))
    return min(values, key=lambda x:x[0])


def case(seed=1041):
    rng = np.random.default_rng(seed)
    grid=GridGraph(3,3);T=4+seed%3;N=2+seed%6
    cells=rng.integers(0,13,(T+1,N));cells[:,-1]=9+seed%4
    p=rng.integers(1,10,N).astype(float);p/=p.sum()
    q=(0.,1.,.78,np.linspace(.1,.9,9))[seed%4]
    motion=ParticleMotion(cells,9,rng.permutation(np.arange(N)*19+5))
    path=[4]
    for _ in range(T):path.append(int(rng.choice(grid.neighbors(path[-1]))))
    return grid,dict(start=4,budget=T,p=p,q=q,motion=motion),tuple(path)


def completed(grid,cfg,path,a=0,radius=None):
    expected,_=oracle(grid,cfg,path,a,radius)
    result=solve_exact_repair(grid,**cfg,initial_path=path,prefix_depth=a,corridor_radius=radius)
    assert result.status=="completed", (result.stop_reason,result.solver_message)
    assert result.theory_certified is False
    assert tuple(result.path[:a+1])==tuple(path[:a+1])
    if radius is not None:
        centers=[divmod(v,grid.cols) for v in path[a:]]
        assert all(any(abs(v//grid.cols-r)+abs(v%grid.cols-c)<=radius for r,c in centers)
                   for v in result.path[a:])
    score=score_path(grid,result.path,**cfg)
    assert score.J==pytest.approx(expected,abs=ATOL,rel=0)
    assert result.J==pytest.approx(score.J,abs=ATOL,rel=0)
    assert result.Pd==pytest.approx(score.pd_final,abs=ATOL,rel=0)
    assert result.restricted_lower_bound is not None
    assert result.restricted_lower_bound<=expected+ATOL
    assert result.J<=score_path(grid,path,**cfg).J+ATOL
    assert result.wall_s>=0 and result.model_build_s>=0 and result.solve_s>=0
    assert result.stats["bound_scope"]=="restricted_subproblem"
    assert result.stats["state_merging"] is False
    return result


@pytest.mark.parametrize("seed", range(1041,1057))
@pytest.mark.parametrize("restricted", [False,True])
def test_random_dynamic_matches_independent_dfs(seed,restricted):
    grid,cfg,path=case(seed)
    completed(grid,cfg,path,cfg["budget"]//2 if restricted else 0,0 if restricted else None)


@pytest.mark.parametrize("q", [0.,.78,1.,np.array([.1,.6,.9])])
def test_static_repeated_observation_preserves_outside_and_zero_mass(q):
    grid=GridGraph(1,3)
    cells=np.tile([0,1,2,3,4,5,6],(5,1))
    cfg=dict(start=0,budget=4,p=np.array([.2,.3,.1,.1,.1,.2,0]),q=q,
             motion=ParticleMotion(cells,3,[13,21,8,9,10,11,12]))
    result=completed(grid,cfg,(0,1,0,1,0))
    score=score_path(grid,result.path,**cfg)
    assert score.final_belief[3:].sum()==pytest.approx(.4,abs=ATOL,rel=0)


def test_t0_not_detected_and_absolute_prefix_hand_calculation():
    grid=GridGraph(1,3)
    motion=ParticleMotion([[0],[1],[2],[0]],3,[71])
    cfg=dict(start=0,budget=3,p=[1.],q=np.array([.1,.7,.8]),motion=motion)
    result=completed(grid,cfg,(0,1,2,1),a=1)
    # t1 .3; t2 .06; t3 no target at1 => .06. t0 at0 is never sensed.
    assert result.J==pytest.approx(.42,abs=ATOL,rel=0)
    assert result.Pd==pytest.approx(.94,abs=ATOL,rel=0)


def test_future_identical_particles_are_weighted_by_posterior_not_original_mass():
    grid=GridGraph(2,2)
    cells=np.array([[0,2,3],[1,2,3],[2,2,3],[3,3,3],[1,1,3]])
    cfg=dict(start=0,budget=4,p=[.6,.3,.1],q=.78,
             motion=ParticleMotion(cells,4,[55,3,91]))
    path=(0,1,3,2,0)
    result=completed(grid,cfg,path,a=1)
    prefix=score_path(grid,path[:2],**dict(cfg,budget=1))
    assert prefix.final_belief[0]==pytest.approx(.132)
    assert prefix.final_belief[1]==pytest.approx(.3)
    assert result.J>=prefix.J


def test_free_endpoint_can_change_and_no_wait_is_allowed():
    grid=GridGraph(1,3)
    motion=ParticleMotion([[0],[1],[2]],3,[7])
    cfg=dict(start=0,budget=2,p=[1.],q=.78,motion=motion)
    result=completed(grid,cfg,(0,1,0))
    assert tuple(result.path)==(0,1,2)
    assert result.J==pytest.approx(.2684,abs=ATOL,rel=0)
    assert result.Pd==pytest.approx(.9516,abs=ATOL,rel=0)


def test_unobserved_time_gaps_still_contribute_to_objective():
    grid=GridGraph(1,2)
    # The only particle is outside for t1..t3, then detected at t4.
    motion=ParticleMotion([[0],[2],[2],[2],[0]],2,[19])
    cfg=dict(start=0,budget=4,p=[1.],q=1.,motion=motion)
    r=completed(grid,cfg,(0,1,0,1,0))
    assert r.J==pytest.approx(3.,abs=ATOL,rel=0)
    assert r.Pd==pytest.approx(1.,abs=ATOL,rel=0)


def test_repeated_detection_multiplies_remaining_weight():
    grid=GridGraph(1,2)
    cfg=dict(start=0,budget=4,p=[1.],q=.78,
             motion=ParticleMotion([[1]]*5,2,[31]))
    r=completed(grid,cfg,(0,1,0,1,0))
    assert r.J==pytest.approx(.5368,abs=ATOL,rel=0)
    assert r.Pd==pytest.approx(.9516,abs=ATOL,rel=0)


@pytest.mark.parametrize("horizon", [49,60])
def test_long_horizon_small_survival_remains_within_original_replay_tolerance(horizon):
    grid=GridGraph(1,2)
    cfg=dict(start=0,budget=horizon,p=[.8,.2],q=.78,
             motion=ParticleMotion(np.tile([1,2],(horizon+1,1)),2,[81,4]))
    path=tuple(t%2 for t in range(horizon+1))
    r=completed(grid,cfg,path)
    expected=sum(.2+.8*.22**((t+1)//2) for t in range(1,horizon+1))
    assert r.J==pytest.approx(expected,abs=ATOL,rel=0)


def test_different_histories_at_same_depth_vertex_remain_distinct():
    grid=GridGraph(2,2)
    cells=np.tile([1,2],(5,1))
    cfg=dict(start=0,budget=4,p=[.8,.2],q=.78,motion=ParticleMotion(cells,4,[51,13]))
    a=(0,1,3,1,0);b=(0,2,3,1,0)
    ra=completed(grid,cfg,a,2);rb=completed(grid,cfg,b,2)
    assert ra.J!=pytest.approx(rb.J,abs=ATOL,rel=0)
    assert ra.path[2]==rb.path[2]==3


@pytest.mark.parametrize("radius", [None,0,1])
def test_fixed_full_prefix_is_exact_and_does_not_change_input(radius):
    grid,cfg,path=case()
    cells=cfg["motion"].cell_ids.copy();ids=cfg["motion"].trajectory_ids.copy();p=cfg["p"].copy()
    result=completed(grid,cfg,path,cfg["budget"],radius)
    assert tuple(result.path)==path
    assert np.array_equal(cells,cfg["motion"].cell_ids)
    assert np.array_equal(ids,cfg["motion"].trajectory_ids)
    assert np.array_equal(p,cfg["p"])


def test_nontrivial_repair_preserves_particle_ids_and_permutation_invariance():
    grid,cfg,path=case(1043)
    original=cfg["motion"]
    before_cells=original.cell_ids.copy();before_ids=original.trajectory_ids.copy()
    r=completed(grid,cfg,path)
    order=np.arange(original.state_size)[::-1]
    other=ParticleMotion(original.cell_ids[:,order],grid.size,original.trajectory_ids[order])
    swapped=completed(grid,dict(cfg,p=cfg["p"][order],motion=other),path)
    assert swapped.J==pytest.approx(r.J,abs=ATOL,rel=0)
    assert np.array_equal(original.cell_ids,before_cells)
    assert np.array_equal(original.trajectory_ids,before_ids)
    assert not original.cell_ids.flags.writeable and not original.trajectory_ids.flags.writeable


def test_zero_horizon_single_vertex_preserves_mass():
    grid=GridGraph(1,1)
    cfg=dict(start=0,budget=0,p=[.7,.3],q=1.,motion=ParticleMotion([[0,1]],1,[1,2]))
    r=completed(grid,cfg,(0,))
    assert r.J==0 and r.Pd==0


def test_single_vertex_positive_horizon_has_no_valid_incumbent():
    grid=GridGraph(1,1)
    cfg=dict(start=0,budget=1,p=[1.],q=1.,motion=ParticleMotion([[0],[0]],1,[1]))
    with pytest.raises(ValueError):solve_exact_repair(grid,**cfg,initial_path=(0,0))


@pytest.mark.parametrize("option", [dict(max_seconds=0.),dict(max_memory_bytes=0)])
def test_zero_budget_is_explicit_and_retains_incumbent(option):
    grid,cfg,path=case()
    r=solve_exact_repair(grid,**cfg,initial_path=path,**option)
    assert r.status=="budget_exceeded"
    assert r.stop_reason in ("max_seconds","max_memory_bytes")
    assert tuple(r.path)==path and not r.theory_certified
    replay=score_path(grid,path,**cfg)
    assert r.J==pytest.approx(replay.J,abs=ATOL,rel=0)
    assert r.Pd==pytest.approx(replay.pd_final,abs=ATOL,rel=0)


def test_zero_node_limit_never_loses_feasible_incumbent():
    grid,cfg,path=case(1043)
    r=solve_exact_repair(grid,**cfg,initial_path=path,node_limit=0)
    assert r.status in ("completed","budget_exceeded")
    if r.status=="budget_exceeded":assert r.stop_reason in ("node_limit","max_seconds","solver_limit")
    assert r.J<=score_path(grid,path,**cfg).J+ATOL
    assert score_path(grid,r.path,**cfg).J==pytest.approx(r.J,abs=ATOL,rel=0)
    assert not r.theory_certified


@pytest.mark.parametrize("node_cap", [1,2])
def test_positive_node_cap_reports_native_limit_without_losing_incumbent(node_cap):
    rng=np.random.default_rng(728);grid=GridGraph(3,3);T=10;N=20
    motion=ParticleMotion(rng.integers(0,9,(T+1,N)),9,np.arange(N))
    path=[4]
    for _ in range(T):path.append(int(rng.choice(grid.neighbors(path[-1]))))
    cfg=dict(start=4,budget=T,p=np.ones(N)/N,q=.78,motion=motion)
    r=solve_exact_repair(grid,**cfg,initial_path=path,node_limit=node_cap)
    assert r.status in ("completed","budget_exceeded")
    if r.status=="budget_exceeded":assert r.stop_reason=="node_limit"
    assert r.J<=score_path(grid,path,**cfg).J+ATOL
    assert score_path(grid,r.path,**cfg).J==pytest.approx(r.J,abs=ATOL,rel=0)
    if r.restricted_lower_bound is not None:assert r.restricted_lower_bound<=r.J+ATOL
    assert not r.theory_certified


@pytest.mark.parametrize("q", [-.1,1.1,np.nan,[.2,.3]])
def test_invalid_sensor_probabilities_are_rejected(q):
    grid,cfg,path=case()
    cfg["q"]=q
    with pytest.raises(ValueError):solve_exact_repair(grid,**cfg,initial_path=path)


@pytest.mark.parametrize("options", [dict(prefix_depth=-1),dict(prefix_depth=99),
    dict(corridor_radius=-1),dict(max_seconds=-1),dict(max_memory_bytes=-1),
    dict(node_limit=-1),dict(mip_rel_gap=-1)])
def test_invalid_restriction_or_budget_is_rejected(options):
    grid,cfg,path=case()
    with pytest.raises(ValueError):solve_exact_repair(grid,**cfg,initial_path=path,**options)


def test_matrix_motion_is_not_silently_approximated_as_particles():
    grid,cfg,path=case()
    cfg.update(motion=MatrixMotion.identity(9),p=np.ones(9)/9)
    with pytest.raises((ValueError,TypeError)):
        solve_exact_repair(grid,**cfg,initial_path=path)


@pytest.mark.parametrize("corrupt", ["fractional", "dual_above_feasible", "objective_mismatch"])
def test_numerical_solver_claim_is_not_trusted_without_validation(monkeypatch,corrupt):
    real=module.milp
    def fake(*args,**kwargs):
        result=real(*args,**kwargs)
        assert result.status==0
        if corrupt=="fractional":
            result.x=np.asarray(result.x).copy()
            binary=np.flatnonzero(np.asarray(kwargs["integrality"])==1)
            assert binary.size
            result.x[binary[0]]=.5
        elif corrupt=="dual_above_feasible":result.mip_dual_bound=1e6
        else:result.fun+=.25
        return result
    monkeypatch.setattr(module,"milp",fake)
    grid,cfg,path=case(1043)
    r=solve_exact_repair(grid,**cfg,initial_path=path)
    assert r.status=="blocked"
    assert r.stop_reason and not r.theory_certified
    assert tuple(r.path)==path
    assert r.J==pytest.approx(score_path(grid,path,**cfg).J,abs=ATOL,rel=0)


@pytest.mark.parametrize("status", [1,2,4])
def test_solver_no_incumbent_status_is_explicit(monkeypatch,status):
    answer=SimpleNamespace(status=status,success=False,message="Time limit reached" if status==1 else "failure",
        x=None,fun=None,mip_dual_bound=None,mip_gap=None,mip_node_count=0)
    monkeypatch.setattr(module,"milp",lambda *args,**kwargs:answer)
    grid,cfg,path=case(1043)
    r=solve_exact_repair(grid,**cfg,initial_path=path)
    assert r.status==("budget_exceeded" if status==1 else "blocked")
    assert r.stop_reason and not r.theory_certified
    assert tuple(r.path)==path
    assert r.restricted_lower_bound is None


@pytest.mark.parametrize("node_cap,message,expected", [
    (1,"The HiGHS status code was not recognized. (HiGHS Status 16: model_status is Solution limit reached; primal_status is None)","budget_exceeded"),
    (None,"The HiGHS status code was not recognized. (HiGHS Status 16: model_status is Solution limit reached; primal_status is None)","blocked"),
    (1,"The HiGHS status code was not recognized. (HiGHS Status 4: failure)","blocked"),
    (1,"HiGHS Status 16: unknown internal failure", "blocked"),
])
def test_native_limit_compatibility_mapping_is_narrow(monkeypatch,node_cap,message,expected):
    answer=SimpleNamespace(status=4,success=False,message=message,x=None,fun=None,
        mip_dual_bound=None,mip_gap=None,mip_node_count=0)
    monkeypatch.setattr(module,"milp",lambda *args,**kwargs:answer)
    grid,cfg,path=case(1043)
    r=solve_exact_repair(grid,**cfg,initial_path=path,node_limit=node_cap)
    assert r.status==expected
    if expected=="budget_exceeded":assert r.stop_reason=="node_limit"
    assert r.solver_status==4 and r.solver_message==message
    assert tuple(r.path)==path and r.restricted_lower_bound is None
    assert not r.theory_certified
