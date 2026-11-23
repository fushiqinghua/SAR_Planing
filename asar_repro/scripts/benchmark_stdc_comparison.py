"""Paired baseline/STDC comparison after the declared validation gates pass.

Use the frozen B7 inputs, objective, initial incumbent and budgets. No optimizer
changes, forcing changes, drift calls, or dropped budget-stop rows are allowed.
"""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter
import traceback

from stdc_validation_guards import ROOT, load_real, read, save, require, digest


def main(run):
    require(run.is_relative_to(ROOT/'outputs/stdc_v0_2'), 'research output directory required')
    validation=read(run/'validation_summary.json')
    require(validation['status']=='passed' and not validation['not_run'], 'all validation stages must pass')
    plan=read(run/'comparison_plan.json')
    require(plan['modes']==['paper_greedy','mass_lb','stdc_lb'] and plan['planned_runs']==27,
            'comparison plan changed')
    protocol,_,_,pt,_,raw=load_real()
    require(plan['epsilons']==protocol['epsilon'] and plan['repeats']==3, 'frozen epsilon/repeat mismatch')
    require(plan['limits']==protocol['search_limits'], 'comparison budget changed')
    output=run/'paired_comparison'
    output.mkdir(exist_ok=False)
    rows=[]; started=perf_counter()
    summary=dict(status='running',planned_runs=27,started_utc=datetime.now(timezone.utc).isoformat(),
                 plan_sha256=digest(run/'comparison_plan.json'),verified_raw_sources=raw,PT_J=pt.J)
    save(output/'summary.json',summary)
    try:
        for epsilon in plan['epsilons']:
            for repeat in range(plan['repeats']):
                modes=plan['modes'][repeat:]+plan['modes'][:repeat]
                for mode in modes:
                    run_id=f"{mode}_eps_{str(epsilon).replace('.','p')}_rep_{repeat}"
                    folder=output/run_id; folder.mkdir()
                    command=[sys.executable,str(ROOT/'scripts/stdc_validation_guards.py'),
                             'lake_worker','--output-dir',str(folder),'--mode',mode,
                             '--epsilon',str(epsilon),'--repeat-index',str(repeat),'--benchmark-run']
                    save(folder/'command.json',dict(command=command,seed=41,threads=1,
                         execution_order=len(rows),watchdog_s=plan['watchdog_s']))
                    with (folder/'stdout.txt').open('w',encoding='utf-8') as stdout, \
                         (folder/'stderr.txt').open('w',encoding='utf-8') as stderr:
                        try:
                            proc=subprocess.run(command,cwd=ROOT,stdout=stdout,stderr=stderr,
                                                timeout=plan['watchdog_s'])
                        except subprocess.TimeoutExpired:
                            save(folder/'watchdog.json',dict(status='budget_exceeded',stop_reason='watchdog',
                                  theory_certified=False,mode=mode,epsilon=epsilon,repeat=repeat,
                                  J=None,incumbent_source=None))
                            raise
                    require(proc.returncode==0,f'worker failure: {run_id}; inspect raw logs')
                    row=read(folder/f'{mode}.json')
                    require(row['epsilon']==epsilon and row['repeat']==repeat and row['mode']==mode,
                            'worker identity mismatch')
                    require(row['legal'] and row['replay_error']<=1e-10, 'route replay failure')
                    require(not row['theory_certified'] or (mode!='paper_greedy' and row['status']=='completed'),
                            'invalid conditional certificate')
                    row.update(run_id=run_id,execution_order=len(rows))
                    rows.append(row)
                    save(output/'results.json',dict(plan=plan,rows=rows))
                    print(f"[{len(rows):02d}/27] {run_id}: {row['status']} {row['stop_reason']}; "
                          f"J={row['J']:.9f}; Pd={row['Pd_T']:.6f}; expanded={row['expanded']}; "
                          f"wall={row['search_wall_s']:.3f}s; certified={row['theory_certified']}",flush=True)
        require(len(rows)==27, 'incomplete paired comparison')
        fields=['run_id','mode','epsilon','repeat','forcing_kind','J','Pd_T','J_minus_PT','expanded',
                'generated','pruned','peak_open','search_wall_s','heuristic_calls','heuristic_wall_s',
                'process_peak_memory_mib','status','stop_reason','incumbent_source','incumbent_origin',
                'theory_certified','root_h','replay_error','legal','particle_sha256','protocol_sha256']
        with (output/'metrics.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
            writer.writeheader(); writer.writerows(rows)
        summary.update(status='passed',runs=len(rows),completed=sum(r['status']=='completed' for r in rows),
                       budget_exceeded=sum(r['status']=='budget_exceeded' for r in rows),
                       certified=sum(r['theory_certified'] for r in rows))
    except Exception as exc:
        summary.update(status='blocked',runs=len(rows),error=str(exc),traceback=traceback.format_exc())
        raise
    finally:
        summary['wall_s']=perf_counter()-started
        save(output/'summary.json',summary)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    args=parser.parse_args()
    main(args.run_dir.resolve())
