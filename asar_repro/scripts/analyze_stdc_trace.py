"""Reproduce supplementary trace analysis and an isolated h-only profile."""
import argparse
from collections import Counter,defaultdict
import cProfile
import hashlib
import io
import json
from pathlib import Path
import pstats
from time import perf_counter
import numpy as np
from asar_repro.heuristic import Heuristic
from asar_repro.objective import score_path
from stdc_validation_guards import ROOT,load_real,read,save


def main(out):
    _,graph,cfg,_,_,_=load_real()
    prior=ROOT/'outputs/stdc_v0_2/local_validation_20261123_r5'
    paper=read(prior/'paired_comparison/paper_greedy_eps_1p1_rep_0/paper_greedy.json')
    score=score_path(graph,paper['path'],**cfg,record_beliefs=True)
    keys=[(d,v,hashlib.sha256(np.asarray(score.beliefs[d],dtype='<f8').tobytes()).hexdigest())
          for d,v in enumerate(paper['path'])]
    totals=[];states=[];bounds=read(out/'path_bounds.json')
    for mode in ['mass_lb','stdc_lb','paper_greedy']:
        events=[json.loads(s) for s in (out/f'{mode}.trace.jsonl').read_text().splitlines()]
        calls=[r for r in events if r['event'] in ('push','prune')]
        pops=[r for r in events if r['event']=='pop']
        popkeys={(r['depth'],r['vertex'],r['belief_sha']) for r in pops}
        pushkeys={(r['depth'],r['vertex'],r['belief_sha']) for r in calls if r['event']=='push'}
        fcounts=Counter(r['f_weighted'] for r in pops);gs=defaultdict(set)
        for r in pops:gs[(r['depth'],r['vertex'],r['belief_sha'])].add(r['g'])
        hits=[d for d,k in enumerate(keys) if k in popkeys]
        next_depth=max(hits)+1 if max(hits)<49 else None
        next_key=keys[next_depth] if next_depth is not None else None
        next_pushes=[r for r in calls if r['event']=='push' and
            (r['depth'],r['vertex'],r['belief_sha'])==next_key and r['g']==float(score.g[next_depth])]
        totals.append(dict(mode=mode,paper_prefix_equivalent_states_popped=hits,
            next_paper_prefix=next((r for r in bounds if r['path']=='paper_1p1' and r['depth']==next_depth),None),
            next_paper_prefix_pushes_with_matching_g=next_pushes,
            max_same_f_pop_multiplicity=max(fcounts.values()),
            pop_states_with_multiple_g=sum(len(v)>1 for v in gs.values()),most_common_f=fcounts.most_common(3),
            exact_statement='belief-byte identity does not imply same g or same path'))
        states.extend(dict(mode=mode,depth=d,pushed=k in pushkeys,popped=k in popkeys) for d,k in enumerate(keys))
        summary=read(out/f'{mode}.json')
        summary.update(actual_max_expanded_depth=max(r['depth'] for r in pops[:-1]),
            generated_complete_candidates=sum(r['depth']==49 for r in calls),
            remaining_step_iterations=sum(49-r['depth'] for r in calls) if mode!='mass_lb' else None,
            depth_49_pops=sum(r['depth']==49 for r in pops))
        save(out/f'{mode}.json',summary)
    root=read(out/'root_decomposition.json');roots=read(prior/'random_audit/random_audit.json')['roots']
    save(out/'mechanism_evidence.json',dict(prefix_progress=totals,
        root_coupling_gain=root['root_h']['stdc_lb']-root['root_h']['stepwise_lb'],
        root_capacity_gain=root['root_h']['stdc_lb']-root['root_h']['capacity_lb'],
        toy_roots_with_coupling_gain_gt_1e_8=sum(r['values']['stdc_lb']>r['values']['stepwise_lb']+1e-8 for r in roots),
        toy_root_count=len(roots),paper_path_mass_at_20=float(score.survival[20]),
        paper_path_cost_after_20=float(score.survival[21:].sum()),
        relaxed_root_mass_at_20=root['rows'][19]['ell'],relaxed_root_cost_after_20=root['tail_after_20']))
    save(out/'known_path_prefix_progress.json',states)
    # Never replace an existing measured profile when regenerating tables.
    if not (out/'heuristic_profile.json').exists():
        h=Heuristic(graph,budget=49,q=.78,motion=cfg['motion'],mode='stdc_lb')
        prof=cProfile.Profile();tic=perf_counter();prof.enable()
        for _ in range(100):
            for d in range(14):h(paper['path'][d],d,score.beliefs[d])
        prof.disable();wall=perf_counter()-tic
        prof.dump_stats(str(out/'heuristic_diagnostic.pstats'))
        stream=io.StringIO();pstats.Stats(prof,stream=stream).strip_dirs().sort_stats('cumulative').print_stats(25)
        (out/'heuristic_profile.txt').write_text(stream.getvalue(),encoding='utf-8')
        entries=[dict(file=f,line=line,function=name,primitive_calls=p,calls=n,self_s=s,cumulative_s=c)
                 for (f,line,name),(p,n,s,c,_) in pstats.Stats(prof).stats.items()]
        save(out/'heuristic_profile.json',dict(scope='1400 h evaluations on frozen paper route depths 0..13; NOT a search benchmark',
            epsilon=None,budget_changed=False,calls=1400,wall_s=wall,rows=sorted(entries,key=lambda r:r['cumulative_s'],reverse=True)[:30]))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    main(parser.parse_args().output_dir.resolve())
