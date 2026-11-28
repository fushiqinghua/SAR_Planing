"""Research-only queue policy around the unmodified H3 C0 and Lazy solvers."""
from contextlib import nullcontext
import heapq
import sys
from time import perf_counter
from unittest.mock import patch

from asar_repro import physical_lazy_prefix as lazy
from asar_repro import physical_refinement as c0
from asar_repro.physical_search import OBJECTIVE_ATOL, REPLAY_ATOL, _history_entry


EARLY_RATIO = .5
LAZY_POLICY_SECONDS = 29.75
BAND_RADIUS = 3
ROOTS_PER_TICK = 6
BEAM_WIDTH = 32
CHECKPOINTS = (5.0, 18.0)
WAVE_SECONDS = 3.0
GROWTH_WINDOW = 2.0
FINISH_MARGIN = .05


def settings():
    return dict(early_ratio=EARLY_RATIO, lazy_policy_seconds=LAZY_POLICY_SECONDS,
                band_radius=BAND_RADIUS, roots_per_tick=ROOTS_PER_TICK,
                beam_width=BEAM_WIDTH, checkpoints_s=list(CHECKPOINTS),
                wave_seconds=WAVE_SECONDS, growth_window_s=GROWTH_WINDOW,
                finish_margin_s=FINISH_MARGIN)


