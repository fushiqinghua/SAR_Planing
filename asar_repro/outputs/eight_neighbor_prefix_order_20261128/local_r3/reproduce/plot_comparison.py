from hashlib import sha256
from pathlib import Path
from statistics import median
import csv
import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

out=Path(sys.argv[1])
gate=json.loads((out/"gate.json").read_bytes())
with (out/"comparison.csv").open(encoding="utf-8", newline="") as stream:
    rows=list(csv.DictReader(stream))
assert len(rows)==24
cases=[pair["instance"] for pair in gate["pairs"]]
short=["Lake 3101","Lake 3201","Hudson 4101","Hudson 4201"]
methods=["C0","C0_PREFIX"]
colors=["#246A9D","#C45B22"]
fig, axes=plt.subplots(2,2,figsize=(12.1,7.6),layout="constrained")
ax=axes[0,0]
changes=[100*p["relative_J_gain"] for p in gate["pairs"]]
ax.barh(short,changes,color=["#157F69" if g>0 else "#AB4B4B" if g<0 else "#9DADB3" for g in changes])
ax.axvline(0,color="#333333",lw=.8)
ax.axvline(.1,color="#157F69",ls="--",label="0.1% screen",lw=1)
lo,hi=min(min(changes),0),max(max(changes),.1)
width=max(.03, hi-lo)
ax.set_xlim(lo-.23*width,hi+.23*width)
for y,gain in enumerate(changes):
    ax.text(gain+(.015 if gain>=0 else -.015)*width,y,f"{gain:+.3f}%",
            va="center",ha="left" if gain>=0 else "right",fontsize=9)
ax.invert_yaxis()
ax.set_xlabel("Relative reduction in J (%)")
ax.set_title("J change from C0 (median of three)")
ax.legend(frameon=False,loc="lower right")

for j,(case,label) in enumerate(zip(cases[-2:],short[-2:])):
    ax=axes[1,j]
    found=[]
    for method,color in zip(methods,colors):
        items=sorted((r for r in rows if r["instance"]==case and r["method"]==method),
                     key=lambda r:(float(r["J"]),int(r["repetition"])))
        representative=items[1]
        raw=json.loads((out/"runs"/representative["run_id"]/"result.json").read_bytes())
        survival=np.asarray(raw["result"]["physical_replay"]["survival"])
        found.append(survival)
        ax.plot(np.arange(len(survival)),(1-survival)*100,label=method,c=color,lw=1.9,
                ls="-" if method=="C0" else "--")
    same=np.allclose(found[0],found[1],atol=1e-12,rtol=0)
    if same:
        ax.text(.98,.1,"Curves coincide",ha="right",transform=ax.transAxes,fontsize=9)
    ax.set_xlabel("Observation tick")
    ax.set_ylabel("Cumulative detection probability (%)")
    ax.set_title(label)
    ax.legend(frameon=False,loc="upper left")
    ax.grid(axis="y",alpha=.2)

ax=axes[0,1]
xs=np.arange(len(cases))
for j,(method,color) in enumerate(zip(methods,colors)):
    grouped=[[r for r in rows if r["instance"]==case and r["method"]==method] for case in cases]
    early=np.array([median(float(r["early_unique_prefixes"]) for r in g) for g in grouped])
    middle=np.array([median(float(r["mid_unique_prefixes"]) for r in g) for g in grouped])
    ax.bar(xs+(j-.5)*.34,early,width=.31,color=color,label=f"{method} early")
    ax.bar(xs+(j-.5)*.34,middle,bottom=early,width=.31,color=color,alpha=.35,label=f"{method} middle")
ax.set_title("Median expanded prefixes by early/middle band")
ax.set_ylabel("Expanded prefixes")
ax.set_xticks(xs,short,rotation=18,ha="right")
ax.legend(frameon=False,ncol=2,fontsize=8)
fig.suptitle("Fixed 30-second prefix-order screen",fontsize=14)
path=out/"prefix_order_comparison.png"
fig.savefig(path,dpi=160)
plt.close(fig)
print(path,sha256(path.read_bytes()).hexdigest())
