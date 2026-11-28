"""Plot the verified P1 J/Pd timing evidence."""
from collections import defaultdict
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

out = Path(sys.argv[1])
evidence = json.loads((out/"independent_verification.json").read_bytes())
assert evidence["status"] == "verified" and evidence["run_count"] == 48
rows = evidence["run_rows"]
by = defaultdict(list)
for row in rows:
    by[row["instance"][-4:], row["method"]].append(row)

colors = {"C0_A":"#28456A","C0_B":"#894E78","C0_LAZY":"#167C70","C0":"#28456A"}
markers = {"C0_A":"o","C0_B":"s","C0_LAZY":"D"}
plt.rcParams.update({"font.size":10,"axes.spines.top":False,"axes.spines.right":False})
fig, axes = plt.subplots(2,2,figsize=(12.6,8),layout="constrained")
methods = ("C0_A","C0_B","C0_LAZY")

ax = axes[0,0]
for j,method in enumerate(methods):
    records = by["4101",method]
    x = [r["repetition"]+1+(j-1)*.14 for r in records]
    ax.scatter(x,[r["J"] for r in records],label=method,c=colors[method],
               marker=markers[method],alpha=.9,s=28)
ax.axhline(28.724588352,color="#A04942",linestyle="--",linewidth=1,label="S30")
ax.axhline(28.448979882240007,color="#374957",linestyle=":",linewidth=1,label="J target")
ax.set(xlabel="Paired block",ylabel="Final J",title="Hudson 4101 route quality")
ax.set_xticks(range(1,13))
js = [r["J"] for r in rows if r["instance"].endswith("4101")] + [28.724588352, 28.448979882240007]
ax.set_ylim(min(js)-.08,max(js)+.16)
ax.legend(frameon=False,ncol=3,fontsize=8,loc="best")

ax = axes[0,1]
for j,method in enumerate(methods):
    records=by["4101",method]
    observed=[r["first_search_improvement_s"] for r in records if r["first_search_improvement_s"] is not None]
    nmiss=len(records)-len(observed)
    if observed:
        ax.scatter(np.full(len(observed),j),observed,color=colors[method],marker=markers[method],alpha=.75,s=30)
    ax.text(j,30.35,f"{nmiss}/12 missed",ha="center",va="bottom",fontsize=9)
ax.axhline(30,color="#8D5353",linestyle="--",linewidth=1)
ax.set_xticks(range(3),methods)
yvals=[r["first_search_improvement_s"] for r in rows
       if r["instance"].endswith("4101") and r["first_search_improvement_s"] is not None]
ax.set_ylim((min(yvals)-.8 if yvals else 0),31.2)
ax.set_xlim(-.5,2.5)
ax.set(ylabel="Seconds",title="4101 first strict search improvement")

ax = axes[1,0]
paired=[p for p in evidence["pair_rows"] if p["instance"].endswith("4201")]
px=[p["repetition"]+1 for p in paired]
gains=[100*p["relative_J_gain"] for p in paired]
delta=[p["delta_Pd_pp"] for p in paired]
ax.bar(px,gains,color="#167C70",width=.54,label="Relative J improvement")
ax.plot(px,delta,color="#8B551A",marker="o",markersize=4,linewidth=1.3,label="Pd change")
ax.axhline(0,color="#374957",linewidth=.8)
ax.set(xlabel="Paired block",ylabel="J reduction (%) / Pd change (pp)",title="Hudson 4201 paired differences")
ax.set_xticks(range(1,7))
ax.set_ylim(min(0,min(gains),min(delta))-.015,max(0,max(gains),max(delta))+.11)
ax.legend(frameon=False,fontsize=8,loc="upper left",ncol=2)

ax = axes[1,1]
groups=[
    ("4101 C0",by["4101","C0_A"]+by["4101","C0_B"],colors["C0"]),
    ("4101 Lazy",by["4101","C0_LAZY"],colors["C0_LAZY"]),
    ("4201 C0",by["4201","C0"],colors["C0"]),
    ("4201 Lazy",by["4201","C0_LAZY"],colors["C0_LAZY"]),
]
boxes=ax.boxplot([[r["rss_mib"] for r in rr] for _,rr,_ in groups],
                 patch_artist=True,
                 medianprops={"color":"#171C20","linewidth":1.6})
for box,(_,_,color) in zip(boxes["boxes"],groups):
    box.set(facecolor=color,alpha=.58)
ax.set_xticks(range(1, len(groups)+1), [label for label,_,_ in groups])
ax.set(ylabel="Sampled peak RSS (MiB)",title="Process memory by method")
for ax in axes.flat:
    ax.set_axisbelow(True)
    ax.grid(axis="y",color="#D7DEE3",linewidth=.6)
fig.suptitle("P1 timing robustness on fixed Hudson archives",fontsize=15)
fig.savefig(out/"p1_robustness_comparison.png",dpi=170)
plt.close(fig)
