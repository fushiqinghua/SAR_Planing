"""Read-only reconstruction of local rollout work from frozen phase histories."""
import json, hashlib, sys
from pathlib import Path
from collections import Counter, defaultdict
import numpy as np

ROOT=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from run_adaptive_experiments import load_case
from run_optimization_validation import sources
from asar_repro.short_window_rollout import BurstRollout,ATOL

OLD=ROOT/'outputs/stdc_v0_2/adaptive_20261124'
OUT=Path(__file__).parent
def save(name,x): (OUT/name).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def key(path): return hashlib.sha256(json.dumps(list(path)).encode()).hexdigest()

class RecordedBurst(BurstRollout):
    def __init__(self,*args,**kwargs):
        self.records=[]; self.events=[]
        super().__init__(*args,trace=self.events.append,**kwargs)
    def _candidate(self,route,belief,g):
        task=self.task;b=task['b'];a=task['a']
        complete=route+task['original'][b+1:]
        J=g+float(task['coeff'].cost[b]@belief)
        Pd=1.-float(task['coeff'].survival[b]@belief)
        self.records.append(dict(a=a,b=b,length=b-a,path=list(complete),path_sha=key(complete),
            incumbent_path=list(self.path),incumbent_sha=key(self.path),same_as_incumbent=complete==self.path,
            J=J,Pd=Pd,incumbent_J=self.score.J,incumbent_Pd=self.score.pd_final,
            delta_J=J-self.score.J,delta_Pd=Pd-self.score.pd_final,
            local_work=self.expanded,window_segment=list(route[a:b+1])))
        return super()._candidate(route,belief,g)

def main():
    frozen=json.loads((OLD/'freeze.json').read_text(encoding='utf-8'))
    assert sources()==frozen['source_sha256'], 'production source SHA changed'
    cases={s:load_case(s) for s in ['lake_ontario','arctic_ocean','bay_of_fundy']}
    rows=[];allcand=[]; comparisons=[]
    for source in sorted((OLD/'benchmark').glob('*/raw_result.json')):
        raw=json.loads(source.read_text(encoding='utf-8'))
        phases=[x for x in raw['phases'] if x['name']=='short_window']
        if not phases:continue
        row=json.loads((source.parent/'result.json').read_text(encoding='utf-8'))
        # Result files have standalone row metadata.
        scene=row['scenario']; grid,cfg,rec=cases[scene]
        roll=RecordedBurst(grid,**cfg,initial_path=phases[0]['incumbent_history'][0]['path'],
            lazy_bound=row['variant']!='short_eager',diversity_slots=4 if row['variant'] in ('short_diverse','adaptive_combo') else 0)
        for i,phase in enumerate(phases):
            roll.set_incumbent(phase['incumbent_history'][-1]['path'])
            res=roll.advance(max_expansions=phase['expanded'])
            fields=['complete_candidates','accepted_improvements','work_expanded','windows_completed',
                    'beam_discarded','external_updates','proposal_resets','reset_discarded','diversity_extra_retained']
            differences={k:[phase['stats'][k],res.stats[k]] for k in fields if phase['stats'][k]!=res.stats[k]}
            comparisons.append(dict(run=source.parent.name,phase=i,differences=differences))
        for c in roll.records:c.update(run=source.parent.name,scene=scene,variant=row['variant'],protocol=row['protocol'],repeat=row['repeat'])
        allcand.extend(roll.records)
        starts=[x for x in roll.events if x['event']=='window_start']
        schedules=[x for x in roll.events if x['event']=='window_schedule']
        counts=Counter((x['a'],x['b']) for x in starts)
        rows.append(dict(run=source.parent.name,scene=scene,variant=row['variant'],protocol=row['protocol'],repeat=row['repeat'],
            candidates=len(roll.records),same_as_incumbent=sum(c['same_as_incumbent'] for c in roll.records),
            stats=roll.stats,local_pruned=roll.pruned,full_bound_pruned=sum(x['bound_pruned'] for x in roll.events if x['event']=='beam_select'),
            window_starts=starts,unique_window_intervals=len(counts),interval_counts=[dict(a=k[0],b=k[1],count=v) for k,v in counts.items()],
            schedule_first20=[dict(windows=x['windows'][:20],opportunity=x['opportunity']) for x in schedules],
            windows_available_per_schedule=len(schedules[0]['windows']) if schedules else 0,
            windows_started_by_length=dict(Counter(x['b']-x['a'] for x in starts)),
            original_counts=raw['result']['stats']['rollout']))
        print(source.parent.name,len(roll.records),sum(c['same_as_incumbent'] for c in roll.records),flush=True)
    assert sources()==frozen['source_sha256'], 'production source SHA changed during audit'
    summary=dict(status='passed' if all(not x['differences'] for x in comparisons) else 'reconstruction_mismatch',
        reconstruction_scope='Replays saved local expansion allocations and before-slice incumbents without wall-clock deadlines. Does not rerun global search or claim independent experiments.',
        original_candidate_paths_logged=False,source_sha_verified=True,real_archives_sha_verified=True,
        runs=len(rows),complete_candidates=len(allcand),same_as_incumbent=sum(c['same_as_incumbent'] for c in allcand),
        unique_scene_path_pairs=len(set((c['scene'],c['path_sha']) for c in allcand)),
        unique_scene_incumbent_window_path_pairs=len(set((c['scene'],c['incumbent_sha'],c['a'],c['b'],c['path_sha']) for c in allcand)),
        phase_checks=len(comparisons),phase_mismatches=[x for x in comparisons if x['differences']],
        totals={k:sum(r['stats'][k] for r in rows) for k in ['work_expanded','bound_calls','cheap_bound_calls','beam_discarded','proposal_resets','reset_discarded','diversity_extra_retained','windows_started','windows_completed']},
        per_scene={s:dict(candidates=sum(c['scene']==s for c in allcand),
            same_as_incumbent=sum(c['scene']==s and c['same_as_incumbent'] for c in allcand),
            unique_paths=len(set(c['path_sha'] for c in allcand if c['scene']==s)),
            intervals=sorted(set((c['a'],c['b']) for c in allcand if c['scene']==s)),
            candidate_lengths=dict(Counter(c['length'] for c in allcand if c['scene']==s)),
            available_windows_per_incumbent=next(r['windows_available_per_schedule'] for r in rows if r['scene']==s),
            completed_windows_range=[min(r['stats']['windows_completed'] for r in rows if r['scene']==s),max(r['stats']['windows_completed'] for r in rows if r['scene']==s)],
            started_unique_interval_range=[min(r['unique_window_intervals'] for r in rows if r['scene']==s),max(r['unique_window_intervals'] for r in rows if r['scene']==s)],
            max_abs_delta_J=max(abs(c['delta_J']) for c in allcand if c['scene']==s),
            diversity_extra_retained=sum(r['stats']['diversity_extra_retained'] for r in rows if r['scene']==s),
            beam_discarded=sum(r['stats']['beam_discarded'] for r in rows if r['scene']==s)) for s in cases},
        physical_direction_unverified={'bay_of_fundy':True})
    save('candidate_records.json',allcand);save('reconstructed_runs.json',rows);save('phase_checks.json',comparisons);save('summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
