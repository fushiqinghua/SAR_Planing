"""Postprocess saved results only; no search, drift or evaluator changes."""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'additional_figures'
OUT.mkdir(exist_ok=False)
data = json.loads((ROOT / 'benchmark/results.json').read_bytes())
assert data['status'] == 'passed'
rows = data['rows']
shape = json.loads((ROOT / 'benchmark/input_gate.json').read_bytes())['mission']['grid_rows_cols']
assert shape == [17,17]
assert len(rows) == 45 and all(r['legal'] and not r['theory_certified'] for r in rows)
eps = (1.0, 1.04, 1.1)
methods = ('paper_baseline', 'window_stdc_endpoint_lb')
labels = ('Paper baseline', 'Endpoint STDC windows')
colors = ('#0072B2', '#CC79A7')
fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), constrained_layout=True)
for mode, label, color in zip(methods, labels, colors):
    chosen = [next(r for r in rows if r['variant']==mode and r['epsilon']==e and r['repeat']==0) for e in eps]
    for ax, field, scale in ((axes[0], 'J', 1), (axes[1], 'Pd_T', 100)):
        values = [r[field]*scale for r in chosen]
        ax.plot(range(3), values, 'o-', color=color, label=label, lw=2)
        for x, y in enumerate(values):
            ax.annotate(f'{y:.4f}', (x,y), xytext=(0,10 if mode==methods[0] else -16),
                        textcoords='offset points', ha='center', color=color, fontsize=9)
for ax in axes:
    ax.set_xticks(range(3), ['1.00', '1.04', '1.10'])
    ax.set_xlabel('epsilon for seed / baseline (not a guarantee)')
    ax.margins(y=.22); ax.grid(alpha=.25); ax.legend(fontsize=9)
axes[0].set_ylabel('J (lower is better)')
axes[1].set_ylabel('Final detection probability (%)')
fig.suptitle('Frozen real Lake Ontario input; equal total caps; all routes uncertified\n'
             'Baseline eps=1 stopped at 5000 expansions; windows completed only their local search', fontsize=11)
fig.savefig(OUT/'core_metrics_all_epsilons.png', dpi=180); plt.close(fig)

selected = [r for r in rows if r['epsilon']==1.0 and r['repeat']==0]
fig, ax = plt.subplots(figsize=(10,5), constrained_layout=True)
for r in selected:
    ax.plot(range(len(r['survival'])), r['survival'], label=f"{r['variant']} (J={r['J']:.4f})")
ax.set(xlabel='Absolute step t (no observation at t=0)', ylabel='Remaining undetected mass M(t)',
       title='epsilon=1: independent full replay, same real particles, all routes uncertified')
ax.legend(fontsize=8); ax.grid(alpha=.25)
fig.savefig(OUT/'survival_eps1.png', dpi=180); plt.close(fig)

fig, axes = plt.subplots(1,2,figsize=(10,5),constrained_layout=True)
for ax,mode,label,color in zip(axes,methods,labels,colors):
    r=next(r for r in selected if r['variant']==mode)
    route=np.asarray(r['path']); cols=shape[1]
    ax.plot(route%cols,route//cols,'o-',ms=3,color=color)
    ax.scatter(route[0]%cols,route[0]//cols,s=100,marker='*',c='gold',edgecolors='black',zorder=4)
    ax.set_xlim(-.5,16.5); ax.set_ylim(16.5,-.5); ax.set_aspect('equal'); ax.grid(alpha=.2)
    ax.set(xlabel='Grid column',ylabel='Grid row',title=f"{label}\nJ={r['J']:.6f}, Pd={r['Pd_T']:.6f}\n{r['status']}")
fig.suptitle('epsilon=1; fixed 17x17 grid; route plot only, not a geographic map',fontsize=11)
fig.savefig(OUT/'paths_eps1.png',dpi=180); plt.close(fig)
print('Saved three additional figures from the archived results; no experiments rerun.')
