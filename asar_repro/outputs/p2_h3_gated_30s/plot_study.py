"""Plot the three guard cases from the budget-valid formal records."""
from statistics import median

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from h3_protocol import read
from run_study import ARMS, DEFAULT_OUT, ident, lock, verify_record


def main():
    out=DEFAULT_OUT
    protocol=lock(out)
    colors={"C0":"#265d86","Lazy":"#9a4d36","Gated":"#187c62"}
    markers={"C0":"o","Lazy":"x","Gated":"D"}
    rows={}
    for task in protocol["tasks"]:
        folder=out/"runs"/ident(task)
        record=verify_record(folder,task)
        if record["status"]!="valid":
            continue
        score=read(folder/"result.json")["replay"]
        rows.setdefault((task["seed"],task["arm"]),[]).append(
            (score["J"],100*score["pd_final"],record["process_peak_rss_bytes"]/2**20))

    fig, axes=plt.subplots(1,3,figsize=(12.6,4.2),constrained_layout=True)
    a=protocol["acceptance"]
    for seed,ax in ((4601,axes[0]),(3401,axes[2])):
        for arm in ARMS:
            points=rows.get((seed,arm),[])
            ax.scatter([p[0] for p in points],[p[1] for p in points],s=40,
                       marker=markers[arm],color=colors[arm],alpha=.83)
        ax.set(xlabel="J (lower is better)",ylabel="Terminal Pd (%)")
        ax.grid(alpha=.18)
    axes[0].set_title("4601 · Route quality")
    axes[0].scatter(55.191382368,22.7242704,marker="*",s=120,edgecolor="#202020",facecolor="none",
                    label="120 s capacity witness",zorder=4)
    axes[0].axvline(a["J_4601_max"],ls=":",color="#76818a")
    axes[0].axhline(100*a["Pd_4601_min"],ls=":",color="#76818a")
    axes[0].legend(frameon=False,fontsize=8,loc="lower left")
    axes[2].set_title("3401 · Route quality")
    axes[2].axvline(a["J_3401_max"],ls=":",color="#76818a")
    axes[2].legend(handles=[Line2D([],[],color=colors[arm],marker=markers[arm],ls="",label=arm)
                            for arm in ARMS],frameon=False,fontsize=8,loc="upper left")
    ax=axes[1]
    for i,arm in enumerate(ARMS):
        rss=[p[2] for p in rows.get((4501,arm),[])]
        if rss:
            ax.bar(i,median(rss),width=.55,color=colors[arm],alpha=.85)
            ax.scatter([i+(j-(len(rss)-1)/2)*.07 for j in range(len(rss))],rss,color="#222222",s=10)
    ax.set_title("4501 · Working-set memory")
    ax.set_xticks(range(len(ARMS)),ARMS)
    ax.set_ylabel("Peak RSS (MiB)")
    ax.grid(axis="y",alpha=.18)
    fig.savefig(out/"analysis"/"guard_cases.png",dpi=155)
    plt.close(fig)


if __name__=="__main__":
    main()
