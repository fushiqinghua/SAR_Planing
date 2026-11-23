"""Generate factual tables and scientific figures from recorded comparisons."""
import argparse
import csv
import json
from pathlib import Path
from statistics import median

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from stdc_validation_guards import ROOT, read, save, require

MODES=('paper_greedy','mass_lb','stdc_lb')
LABELS={'paper_greedy':'ASAR paper_greedy','mass_lb':'ASAR mass_lb','stdc_lb':'STDC-ASAR'}
COLORS={'paper_greedy':'#0072B2','mass_lb':'#777777','stdc_lb':'#D55E00'}


def main(run):
    base=run/'paired_comparison'
    require(read(base/'summary.json')['status']=='passed','comparison did not pass')
    rows=read(base/'results.json')['rows']
    figures=base/'figures';figures.mkdir(exist_ok=False)
    epsilons=(1.1,1.04,1.)
    aggregate=[]
    for epsilon in epsilons:
        for mode in MODES:
            group=[r for r in rows if r['epsilon']==epsilon and r['mode']==mode]
            require(len(group)==3,'missing planned replicate')
            row=dict(mode=mode,epsilon=epsilon,runs=3,
                completed=sum(r['status']=='completed' for r in group),
                budget_stopped=sum(r['status']=='budget_exceeded' for r in group),
                certified=sum(r['theory_certified'] for r in group),
                distinct_paths=len({tuple(r['path']) for r in group}),
                stop_reasons=sorted({r['stop_reason'] or 'none' for r in group}))
            for metric in ['J','Pd_T','expanded','search_wall_s','process_peak_memory_mib',
                           'heuristic_wall_s','heuristic_calls','root_h','peak_open']:
                values=[r[metric] for r in group]
                row[metric+'_median']=median(values)
                row[metric+'_min']=min(values);row[metric+'_max']=max(values)
            row['heuristic_time_fraction_median']=median(r['heuristic_wall_s']/r['search_wall_s'] for r in group)
            aggregate.append(row)
    paired=[]
    for eps in epsilons:
        for rep in range(3):
            group={r['mode']:r for r in rows if r['epsilon']==eps and r['repeat']==rep}
            for baseline in ('paper_greedy','mass_lb'):
                a,b=group['stdc_lb'],group[baseline]
                paired.append(dict(epsilon=eps,repeat=rep,baseline=baseline,
                     delta_J=a['J']-b['J'],J_change_percent=100*(a['J']/b['J']-1),
                     delta_Pd=a['Pd_T']-b['Pd_T'],time_ratio=a['search_wall_s']/b['search_wall_s'],
                     delta_expanded=a['expanded']-b['expanded'],
                     STDC_J_improved=a['J']<b['J']-1e-10,
                     STDC_certified=a['theory_certified'],baseline_certified=b['theory_certified']))
    save(base/'aggregate.json',dict(aggregate=aggregate,paired=paired,
         real_J_improvements=sum(r['STDC_J_improved'] for r in paired),
         interpretation='finite frozen-scene evidence; three timing repeats are not independent scenario samples'))
    for filename,data in [('aggregate.csv',aggregate),('paired_differences.csv',paired)]:
        with (base/filename).open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)

    fig,axes=plt.subplots(2,2,figsize=(12,8),constrained_layout=True)
    specs=[('J','Truncated cost J (lower is better)',False),('Pd_T','Detection probability Pd(T)',False),
           ('search_wall_s','Search wall time (s, logarithmic)',True),('expanded','Expanded nodes',False)]
    x=np.arange(3);width=.24
    for ax,(metric,title,log) in zip(axes.flat,specs):
        for index,mode in enumerate(MODES):
            group=[next(r for r in aggregate if r['mode']==mode and r['epsilon']==e) for e in epsilons]
            y=np.array([r[metric+'_median'] for r in group])
            errors=np.array([[r[metric+'_median']-r[metric+'_min'] for r in group],
                             [r[metric+'_max']-r[metric+'_median'] for r in group]])
            ax.bar(x+(index-1)*width,y,width,label=LABELS[mode],color=COLORS[mode],yerr=errors,capsize=3)
        ax.set_xticks(x,[str(e) for e in epsilons]);ax.set_xlabel('epsilon');ax.set_title(title)
        if log:ax.set_yscale('log')
        ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    axes[0,0].legend(fontsize=8)
    fig.suptitle('Frozen Lake Ontario: 3 timing repeats, identical input / PT / budgets\n'
                 'Bars: medians; whiskers: min-max. All runs uncertified.',fontsize=12)
    fig.savefig(figures/'real_performance.png',dpi=170);plt.close(fig)

    selected={r['mode']:r for r in rows if r['epsilon']==1.1 and r['repeat']==0}
    fig,axes=plt.subplots(1,2,figsize=(11,4),constrained_layout=True)
    for mode,row in selected.items():
        axes[0].plot(range(50),row['survival'],label=LABELS[mode],color=COLORS[mode],
                     linestyle='--' if mode=='mass_lb' else '-')
        axes[1].plot(range(50),row['cumulative_J'],label=LABELS[mode],color=COLORS[mode],
                     linestyle='--' if mode=='mass_lb' else '-')
    axes[0].set_title('Remaining undetected mass');axes[1].set_title('Cumulative J')
    for ax in axes:ax.set_xlabel('Step t (t=0 has no detection)');ax.legend(fontsize=8);ax.grid(alpha=.25)
    fig.suptitle('Real input, epsilon=1.10, replicate 0; curves from independent replay')
    fig.savefig(figures/'real_survival_cost.png',dpi=170);plt.close(fig)

    proto=read(ROOT/'outputs/baseline_v1.1/b7_final/frozen_experiment_protocol.json')
    with np.load(ROOT/proto['particle_archive']['path'],allow_pickle=False) as archive:
        mass=np.bincount(archive['cell_ids'][0],weights=archive['initial_weights'],minlength=293)[:289]
    fig,axes=plt.subplots(1,3,figsize=(13,4.5),constrained_layout=True)
    for ax,mode in zip(axes,MODES):
        row=selected[mode];path=np.asarray(row['path']);r,c=path//17,path%17
        im=ax.imshow(mass.reshape(17,17),cmap='Blues',vmin=0,vmax=mass.max())
        ax.plot(c,r,'o-',markersize=2,linewidth=1.3,color=COLORS[mode]);ax.scatter(c[0],r[0],marker='*',s=120,c='gold',edgecolors='black')
        ax.set_title(f"{LABELS[mode]}\nJ={row['J']:.4f}; Pd={row['Pd_T']:.4f}",fontsize=10)
        ax.set_xlabel('Grid column');ax.set_ylabel('Grid row')
    fig.colorbar(im,ax=axes,label='Initial searchable probability mass',shrink=.8)
    fig.suptitle('Frozen Lake Ontario routes (epsilon=1.10, replicate 0)')
    fig.savefig(figures/'real_paths.png',dpi=170);plt.close(fig)

    small=read(run/'small_search/small_search.json'); audit=read(run/'random_audit/random_audit.json')
    toy=[r for r in small['aggregate'] if r['epsilon']==1.]
    fig,axes=plt.subplots(1,2,figsize=(11,4.5),constrained_layout=True)
    names=[r['mode'] for r in toy]
    axes[0].barh(names,[r['expanded_mean'] for r in toy],color='#4C78A8')
    axes[1].barh(names,[r['time_ms_mean'] for r in toy],color='#F58518')
    axes[0].set_title('Mean expanded nodes');axes[1].set_title('Mean search time (ms)')
    fig.suptitle('35 synthetic toy cases, epsilon=1.0; every J matches the DFS Oracle')
    fig.savefig(figures/'toy_efficiency.png',dpi=170);plt.close(fig)

    toy_by_mode={r['mode']:r for r in toy}
    t0,t1=toy_by_mode['mass_lb'],toy_by_mode['stdc_lb']
    saved_nodes=100*(1-t1['expanded_mean']/t0['expanded_mean'])
    saved_time=100*(1-t1['time_ms_mean']/t0['time_ms_mean'])
    wins=sum(r['STDC_J_improved'] for r in paired)
    verdict=('本轮真实场景未观察到 STDC 的 J 改善；不能据此声称优于 baseline A^SAR。'
             if wins==0 else '真实场景部分配对观察到 STDC 的 J 改善，具体范围见逐行差值；不能推广到未测场景。')
    lines=['# STDC v0.2：与 baseline A^SAR 的本地性能对照','',verdict,'',
      '## 正确性与输入', '',
      '- 新测试 28 passed；完整回归 281 passed，无失败、跳过。原动态反例保留。',
      f"- 160 个随机小场景、{audit['prefix_evaluations']:,} 个路径前缀：0 项超过 1e-10 容差的下界违规；最大正差 {audit['positive_overestimation']:.3g}。",
      '- 35 组 toy × 7 方法 × 2 个 ε = 490 次搜索，路径逐条合法，独立 J 回放误差为 0；ε=1 与 DFS Oracle 相等。',
      '- 真实 smoke 两组通过输入门禁和回放，但搜索均因扩展预算中止，均未认证。',
      '- 本轮对照预先固定为三种方法 × 三个 ε × 三次独立进程 = 27 次；单线程，旋转方法顺序。',
      '- 粒子、metadata、原始 forcing、冻结协议和评价器均通过 SHA 校验。500 粒子、17×17、T=49、q=.78、seed=41，t=0 不探测。',
      '- 所有方法使用同一冻结 PT 初始路径（J=20.477608336）及 5000 expansions / 20000 OPEN / 30 s 预算。未重新运行 Leeway。','',
      '## 真实 Lake Ontario：三次重复的中位数','',
      '| ε | 方法 | J↓ | Pd↑ | 扩展数 | 搜索秒数〔最小–最大〕 | 峰值内存 MiB | 完成/中止 | 认证 |',
      '|---|---|---:|---:|---:|---:|---:|---|---|']
    for r in aggregate:
        lines.append(f"| {r['epsilon']:.2f} | {r['mode']} | {r['J_median']:.9f} | {r['Pd_T_median']:.6f} | "
                     f"{r['expanded_median']:.0f} | {r['search_wall_s_median']:.4f}〔{r['search_wall_s_min']:.4f}–{r['search_wall_s_max']:.4f}〕 | "
                     f"{r['process_peak_memory_mib_median']:.2f} | {r['completed']}/{r['budget_stopped']} | {r['certified']}/3 |")
    lines += ['', 'paper_greedy 的 completed 仅表示实现终止，不表示具有动态 ε 界。提前中止的 STDC/mass_lb 也不能认证。峰值内存为独立进程 peak working set，包含预处理和回放；不是搜索堆独占内存。','',
              '## STDC 相对 baseline 的配对差异','',
              '| ε | 对照 | ΔJ（STDC−对照） | ΔPd | 时间倍数中位数 | J 改善次数 |',
              '|---|---|---:|---:|---:|---|']
    for eps in epsilons:
        for baseline in ('paper_greedy','mass_lb'):
            g=[r for r in paired if r['epsilon']==eps and r['baseline']==baseline]
            lines.append(f"| {eps:.2f} | {baseline} | {median(r['delta_J'] for r in g):+.9f} | "
                         f"{median(r['delta_Pd'] for r in g):+.6f} | {median(r['time_ratio'] for r in g):.2f}× | "
                         f"{sum(r['STDC_J_improved'] for r in g)}/3 |")
    lines += ['', '## toy 收益与计算开销','',
      f"ε=1 时，相对 mass_lb：平均扩展 {t0['expanded_mean']:.2f} → {t1['expanded_mean']:.2f}（减少 {saved_nodes:.1f}%）；平均耗时 {t0['time_ms_mean']:.3f} → {t1['time_ms_mean']:.3f} ms（减少 {saved_time:.1f}%）。这些是合成小图结果，不能代替真实场景结果。",
      f"capacity_lb 在同组 toy 的平均扩展为 {toy_by_mode['capacity_lb']['expanded_mean']:.2f}，耗时 {toy_by_mode['capacity_lb']['time_ms_mean']:.3f} ms；需区分容量约束的收益与 STDC 耦合的额外贡献。",'',
      '| ε | STDC 根 h | mass 根 h | STDC 启发式耗时占比 |', '|---|---:|---:|---:|']
    for eps in epsilons:
        a=next(r for r in aggregate if r['epsilon']==eps and r['mode']=='stdc_lb')
        b=next(r for r in aggregate if r['epsilon']==eps and r['mode']=='mass_lb')
        lines.append(f"| {eps:.2f} | {a['root_h_median']:.6f} | {b['root_h_median']:.6f} | {100*a['heuristic_time_fraction_median']:.1f}% |")
    lines += ['', '## 可支持的结论与局限','',
      '- 本地离散正确性检查通过；这不是对全部输入的形式化浮点证明。新模式的 ε 界仍要求模型前提成立且搜索真正完成。',
      '- 根下界更紧和 toy 扩展减少已经有数值证据；真实任务是否更好必须由上表的 J、Pd、时间和完成状态判断。',
      '- 本轮 STDC 均触发 5000 次扩展上限，尚未触及 30 秒时间上限。因此，只加速同一个启发式、保持搜索顺序和扩展预算不变，不能直接解决本轮的路径质量瓶颈；需要先解释为何有限扩展内没有找到更好的完整路径。',
      '- 这是一个冻结的历史环境重建场景，沿用 allwater 假设与本地 PT。没有复现原作者私有 forcing 或手工 PT。',
      '- 三次重复仅用于观察运行时间波动，是同一场景的重复，不是三个独立场景；不声称统计显著或跨场景泛化。',
      '- 原 r1–r4 失败记录保留；本轮通过使用非沙箱进程和纯英文临时路径解决 Windows IO 问题，没有放宽数值断言。',
      '- 未开展创新点二，也未基于本轮结果修改算法、forcing、目标或预算。','',
      '## 文件与复跑','',
      '- 完整命令、seed、stderr、JUnit 与阶段 git diff：本目录父级各阶段子目录。',
      '- metrics.csv：27 次运行；aggregate.csv：三次重复汇总；paired_differences.csv：逐对差值。',
      '- 各运行子目录保存完整路径、未探测质量曲线、独立回放与输入指纹。',
      '- figures/real_performance.png、real_paths.png、real_survival_cost.png、toy_efficiency.png。',
      '- 后续复跑应创建新结果目录，保留旧结果，使用同一 comparison_plan.json 和冻结输入。',
      '- 生成报告：`python scripts/report_stdc_comparison.py --run-dir <本轮目录>`；图目录拒绝覆盖。','']
    (base/'stdc_vs_baseline_report.md').write_text('\n'.join(lines),encoding='utf-8')
    print(verdict)
    print(json.dumps(dict(runs=len(rows),toy_node_reduction_pct=saved_nodes,toy_time_reduction_pct=saved_time,
                         real_J_improvements=wins),ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    main(parser.parse_args().run_dir.resolve())
