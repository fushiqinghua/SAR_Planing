"""Opt-in shared-budget orchestration; frozen planners and scorer stay unchanged."""
from dataclasses import asdict
from math import inf, isfinite
from time import perf_counter

from .grid import integer
from .heuristic import Heuristic
from .particle_dp import ParticleDP
from .resumable_search import SearchSession

ATOL = 1e-10

def search_adaptive(grid, *, start, budget, p, q, motion, initial_path,
                    schedule="direct", dp_kind="none", dp_mode="max",
                    efficient_guide=False, lazy_rollout=True, diversity_slots=0,
                    max_expansions=None, max_seconds=None, max_open=None,
                    dp_memory_bytes=128*2**20, global_chunk=512, burst_work=128,
                    local_fraction=.1, trace=None):
    """All preprocessing/global/local work shares one absolute deadline.

    direct: resumable STDC control; recycle: old midpoint then resume global;
    bursts: opt-in short windows, interleaved with retained global frontier.
    Partial/local completion never certifies the global result.
    """
    if schedule not in ("direct", "recycle", "bursts"):
        raise ValueError("unsupported schedule")
    if dp_kind not in ("none", "dense", "compact") or dp_mode not in ("max", "only"):
        raise ValueError("unsupported DP mode")
    for name, value in (("max_expansions", max_expansions), ("max_open", max_open)):
        if value is not None: integer(value, name)
    integer(global_chunk, "global_chunk", 1); integer(burst_work, "burst_work", 1)
    if not 0 <= local_fraction < 1: raise ValueError("invalid local fraction")
    if max_seconds is not None and (max_seconds < 0 or not isfinite(max_seconds)):
        raise ValueError("invalid time budget")
    started=perf_counter()
    deadline=inf if max_seconds is None else started+max_seconds
    cfg=dict(start=start,budget=budget,p=p,q=q,motion=motion)
    phases=[];prep={};local_work=local_generated=local_pruned=0;peak=0
    dp=None;guide=None;roll=None;attempted_old=False;resumed=False
    next_local_global=0;local_stalls=0
    bound=Heuristic(grid,budget=budget,q=q,motion=motion,mode="stdc_lb")
    stdc_component=bound
    if dp_kind != "none":
        if dp_kind=="compact":
            from .compact_particle_dp import CompactParticleDP
            dp=CompactParticleDP(grid,start=start,budget=budget,q=q,motion=motion,
                deadline=deadline,max_memory_bytes=dp_memory_bytes)
        else:
            dp=ParticleDP(grid,budget=budget,q=q,motion=motion,
                deadline=deadline,max_memory_bytes=dp_memory_bytes)
        prep["dp"]=dict(dp.build_info)
        prep["dp_fallback"]=not dp.ready
        prep["fallback_policy"]="unfinished DP uses STDC under the unchanged remaining global deadline"
        if dp.ready:
            stdc=bound
            bound=dp if dp_mode=="only" else lambda v,d,b:max(stdc(v,d,b),dp(v,d,b))
        else: dp=None
    if efficient_guide:
        from .sparse_particle_guide import SparseParticleGuide
        guide=SparseParticleGuide(grid,budget=budget,q=q,motion=motion)
    prep["method_preprocessing_s"]=perf_counter()-started
    session=SearchSession(grid,**cfg,initial_path=initial_path,guide_weight=1.04,
        bound=bound,guide=guide,max_open=max_open,deadline=deadline,
        bound_mode=('dp_only' if dp_mode=='only' else 'stdc_dp') if dp is not None else 'stdc_lb')
    session_offset=session.started-started
    def remaining_work():
        return None if max_expansions is None else max(0,max_expansions-session.expanded-local_work)
    def quota(wanted):
        rem=remaining_work()
        return wanted if rem is None else min(wanted,rem)
    def record(kind,before,after,tic):
        phases.append(dict(name=kind,expanded=after.expanded-before,
            total_work=session.expanded+local_work,wall_s=perf_counter()-tic,
            J=after.J,Pd=after.Pd,status=after.status,stop_reason=after.stop_reason,
            frontier=session.frontier_count))
    def annotate_events():
        for event in session.incumbent_history+session.candidate_archive:
            if 'global_expanded_at_accept' not in event:
                event['global_expanded_at_accept']=event['expanded']
                event['expanded']+=local_work
                event['work_expanded']=event['expanded']
    def global_step(work,until):
        nonlocal resumed,peak
        held=0 if roll is None else roll.frontier_count
        session.max_open=None if max_open is None else max(0,max_open-held)
        before=session.expanded;tic=perf_counter()
        result=session.advance(max_expansions=work,deadline=until)
        peak=max(peak,held+result.stats.get('advance_peak_open',0))
        annotate_events()
        record("global_stdc",before,result,tic)
        if attempted_old and result.expanded>before:resumed=True
        return result
    result=session.finish()
    while True:
        if perf_counter()>=deadline:
            result=session.finish(stop_reason="max_seconds");break
        rem=remaining_work()
        if rem==0:
            result=session.finish(stop_reason="max_expansions");break
        if result.status in ("completed","budget_exceeded"):break
        if schedule=="recycle" and not attempted_old:
            seed_quota=None if max_expansions is None else int(.4*max_expansions)
            seed_deadline=started+(.4*max_seconds) if max_seconds is not None else inf
            result=global_step(seed_quota,min(deadline,seed_deadline))
            attempted_old=True
            if result.status in ("completed","budget_exceeded"):continue
            available=None if max_open is None else max(0,max_open-session.frontier_count)
            if available==0:continue
            from .midpoint_rollout import search_midpoint
            tic=perf_counter()
            local=search_midpoint(grid,**cfg,initial_path=session.path,bound=bound,
                beam_width=24,diversity=False,max_expansions=remaining_work(),
                max_seconds=max(0,deadline-perf_counter()) if deadline!=inf else None,
                max_open=available)
            local_work+=local.expanded;local_generated+=local.generated;local_pruned+=local.pruned
            peak=max(peak,session.frontier_count+local.peak_open)
            session.inject_incumbent(local.path,source="midpoint_rollout")
            annotate_events()
            phases.append(dict(name="old_midpoint",expanded=local.expanded,
                total_work=session.expanded+local_work,wall_s=perf_counter()-tic,
                J=local.J,Pd=local.Pd,status=local.status,stop_reason=local.stop_reason,
                stats=local.stats,incumbent_history=local.incumbent_history))
            continue
        result=global_step(quota(global_chunk),deadline)
        if schedule!="bursts" or result.status in ("completed","budget_exceeded"):
            continue
        if session.expanded<next_local_global:continue
        # Limit local work to a fraction of already paid global work; no free seed.
        allowance=int(session.expanded*local_fraction/(1-local_fraction))-local_work
        if allowance<=0 or quota(min(burst_work,allowance))==0:continue
        if session.incumbent_source=="initial_path":continue
        available=None if max_open is None else max(0,max_open-session.frontier_count)
        if available==0:continue
        from .short_window_rollout import BurstRollout
        if roll is None:
            roll=BurstRollout(grid,**cfg,initial_path=session.path,
                quality_width=24,diversity_slots=diversity_slots,
                lazy_bound=lazy_rollout,trace=trace)
        else:roll.set_incumbent(session.path)
        before=roll.expanded;before_generated=roll.generated;before_pruned=roll.pruned;tic=perf_counter()
        windows_before=roll.stats['windows_completed'];previous_J=session.J
        local=roll.advance(max_expansions=quota(min(burst_work,allowance)),
            deadline=min(deadline,perf_counter()+.1),max_open=available)
        used=local.expanded-before;local_work+=used
        local_generated+=local.generated-before_generated;local_pruned+=local.pruned-before_pruned
        peak=max(peak,session.frontier_count+local.stats.get('advance_peak_open',local.peak_open))
        session.inject_incumbent(local.path,source="short_window_rollout")
        annotate_events()
        if session.J<previous_J-ATOL:
            local_stalls=0
            next_local_global=session.expanded+global_chunk
        elif roll.stats['windows_completed']>windows_before or roll.done:
            local_stalls+=1
            next_local_global=session.expanded+global_chunk*min(4,2**min(local_stalls,2))
        phases.append(dict(name="short_window",expanded=used,total_work=session.expanded+local_work,
            wall_s=perf_counter()-tic,J=local.J,Pd=local.Pd,status=local.status,
            stop_reason=local.stop_reason,stats=dict(local.stats),incumbent_history=local.incumbent_history))
    annotate_events()
    result=session.finish(stop_reason=result.stop_reason if result.status=="budget_exceeded" else None)
    result.expanded+=local_work;result.generated+=local_generated;result.pruned+=local_pruned
    result.peak_open=max(result.peak_open,peak)
    for e in result.incumbent_history+result.candidate_archive:
        e["elapsed_s"]+=session_offset
    result.stats.update(work_expanded=result.expanded,global_expanded=session.expanded,
        local_expanded=local_work,global_resumed_after_rollout=resumed,
        dp_fallback=prep.get("dp_fallback",False),dp_kind=dp_kind,
        physical_open_scope="simultaneously retained global and local states",
        original_goal_unchanged=True,global_epsilon_certified=False,
        local_stalls=local_stalls,local_fraction_cap=local_fraction,
        phase_count=len(phases),method_preprocessing_s=prep["method_preprocessing_s"])
    if roll is not None:result.stats["rollout"]=dict(roll.stats)
    if guide is not None:result.stats["guide_memory"]=guide.cache_info()
    elif hasattr(session.guide,'_reachable'):
        rings=session.guide._reachable
        result.stats['guide_memory']=dict(reach_array_bytes=sum(a.nbytes for rows in rings.values() for a in rows),
            vertices=len(rings),scope='reference retained integer reach arrays; Python objects excluded')
    stdc_impl=getattr(stdc_component,'_stdc',None)
    if stdc_impl is not None:
        result.stats['stdc_geometry_memory']=dict(stdc_impl.geometry_cache_info(),
            distance_array_bytes=sum(a.nbytes for a in stdc_impl._distances.values()))
    result.wall_s=perf_counter()-started
    result.stats["deadline_overshoot_s"]=max(0,started+result.wall_s-deadline)
    return result,phases,prep,result.wall_s

