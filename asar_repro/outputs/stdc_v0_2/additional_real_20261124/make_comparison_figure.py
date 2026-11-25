"""Scientific figure from saved real paths; no simulation or optimization."""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from stdc_validation_guards import read, save
from run_anytime_experiments import csv_save
from compare_additional_real import frozen
from asar_repro.objective import score_path

run=Path(__file__).resolve().parent
grid,cfg,meta,record,_=frozen(run,'arctic_ocean')
rows=read(run/'benchmark/results.json')['rows']
chosen=[next(r for r in rows if r['variant']==m and r['protocol']=='work' and r['repeat']==0) for m in ('paper_baseline','prior_stdc')]
routes=[('ParallelTrack',record['initial_path'])]+[(r['variant'],r['path']) for r in chosen]
mass=cfg['motion'].cell_mass(cfg['p'],0)[:grid.size].reshape(grid.rows,grid.cols)
active=np.argwhere(mass>0)
points=np.concatenate([active]+[np.column_stack((np.asarray(p)//grid.cols,np.asarray(p)%grid.cols)) for _,p in routes])
r0,c0=np.maximum(points.min(axis=0)-2,0);r1,c1=np.minimum(points.max(axis=0)+2,[grid.rows-1,grid.cols-1])
fig,axs=plt.subplots(1,3,figsize=(15,5),constrained_layout=True)
for ax,(name,path) in zip(axs,routes):
    score=score_path(grid,path,**cfg);route=np.asarray(path)
    ax.imshow(mass,origin='upper',cmap='Blues',vmin=0,vmax=mass.max())
    xy=np.column_stack((route%grid.cols,route//grid.cols))
    segments=np.stack((xy[:-1],xy[1:]),axis=1)
    lc=LineCollection(segments,cmap='plasma',norm=plt.Normalize(1,cfg['budget']),linewidths=1.8)
    lc.set_array(np.arange(1,cfg['budget']+1));ax.add_collection(lc)
    ax.scatter(route[0]%grid.cols,route[0]//grid.cols,marker='*',s=100,c='#e98b14',zorder=5)
    ax.scatter(route[-1]%grid.cols,route[-1]//grid.cols,marker='x',s=50,c='black',zorder=6)
    state='constructed reference' if name=='ParallelTrack' else 'completed; uncertified' if name=='paper_baseline' else 'budget stop: 5000 expansions'
    ax.set(xlim=(c0-.5,c1+.5),ylim=(r1+.5,r0-.5),xlabel='Grid column',ylabel='Grid row',
           title=f'{name}\nJ={score.J:.9f}   Pd={score.pd_final:.9f}\n{state}')
    ax.grid(alpha=.15)
fig.colorbar(lc,ax=axs,label='Search step (later visits drawn on top)',shrink=.75)
fig.suptitle('Hudsons Bay | historical forcing, simulated frozen particles | work cap, repeat 0\nBackground: prior mass at CST; star=start, x=end | all-water approximation | uncertified',fontsize=11)
fig.savefig(run/'hudson_core_comparison.png',dpi=180,bbox_inches='tight',pad_inches=.15)
plt.close(fig)
base,new=[score_path(grid,r['path'],**cfg) for r in chosen]
steps=[dict(t=t,baseline_vertex=chosen[0]['path'][t],stdc_vertex=chosen[1]['path'][t],
            baseline_survival=float(base.survival[t]),stdc_survival=float(new.survival[t]),
            cumulative_J_improvement=float(base.g[t]-new.g[t])) for t in range(cfg['budget']+1)]
csv_save(run/'hudson_stepwise_comparison.csv',steps)
save(run/'hudson_core_comparison.json',dict(
    scenario='arctic_ocean',protocol='work',repeat=0,particle_sha256=meta['particle_sha256'],
    baseline_J=base.J,stdc_J=new.J,delta_J=new.J-base.J,
    J_reduction_percent=100*(base.J-new.J)/base.J,
    baseline_Pd=base.pd_final,stdc_Pd=new.pd_final,
    Pd_increase_percentage_points=100*(new.pd_final-base.pd_final),
    differing_path_steps=[s['t'] for s in steps if s['baseline_vertex']!=s['stdc_vertex']],
    compared_on_identical_inputs=True,theory_certified=False))
aggregate=read(run/'benchmark/aggregate.json')['rows']
group=[a for a in aggregate if a['protocol']=='work']
labels=[a['variant']+(' [DP memory stop; PT only]' if a['variant'] in ('dp_only','stdc_dp','mid_dp') else ' [completed]' if a['variant']=='paper_baseline' else ' [budget stop]') for a in group]
fig,axes=plt.subplots(1,3,figsize=(17,6),constrained_layout=True)
for ax,key,title in zip(axes,('J','search_wall_s','process_peak_memory_mib'),('J (lower is better)','Paid method seconds','Process peak MiB')):
    bars=ax.barh(labels,[a[key+'_median'] for a in group]);ax.invert_yaxis();ax.set_title(title);ax.tick_params(axis='y',labelsize=8)
    for bar,a in zip(bars,group):
        if a['variant'] in ('dp_only','stdc_dp','mid_dp'):bar.set_color('#999999');bar.set_hatch('//')
fig.suptitle('Hudsons Bay | work cap | median of 3 repeats | all methods uncertified\nDP requires 992.89 MiB managed buffers > 128 MiB cap: no DP search ran; gray bars retain common PT',fontsize=11)
fig.savefig(run/'hudson_efficiency_annotated.png',dpi=160,bbox_inches='tight',pad_inches=.15);plt.close(fig)
