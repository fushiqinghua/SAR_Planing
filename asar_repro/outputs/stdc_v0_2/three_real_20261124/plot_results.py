"""Scientific plots; budgets and Fundy physical qualification remain visible."""
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from stdc_validation_guards import read
from compare_additional_real import load_input
from asar_repro.objective import score_path
from run_trajectory_experiments import VARIANTS

out=Path(__file__).resolve().parent
agg=read(out/'aggregate.json')['rows'];prov=read(out/'provenance.json')
scenes=['lake_ontario','arctic_ocean','bay_of_fundy']
names=['Lake Ontario','Hudsons Bay','Bay of Fundy\nphysical direction UNVERIFIED']
labels=['A^SAR baseline','STDC','Compressed STDC','Particle DP','STDC + DP','Mid plain','Mid diverse','Mid + DP']
for cap in ('work','wall'):
    fig,axes=plt.subplots(3,4,figsize=(18,14),constrained_layout=True)
    for row,(scene,name) in enumerate(zip(scenes,names)):
        group=[next(a for a in agg if (a['scenario'],a['protocol'],a['variant'])==(scene,cap,v)) for v in VARIANTS]
        b=group[0]
        for col in range(4):
            ax=axes[row,col]
            for y,a in enumerate(group):
                failed=any(k.startswith('dp_') for k in a['stops'])
                color='#999999' if failed else '#2365ad' if y==0 else '#218349' if y==1 else '#8a49ae'
                if col==0:
                    value=100*(b['J_median']-a['J_median'])/b['J_median']
                    low=100*(b['J_median']-a['J_max'])/b['J_median'];high=100*(b['J_median']-a['J_min'])/b['J_median']
                elif col==1:
                    value=100*a['Pd_T_median'];low=100*a['Pd_T_min'];high=100*a['Pd_T_max']
                else:
                    key='search_wall_s' if col==2 else 'process_peak_memory_mib'
                    value=a[key+'_median'];low=a[key+'_min'];high=a[key+'_max']
                ax.errorbar(value,y,xerr=[[max(0,value-low)],[max(0,high-value)]],fmt='x' if failed else 'o',color=color,capsize=3)
            ax.set_yticks(range(8),labels if col==0 else ['']*8);ax.invert_yaxis();ax.grid(axis='x',alpha=.2)
            if col==0:
                ax.set_xscale('symlog',linthresh=.01);ax.axvline(0,color='black',lw=.6)
                ax.set_ylabel(name,fontsize=11)
            ax.margins(x=.12)
            ax.set_title(['J reduction vs baseline (%)\npositive = better; symlog scale','Pd (%)','Paid method seconds','Process peak MiB'][col])
    fig.suptitle(f'{cap}: same budget within each frozen real scenario | medians and min-max of 3 repeats\nGray crosses: DP memory abort, common PT only | all-water approximation | all results uncertified',fontsize=13)
    fig.savefig(out/f'three_scenes_{cap}.png',dpi=160,bbox_inches='tight');plt.close(fig)

folder=out.parent/'fundy_repair_20261124'
grid,cfg,meta=load_input(folder,'bay_of_fundy');rows=read(folder/'benchmark/results.json')['rows']
mass=cfg['motion'].cell_mass(cfg['p'],0)[:grid.size].reshape(grid.rows,grid.cols)
selected=[next(r for r in rows if (r['variant'],r['protocol'],r['repeat'])==(v,'work',0)) for v in ('paper_baseline','prior_stdc','mid_diverse','mid_dp')]
points=np.concatenate([np.argwhere(mass>0)]+[np.column_stack((np.asarray(r['path'])//grid.cols,np.asarray(r['path'])%grid.cols)) for r in selected])
r0,c0=np.maximum(points.min(axis=0)-2,0);r1,c1=np.minimum(points.max(axis=0)+2,[grid.rows-1,grid.cols-1])
fig,axes=plt.subplots(2,2,figsize=(12,11),constrained_layout=True)
for ax,r in zip(axes.flat,selected):
    route=np.asarray(r['path']);xy=np.column_stack((route%grid.cols,route//grid.cols))
    ax.imshow(mass,cmap='Blues',vmin=0,vmax=mass.max())
    lc=LineCollection(np.stack((xy[:-1],xy[1:]),axis=1),cmap='plasma',norm=plt.Normalize(1,cfg['budget']),linewidths=1.5)
    lc.set_array(np.arange(1,cfg['budget']+1));ax.add_collection(lc)
    ax.scatter(*xy[0],marker='*',s=90,c='#e98b14',zorder=5);ax.scatter(*xy[-1],marker='x',s=45,c='black',zorder=6)
    ax.set(xlim=(c0-.5,c1+.5),ylim=(r1+.5,r0-.5),xlabel='Grid column',ylabel='Grid row',
           title=f"{r['variant']} | J={r['J']:.9f}; Pd={r['Pd_T']:.6f}\n{r['stop_reason'] or 'completed (uncertified)'}")
fig.colorbar(lc,ax=axes,label='Absolute search step; later visits on top',shrink=.8)
fig.suptitle('Bay of Fundy | physical direction UNVERIFIED | work repeat 0\nHistorical forcing, simulated frozen particles | native angle | star=start, x=end',fontsize=12)
fig.savefig(out/'fundy_paths_qualified.png',dpi=160,bbox_inches='tight');plt.close(fig)
for cap in ('work','wall'):
    fig,ax=plt.subplots(figsize=(11,6),constrained_layout=True)
    for v in VARIANTS:
        r=next(r for r in rows if (r['variant'],r['protocol'],r['repeat'])==(v,cap,0))
        ax.plot(r['survival'],label=v+(' [PT; DP abort]' if r['stop_reason']=='dp_max_memory_bytes' else ''))
    ax.set(xlabel='Absolute step, no sensing at t=0',ylabel='Remaining undetected mass',title=f'Fundy | {cap} repeat 0 | official native angle\nPhysical direction UNVERIFIED; all-water approximation; uncertified')
    ax.legend(fontsize=8);ax.grid(alpha=.2)
    fig.savefig(out/f'fundy_{cap}_survival_qualified.png',dpi=160,bbox_inches='tight');plt.close(fig)
