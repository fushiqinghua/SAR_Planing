"""Report the recorded repair experiment, including unsuccessful outcomes."""
import argparse
from collections import Counter
import csv
from pathlib import Path
from statistics import median

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from run_stdc_repair import VARIANTS, ORDER, REFERENCE, preserve
from stdc_validation_guards import ROOT, read, save, require, load_real


LABELS = {'paper_reference':'Paper reference', 'mass_reference':'Mass reference',
    'stdc_reference':'STDC reference', 'stdc_geometry':'STDC geometry',
    'stdc_cache':'STDC + h cache', 'stdc_reuse':'STDC + exact reuse',
    'paper_reuse':'Paper + exact reuse', 'mass_reuse':'Mass + exact reuse'}
COLORS = dict(zip(VARIANTS, ['#0072B2','#888888','#E69F00','#F0B750',
                            '#CC79A7','#D55E00','#009E73','#565656']))
METRICS = ('J','Pd_T','expanded','generated','pruned','peak_open','search_wall_s',
           'heuristic_calls','heuristic_wall_s','process_peak_memory_mib')


def csv_file(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def aggregate_rows(rows, epsilons):
    aggregate = []
    for eps in epsilons:
        for variant in VARIANTS:
            group = [r for r in rows if r['epsilon']==eps and r['variant']==variant]
            require(len(group)==3 and {r['repeat'] for r in group}=={0,1,2},
                    f'missing or duplicate repeat: {variant}/{eps}')
            record = dict(variant=variant, epsilon=eps, runs=3,
                completed=sum(r['status']=='completed' for r in group),
                budget_exceeded=sum(r['status']=='budget_exceeded' for r in group),
                certified=sum(r['theory_certified'] for r in group),
                stop_reasons=dict(Counter(r['stop_reason'] or 'none' for r in group)),
                incumbent_sources=dict(Counter(r['incumbent_source'] or 'none' for r in group)),
                distinct_paths=len({tuple(r['path']) for r in group}),
                max_generated_depth=max(r['depth_stats']['max_generated_depth'] for r in group),
                complete_candidates_median=median(r['depth_stats']['complete_candidates'] for r in group))
            for field in METRICS:
                values = [r[field] for r in group]
                record[field+'_median'] = median(values)
                record[field+'_min'] = min(values); record[field+'_max'] = max(values)
            for field in ('dominance_pruned','stale_pops','heuristic_cache_hits',
                          'heuristic_cache_misses','state_records_peak',
                          'dominance_key_bytes','heuristic_cache_peak_key_bytes'):
                record[field+'_median'] = median(r['reuse_stats'].get(field,0) for r in group)
            record['geometry_array_bytes_median'] = median(
                sum(c['array_bytes']+c['reach_array_bytes'] for c in r['geometry_cache']) for r in group)
            aggregate.append(record)
    return aggregate


def paired_rows(rows, epsilons):
    pairs = []
    comparisons = [('stdc_geometry','stdc_reference'), ('stdc_cache','stdc_geometry'),
        ('stdc_reuse','stdc_cache'), ('stdc_reuse','stdc_reference'),
        ('stdc_reuse','paper_reference'), ('stdc_reuse','paper_reuse'),
        ('stdc_reuse','mass_reuse')]
    for eps in epsilons:
        for rep in range(3):
            group = {r['variant']:r for r in rows if r['epsilon']==eps and r['repeat']==rep}
            for variant, baseline in comparisons:
                a,b = group[variant],group[baseline]
                pairs.append(dict(variant=variant,baseline=baseline,epsilon=eps,repeat=rep,
                    delta_J=a['J']-b['J'],delta_Pd=a['Pd_T']-b['Pd_T'],
                    time_ratio=a['search_wall_s']/b['search_wall_s'],
                    delta_expanded=a['expanded']-b['expanded'],
                    delta_peak_memory_mib=a['process_peak_memory_mib']-b['process_peak_memory_mib'],
                    J_improved=a['J']<b['J']-1e-10,
                    J_worse=a['J']>b['J']+1e-10,
                    variant_status=a['status'],baseline_status=b['status']))
    return pairs


def figures(output, rows, aggregate):
    selected = [r for r in aggregate if r['epsilon']==1.1]
    fig,axes = plt.subplots(2,2,figsize=(13,9),constrained_layout=True)
    for ax,(metric,title) in zip(axes.flat,[
        ('search_wall_s','Search wall time (s)'),('expanded','Expanded nodes'),
        ('J','Truncated cost J (lower is better)'),('process_peak_memory_mib','Process peak working set (MiB)')]):
        vals = np.array([r[metric+'_median'] for r in selected])
        errs = np.array([[r[metric+'_median']-r[metric+'_min'] for r in selected],
                         [r[metric+'_max']-r[metric+'_median'] for r in selected]])
        y = np.arange(len(selected))
        ax.barh(y,vals,xerr=errs,capsize=2,color=[COLORS[r['variant']] for r in selected])
        ax.set_yticks(y,[LABELS[r['variant']]+(' *' if r['budget_exceeded'] else '') for r in selected])
        ax.invert_yaxis();ax.set_title(title);ax.grid(axis='x',alpha=.2);ax.set_axisbelow(True)
        for yi,value in zip(y,vals):
            ax.annotate(f'{value:.3g}',(value,yi),xytext=(4,0),textcoords='offset points',va='center',fontsize=8)
        ax.margins(x=.18)
    fig.suptitle('Frozen real Lake Ontario, epsilon=1.10, 3 repeats per variant\n'
                 'Median and min-max; * includes a budget stop. Completion is not a paper-greedy certificate.',fontsize=11)
    fig.savefig(output/'repair_performance.png',dpi=170);plt.close(fig)

    protocol,grid,cfg,_,_,_ = load_real()  # SHA gate before reading particle-derived map
    mass = cfg['motion'].cell_mass(cfg['p'],0)[:grid.size].reshape(grid.rows,grid.cols)
    chosen = {r['variant']:r for r in rows if r['epsilon']==1.1 and r['repeat']==0}
    groups = {}
    for name in VARIANTS:
        groups.setdefault(tuple(chosen[name]['path']),[]).append(name)
    fig,axes = plt.subplots(1,2,figsize=(14,6),constrained_layout=True)
    im = axes[0].imshow(mass,cmap='Blues',vmin=0,vmax=mass.max())
    fig.colorbar(im,ax=axes[0],label='Initial searchable mass (special bins retained in scores)',shrink=.7)
    for path,names in groups.items():
        row = chosen[names[0]]; vertices = np.asarray(path)
        color = COLORS[names[0]];label = ' / '.join(LABELS[n] for n in names)
        axes[0].plot(vertices%grid.cols,vertices//grid.cols,'o-',markersize=2,
                     linewidth=1.2,color=color,label=label)
        axes[1].plot(np.arange(len(row['survival'])),row['survival'],color=color,label=label)
    start = protocol['start_vertex']
    axes[0].scatter(start%grid.cols,start//grid.cols,marker='*',s=110,c='gold',edgecolors='black',zorder=5)
    axes[0].set_title('Returned paths; identical paths grouped')
    axes[0].set_xlabel('Grid column');axes[0].set_ylabel('Grid row')
    axes[1].set_title('Remaining undetected mass from independent replay')
    axes[1].set_xlabel('Step t (no detection at t=0)');axes[1].set_ylabel('M(t)')
    axes[1].grid(alpha=.2);axes[1].legend(fontsize=7,loc='best')
    fig.suptitle('Frozen real particles; epsilon=1.10, repeat 0; shared initial PT and unchanged budgets')
    fig.savefig(output/'repair_paths_survival.png',dpi=170);plt.close(fig)


def main(run):
    require(run.is_relative_to(ROOT/'outputs/stdc_v0_2'),'research output required')
    output = run/'report';output.mkdir(exist_ok=False)
    validation = read(run/'validation_summary.json')
    if validation['status']!='passed' or validation['not_run']:
        save(output/'aggregate.json',dict(status='blocked',reason='mandatory validation incomplete or failed'))
        (output/'repair_report.md').write_text('# STDC 修复验证\n\nblocked：强制门槛未全部通过，不生成完成结论。\n',encoding='utf-8')
        return 2
    save(output/'preservation.json',preserve(run))
    pre = read(run/'preflight.json');epsilons = pre['plan']['epsilons']
    require(pre['plan']['repeats']==3 and list(pre['plan']['variants'])==list(VARIANTS),'experiment plan changed')
    data = read(run/'comparison/results.json');rows = data['rows']
    require(data['status']=='passed' and len(rows)==72,'comparison must contain all 72 planned runs')
    for r in rows:
        require(r['forcing_kind']=='historical_real' and r['legal'] and r['replay_error']<=1e-10,'invalid replay/input row')
        require(r['status'] in ('completed','budget_exceeded'),'unknown status')
        require(not r['theory_certified'] or (r['status']=='completed' and r['heuristic_mode']!='paper_greedy'),'invalid certificate')
    aggregate = aggregate_rows(rows,epsilons);pairs = paired_rows(rows,epsilons)
    fields = ['variant','epsilon','repeat','heuristic_mode','forcing_kind',*METRICS,
              'status','stop_reason','incumbent_source','theory_certified','guarantee',
              'replay_J','replay_error','legal','particle_sha256','seed']
    flat = []
    for r in rows:
        record = {field:r[field] for field in fields}
        record.update(r['depth_stats'])
        for key in ('dominance_pruned','stale_pops','heuristic_cache_hits','heuristic_cache_misses',
                    'heuristic_cache_peak_entries','heuristic_cache_peak_key_bytes',
                    'state_records_peak','dominance_key_bytes'):
            record[key] = r['reuse_stats'].get(key,0)
        record['geometry_array_bytes'] = sum(c['array_bytes']+c['reach_array_bytes'] for c in r['geometry_cache'])
        flat.append(record)
    csv_file(output/'metrics.csv',flat);csv_file(output/'aggregate.csv',aggregate)
    csv_file(output/'paired_differences.csv',pairs)
    quality = [r for r in pairs if r['variant']=='stdc_reuse' and r['baseline']=='stdc_reference']
    paper = [r for r in pairs if r['variant']=='stdc_reuse' and r['baseline']=='paper_reference']
    same_engine = [r for r in pairs if r['variant']=='stdc_reuse' and r['baseline']=='paper_reuse']
    wins = sum(r['J_improved'] for r in quality)
    verdict = ('本轮 STDC 修复未改善真实场景返回 J；重复计算问题得到针对性处理，弱下界导致的有限预算路径质量问题仍未解决。'
               if wins==0 else f'本轮 STDC 修复在 {wins}/9 个与旧 STDC 的配对中降低了 J；这是当前冻结场景的有限预算结果，不能推广为跨场景优势。')
    save(output/'aggregate.json',dict(status='passed',aggregate=aggregate,paired=pairs,
        verdict=verdict,source_commit=REFERENCE,planned_runs=72,
        STDC_J_improvements_vs_reference=wins,
        STDC_J_improvements_vs_paper=sum(r['J_improved'] for r in paper),
        STDC_J_improvements_vs_paper_same_reuse=sum(r['J_improved'] for r in same_engine),
        interpretation='one frozen scenario; repeats measure timing variation, not independent scene samples'))
    figures(output,rows,aggregate)
    audit = read(run/'random_audit/random_audit.json')
    small = read(run/'small_search/small_search.json')
    lines = ['# STDC 修复：验证与同预算对照','',verdict,'',
        '## 修复范围与对照','',
        f'- 原实现 reference 从 Git 提交 `{REFERENCE}` 冻结 search.py 与 stdc_heuristic.py 后加载复跑；不将新实现伪装成旧基线。',
        '- 本轮只处理等价几何计算、完整状态启发式缓存、严格状态支配。原 STDC 下界公式未增强，规划目标、forcing、粒子、初始 PT 和预算均未改变。',
        '- 两个新增搜索选项默认关闭。paper_reuse/mass_reuse 也使用相同复用机制，以区分通用工程优化与 STDC 特有收益。','',
        '| variant | 启发式 | 原冻结搜索 | 完整状态支配 | h 缓存条目上限 |',
        '|---|---|---|---|---:|']
    for name,(mode,dominance,cache,legacy) in VARIANTS.items():
        lines.append(f'| {name} | {mode} | {legacy} | {dominance} | {cache} |')
    lines += ['', '## 强制门槛与数据','',
        '| 阶段 | 状态 | 测试数 / 说明 |','|---|---|---|']
    for stage in ORDER:
        rec = validation['stages'][stage];counts = rec.get('test_counts')
        detail = str(counts) if counts else '见阶段命令、stdout/stderr、JSON 与源码指纹'
        lines.append(f"| {stage} | {rec['status']} | {detail} |")
    lines += ['',
        f"- 合成小图：160 个场景、{audit['prefix_evaluations']} 个前缀，超出 1e-10 的可采纳性违规数为 {audit['violations']}；最大正差 {audit['positive_overestimation']:.3g}。",
        f"- 35 组小图：历史搜索 {small['historical_searches']} 次，修复选项搜索 {small['repair_searches']} 次；共 {small['independent_replays']} 条路径独立评分与 Oracle 检查。",
        '- 真实 Lake Ontario：粒子及原始风流指纹门禁通过；17×17、500 粒子、T=49、q=.78、seed=41，t=0 不探测。未重新运行 Leeway。',
        '- 8 variants × 3 ε × 3 次独立进程 = 72 次；统一 PT 初始解及 5000 expansions / 20000 OPEN / 30 s，方法次序按重复轮转。',
        '- geometry/cache 与原 STDC 的路径、J、状态、节点计数须完全一致，驱动器已强制检查。支配会改变被扩展的完整状态集合，按 Oracle 和独立回放验证。',
        '- depth_stats 为 trace 观测最深生成/完整候选，含 dominance_prune；最后预算边界的节点可能在回调前退出，不能将这些观测计数当成所有内部节点的绝对精确总数。','',
        '## 完整 ε 对照：三次重复的中位数','',
        '| ε | variant | J↓ | Pd↑ | 扩展 | 秒〔min–max〕 | 峰值 MiB | completed/budget | incumbent 来源 | 条件认证 |',
        '|---|---|---:|---:|---:|---:|---:|---|---|---|']
    for r in aggregate:
        sources = ', '.join(f'{k}:{v}' for k,v in r['incumbent_sources'].items())
        lines.append(f"| {r['epsilon']:.2f} | {r['variant']} | {r['J_median']:.9f} | {r['Pd_T_median']:.6f} | "
            f"{r['expanded_median']:.0f} | {r['search_wall_s_median']:.4f}〔{r['search_wall_s_min']:.4f}–{r['search_wall_s_max']:.4f}〕 | "
            f"{r['process_peak_memory_mib_median']:.2f} | {r['completed']}/{r['budget_exceeded']} | {sources} | {r['certified']}/3 |")
    lines += ['', 'budget_exceeded 均为 uncertified；具体 max_expansions/max_open/max_seconds 逐行保留于 metrics.csv。paper_greedy 的 completed 也不具有动态 ε 认证。',
        '', '## 配对差异与归因','',
        '| ε | variant / 对照 | ΔJ | 时间倍数 | Δ峰值 MiB | J 改善次数 |','|---|---|---:|---:|---:|---|']
    for eps in epsilons:
        identities = list(dict.fromkeys((r['variant'],r['baseline']) for r in pairs))
        for variant,baseline in identities:
            group = [r for r in pairs if r['epsilon']==eps and r['variant']==variant and r['baseline']==baseline]
            lines.append(f"| {eps:.2f} | {variant} / {baseline} | {median(r['delta_J'] for r in group):+.9f} | "
                f"{median(r['time_ratio'] for r in group):.3f}× | {median(r['delta_peak_memory_mib'] for r in group):+.2f} | "
                f"{sum(r['J_improved'] for r in group)}/3 |")
    lines += ['',
        '- geometry / reference 衡量保持数值与搜索顺序的几何加速；cache / geometry 衡量完整 belief 的 h 复用；reuse / cache 衡量严格支配的新增影响。',
        '- 只有对 paper_reference 的 J/Pd/时间差能回答相对原 baseline A^SAR 的本场景表现；对 paper_reuse 的差异进一步控制通用搜索优化。改善旧 STDC 的耗时不等于超过 paper baseline。',
        '- 本轮没有新增更紧的下界。若完整候选仍为零或 J 仍等于初始 PT，不将计算加速解释成路径质量瓶颈已修复。','',
        '## 正确性前提与内存代价','',
        '- 支配键包括 depth、vertex、belief dtype/shape/完整字节；运动、传感器和时域在单次搜索内固定。相同完整状态的任意合法后缀具有相同未来 belief 和新增代价，因此仅保留较小 g 不损失更优完成路径。更小 g 重新入队，较大 g 的旧堆项过期跳过。',
        '- 未按 (depth,vertex) 合并、未用哈希碰撞身份或浮点容差近似合并；路径历史必须仅通过当前完整 belief、位置、深度影响未来。若以后加入转向、燃油或历史约束，必须扩展状态键。',
        '- h 的 LRU 上限为 4096 条；几何缓存额外浮点数组上限为 16 MiB，可达整数数组另计。完整状态支配表保留遇到的状态，并不由 OPEN 条目数直接限制，可能增加内存。',
        '- metrics 的字节计数只覆盖相应键载荷/数组；可能共享引用，不宜直接相加当作进程增量。峰值 MiB 为独立工作进程 peak working set，包含输入校验、预处理和回放，不是纯搜索堆。',
        '- 预算中止无 ε 认证。可采纳模式仅在离散模型前提成立且搜索完成时具有条件性 ε 界；本地有限测试不是全输入形式化浮点证明。',
        '- 真实历史环境归档沿用 allwater 假设与本地 PT，不声称复现原作者私有 forcing 或手工 PT。三次重复不是三个独立场景。','',
        '## 文件与复跑','',
        '- metrics.csv：72 条运行；aggregate.json/CSV：24 组汇总及配对解释；paired_differences.csv：逐重复差值。',
        '- repair_performance.png：ε=1.10 的耗时、扩展、J、内存；repair_paths_survival.png：独立回放的路径和剩余质量。',
        '- 各阶段目录保留命令、seed、stderr、JUnit、JSON 和 git diff；comparison 每个子目录保留完整路径和来源。',
        '- 初始化新目录后，按 new_tests → full_tests → random_audit → small_search → lake_smoke → comparison 顺序运行 scripts/run_stdc_repair.py。',
        '- 报告命令：`python scripts/report_stdc_repair.py --run-dir <本轮目录>`；拒绝覆盖已有 report 目录。',
        '- 本轮没有实施新下界或第二个创新点；没有修改 baseline-v1.1、B7 原始结果和评价器。','']
    (output/'repair_report.md').write_text('\n'.join(lines),encoding='utf-8')
    print(verdict)
    print(output)
    return 0


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    args = parser.parse_args()
    raise SystemExit(main(args.run_dir.resolve()))