def coverage_ratio(survival):
    """Share of S30 terminal detection accumulated in its first quarter."""
    terminal = 1.0 - survival[-1]
    if terminal <= REPLAY_ATOL:
        return 0.0
    return (1.0 - survival[(len(survival)-1)//4]) / terminal


def entry_mode(survival):
    return "lazy" if coverage_ratio(survival) >= EARLY_RATIO else "single_global"


def rescue_eligible(*, first_terminal, previous_open, current_open):
    return first_terminal is None and previous_open is not None and current_open > previous_open > 0


def select_prefixes(heap, *, max_tick, per_tick=ROOTS_PER_TICK, band_radius=BAND_RADIUS):
    """Transient shortlist. The main heap and each exact state stay intact."""
    by_tick = {}
    for item in heap:
        key, serial, state, _path = item
        if abs(state.tick-max_tick) > band_radius:
            continue
        group = by_tick.setdefault(state.tick,{})
        incumbent = group.get(state.vertex)
        if incumbent is None or (key,serial)<incumbent[:2]:
            group[state.vertex] = item
    ranked = [
        heapq.nsmallest(per_tick, by_tick[tick].values(), key=lambda item:item[:2])
        for tick in sorted(by_tick,reverse=True)
    ]
    return [group[rank] for rank in range(per_tick) for group in ranked if rank<len(group)]


class _SideExpired(Exception):
    pass


class _SideBudget:
    def __init__(self, deadline):
        self.deadline = deadline

    def check(self):
        if perf_counter() >= self.deadline:
            raise _SideExpired


def bounded_completion(problem, guide, roots, *, connectivity, guide_weight, width, deadline, incumbent_j):
    """Search a narrow lane from actual OPEN states with unchanged propagation."""
    budget = _SideBudget(deadline)
    installed = patch.object(guide,"budget",budget) if hasattr(guide,"budget") else nullcontext()
    counters = dict(terminal_candidates=0,replays=0,generated=0,expanded=0,guide_calls=0,
                    peak_retained=0, layers=0, reason="exhausted",best_monotonic_s=None,
                    winning_root=None,late_replays=0)
    best = None
    best_j = incumbent_j
    beam = [(*item,len(item[3])) for item in roots]
    serial = max((item[1] for item in roots),default=-1)+1
    try:
        with installed:
            while beam:
                counters["layers"] += 1
                layer = {}
                for _f,_id,state,path,root_length in beam:
                    budget.check()
                    if state.terminal:
                        raise ValueError("A side search root must be an OPEN prefix")
                    if state.J >= best_j+OBJECTIVE_ATOL:
                        continue
                    counters["expanded"] += 1
                    for target in problem.neighbors(state.vertex,connectivity):
                        budget.check()
                        child=problem.advance(state,target,connectivity=connectivity)
                        counters["generated"] += 1
                        child_path=path+(target,)
                        budget.check()
                        if child.terminal:
                            counters["terminal_candidates"] += 1
                            if child.J >= best_j-OBJECTIVE_ATOL:
                                continue
                            score=problem.replay(child_path,connectivity=connectivity)
                            counters["replays"] += 1
                            done=perf_counter()
                            if done >= deadline:
                                counters["late_replays"] += 1
                                raise _SideExpired
                            if (abs(score["J"]-child.J)>REPLAY_ATOL
                                    or abs(score["pd_final"]-(1-float(child.weights.sum())))>REPLAY_ATOL
                                    or len(score["survival"])!=len(child.survival)
                                    or any(abs(a-b)>REPLAY_ATOL for a,b in zip(score["survival"],child.survival))):
                                raise AssertionError("Side transitions disagree with original physical replay")
                            if score["J"] < best_j-OBJECTIVE_ATOL:
                                best,best_j=score,score["J"]
                                counters["best_monotonic_s"]=done
                                counters["winning_root"]=list(child_path[:root_length])
                            continue
                        if child.J >= best_j+OBJECTIVE_ATOL:
                            continue
                        h=guide.remaining_cost(child)
                        counters["guide_calls"] += 1
                        item=(child.J+guide_weight*h,serial,child,child_path,root_length)
                        serial += 1
                        family=(child.tick,child.vertex)
                        seen=layer.get(family)
                        if seen is None or item[:2]<seen[:2]:
                            layer[family]=item
                        counters["peak_retained"]=max(counters["peak_retained"],len(beam)+len(layer))
                beam=heapq.nsmallest(width,layer.values(),key=lambda item:item[:2])
    except _SideExpired:
        counters["reason"]="wave_deadline"
    if not roots:
        counters["reason"]="empty_shortlist"
    return best,counters


def solve_original_lazy(problem, **options):
    controller=lazy._LazyProgressController
    with patch.object(lazy,"_LazyProgressController",lambda k,_:controller(k,LAZY_POLICY_SECONDS)):
        return lazy.solve_physical_lazy_prefix(problem,**options)


def solve_gated(problem, *, connectivity, initial_waypoints, max_seconds, **options):
    """Route early-coverage cases to Lazy, otherwise observe C0 and its live OPEN."""
    if options.get("objective","J")!="J":
        raise ValueError("This experiment is restricted to the original J objective")
    started=perf_counter()
    deadline=started+max_seconds
    initial_waypoints=tuple(initial_waypoints)
    score=problem.replay(initial_waypoints,connectivity=connectivity)
    ratio=coverage_ratio(score["survival"])
    mode=entry_mode(score["survival"])
    detail=dict(mode=mode,initial_coverage_ratio=ratio,first_main_terminal_s=None,
                first_main_terminal_observed=False,checks=[],attempts=[],side_improvements=[],
                selected_source="lazy" if mode=="lazy" else "main",configuration=settings())

    def remaining():
        return max(0.,deadline-perf_counter())

    if mode=="lazy":
        result=solve_original_lazy(problem,connectivity=connectivity,initial_waypoints=initial_waypoints,
                                   max_seconds=remaining(),**options)
        detected=result["diagnostics"]["first_search_terminal_generated_s"]
        if detected is not None:
            detail.update(first_main_terminal_s=detected,first_main_terminal_observed=True)
        result["diagnostics"]["gated"]=detail
        return result

    execute=c0.solve_physical_refinement
    guide_class=c0._CoarseCellGuide
    advance=c0.CachedPhysicalProblem.advance
    replay=c0.CachedPhysicalProblem.replay
    next_checkpoint=0
    anchor=None
    peak_tick=0
    guide=None
    incumbent=score["J"]
    contenders=[]

    class ObservedGuide(guide_class):
        def __init__(self,*args,**kwargs):
            nonlocal guide
            super().__init__(*args,**kwargs)
            guide=self

    def observed_replay(self,route,connectivity=4):
        nonlocal incumbent
        result=replay(self,route,connectivity=connectivity)
        if sys._getframe(1).f_code is not bounded_completion.__code__:
            incumbent=min(incumbent,result["J"])
        return result

    def disarm():
        c0.heapq=heapq
        c0.CachedPhysicalProblem.advance=advance
        c0.CachedPhysicalProblem.replay=replay

    def observed_advance(self,state,target,connectivity=4):
        child=advance(self,state,target,connectivity=connectivity)
        if child.terminal and sys._getframe(1).f_code is execute.__code__:
            detail["first_main_terminal_s"]=perf_counter()-started
            detail["first_main_terminal_observed"]=True
            disarm()
        return child

    class ObservedHeap:
        heappush=staticmethod(heapq.heappush)
        heapify=staticmethod(heapq.heapify)

        @staticmethod
        def heappop(heap):
            nonlocal anchor,next_checkpoint,peak_tick,incumbent
            elapsed=perf_counter()-started
            threshold=CHECKPOINTS[next_checkpoint]
            if anchor is None and elapsed>=threshold-GROWTH_WINDOW:
                anchor=len(heap)
            if elapsed>=threshold:
                eligible=rescue_eligible(first_terminal=detail["first_main_terminal_s"],
                                          previous_open=anchor,current_open=len(heap))
                detail["checks"].append(dict(checkpoint_s=threshold,elapsed_s=elapsed,max_tick=peak_tick,
                                              previous_open=anchor,open_count=len(heap),eligible=eligible))
                next_checkpoint += 1
                anchor=None
                if eligible:
                    start_wave=perf_counter()
                    wave_deadline=min(deadline-FINISH_MARGIN,start_wave+WAVE_SECONDS)
                    if guide is None:
                        raise AssertionError("Queue rescue ran before guide initialization")
                    roots=select_prefixes(heap,max_tick=peak_tick)
                    selected,new=bounded_completion(
                        guide.problem,guide,roots,connectivity=connectivity,
                        guide_weight=options.get("guide_weight",1.04),width=BEAM_WIDTH,
                        deadline=wave_deadline,incumbent_j=incumbent,
                    )
                    detail["attempts"].append(dict(
                        **new,checkpoint_s=threshold,opened_elapsed_s=elapsed,
                        wall_s=perf_counter()-start_wave,
                        shortlist=[dict(f=f,serial=n,vertex=state.vertex,tick=state.tick,
                                        depth=len(path)-1,path=list(path)) for f,n,state,path in roots],
                        best_J=selected["J"] if selected else None,
                        best_Pd=selected["pd_final"] if selected else None,
                    ))
                    if selected is not None:
                        found_at=new["best_monotonic_s"]-started
                        incumbent=selected["J"]
                        contenders.append((found_at,selected))
                if next_checkpoint==len(CHECKPOINTS):
                    disarm()
            if perf_counter()>=deadline:
                raise c0._Deadline
            item=heapq.heappop(heap)
            peak_tick=max(peak_tick,item[2].tick)
            return item

    core_started=perf_counter()
    with (patch.object(c0,"heapq",ObservedHeap),patch.object(c0,"_CoarseCellGuide",ObservedGuide),
          patch.object(c0.CachedPhysicalProblem,"advance",observed_advance),
          patch.object(c0.CachedPhysicalProblem,"replay",observed_replay)):
        result=execute(problem,connectivity=connectivity,initial_waypoints=initial_waypoints,
                       max_seconds=remaining(),**options)
    result["diagnostics"]["gated"]=detail
    if not contenders or result["error"] is not None:
        return result

    # The side lane records every retained candidate separately. The primary
    # C0 frontier has never pruned with any unreplayed side state.
    detail["side_improvements"]=[_history_entry(s,t,"bounded_completion") for t,s in contenders]
    detail["archive_scope"]="C0 Pareto evidence unchanged; fully replayed side awards recorded separately"
    best_time,best=min(contenders,key=lambda entry:entry[1]["J"])
    if result["J"] is not None and best["J"]>=result["J"]-OBJECTIVE_ATOL:
        return result
    offset=core_started-started
    events=sorted([dict(row,elapsed_s=row["elapsed_s"]+offset) for row in result["history"]]
                  +detail["side_improvements"],key=lambda row:row["elapsed_s"])
    history=[]
    for item in events:
        if not history or item["J"]<history[-1]["J"]-OBJECTIVE_ATOL:
            history.append(item)
    detail["selected_source"]="bounded_completion"
    detail["original_main_J"]=result["J"]
    detail["original_main_Pd"]=result["pd_final"]
    result.update(best=best,best_elapsed_s=best_time,history=history,J=best["J"],pd_final=best["pd_final"],
                  waypoints=best["waypoints"],path=best["waypoints"],survival=best["survival"])
    return result
