"""Summarize diagnostic traces; no planner modifications or additional searches."""
import argparse
import csv
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from stdc_validation_guards import ROOT,read,require,save


def main(folder):
    require(read(folder/'diagnosis.json')['status']=='passed','diagnostic search did not pass')
    modes=['mass_lb','stdc_lb','paper_greedy']
    traces={m:[json.loads(s) for s in (folder/f'{m}.trace.jsonl').read_text().splitlines()] for m in modes}
    summaries={m:read(folder/f'{m}.json') for m in modes}
    root=read(folder/'root_decomposition.json'); evidence=read(folder/'mechanism_evidence.json')
    profile=read(folder/'heuristic_profile.json')
    profile_total=max(r['cumulative_s'] for r in profile['rows'])
    profile_reach=next(r['cumulative_s'] for r in profile['rows'] if r['function']=='reachable')
    profile_copy=sum(r['self_s'] for r in profile['rows'] if "'copy' of 'numpy.ndarray'" in r['function'])
    old=read(ROOT/'outputs/stdc_v0_2/local_validation_20261123_r5/paired_comparison/aggregate.json')
    baseline={r['mode']:r for r in old['aggregate'] if r['epsilon']==1.1}
    with (folder/'search_diagnosis.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        keys=['mode','expanded','generated','pruned','max_expanded_depth','max_generated_depth',
              'generated_complete_candidates','duplicate_pops','unique_popped_states','h_calls',
              'h_microseconds_per_call','search_seconds','root_h']
        writer=csv.DictWriter(stream,fieldnames=keys);writer.writeheader()
        for m in modes:
            s=summaries[m];b=baseline[m]
            writer.writerow(dict(mode=m,expanded=s['result']['expanded'],generated=s['result']['generated'],
                pruned=s['result']['pruned'],max_expanded_depth=s['actual_max_expanded_depth'],
                max_generated_depth=s['max_generated_depth'],generated_complete_candidates=s['generated_complete_candidates'],
                duplicate_pops=s['duplicate_pops'],unique_popped_states=s['unique_popped_states'],
                h_calls=b['heuristic_calls_median'],h_microseconds_per_call=1e6*b['heuristic_wall_s_median']/b['heuristic_calls_median'],
                search_seconds=b['search_wall_s_median'],root_h=b['root_h_median']))
    with (folder/'root_decomposition.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(root['rows'][0]));writer.writeheader();writer.writerows(root['rows'])
    colors={'mass_lb':'#777777','stdc_lb':'#D55E00','paper_greedy':'#0072B2'}
    fig,axes=plt.subplots(2,2,figsize=(12,8),constrained_layout=True)
    for m in modes:
        pops=[r for r in traces[m] if r['event']=='pop']
        axes[0,0].plot(np.arange(len(pops))+1,[r['depth'] for r in pops],label=m,color=colors[m],linewidth=1)
        depths=summaries[m]['depths']
        axes[0,1].plot([r['depth'] for r in depths],[r['pops'] for r in depths],'o-',label=m,color=colors[m],markersize=3)
    axes[0,0].axhline(49,color='black',ls='--',lw=1);axes[0,0].set_xlabel('Pop index');axes[0,0].set_ylabel('Depth')
    axes[0,0].set_title('Budget consumed before reaching depth 49');axes[0,0].legend(fontsize=8)
    axes[0,1].set_yscale('log');axes[0,1].set_xlabel('Depth');axes[0,1].set_ylabel('Pop count (log)')
    axes[0,1].set_title('Many shallow prefixes; traces are not benchmarks')
    steps=[r['k'] for r in root['rows']]
    axes[1,0].plot(steps,[r['ell'] for r in root['rows']],label='STDC relaxed mass bound',color=colors['stdc_lb'])
    prior=read(ROOT/'outputs/stdc_v0_2/local_validation_20261123_r5/paired_comparison/paper_greedy_eps_1p1_rep_0/paper_greedy.json')
    axes[1,0].plot(steps,prior['survival'][1:],label='One feasible paper route (not optimum)',color=colors['paper_greedy'])
    axes[1,0].set_yscale('log');axes[1,0].set_xlabel('Future step k from root');axes[1,0].set_ylabel('Undetected mass (log)')
    axes[1,0].set_title('Optimistic relaxed tail');axes[1,0].legend(fontsize=8)
    names=['mass_lb','reach_lb','capacity_lb','stepwise_lb','stdc_lb','paper_greedy']
    axes[1,1].barh(names,[root['root_h'][m] for m in names],color=['#777777']*4+['#D55E00','#0072B2'])
    axes[1,1].set_xlabel('Root heuristic');axes[1,1].set_title('paper_greedy is not a certified lower bound')
    for ax in axes.flat:ax.grid(alpha=.15);ax.set_axisbelow(True)
    fig.suptitle('STDC diagnosis: frozen Lake Ontario, epsilon=1.10, unchanged 5000-expansion budget')
    fig.savefig(folder/'diagnosis.png',dpi=170);plt.close(fig)
    s=summaries['stdc_lb'];paper=summaries['paper_greedy'];mass=summaries['mass_lb']
    report=f'''# STDC 问题归因报告

结论：当前证据支持“可采纳放松仍过于乐观 → 大量短前缀优先 → 扩展预算内未生成完整路径”，同时存在重复状态计算和较高的启发式开销。没有发现能够解释这次退化的公式、时间索引或搜索接入错误。未修改算法来追求更好结果。

## 诊断范围与可信度

以已上传提交 4a01dee 为起点。读取并校验冻结真实粒子、原 forcing、协议及评价器 SHA，保留原目标、PT 初始路径、ε=1.10、5000 expansions / 20000 OPEN / 30 s。给原 search_asar 添加已有 trace 回调及只读观测包装，没有状态合并或搜索排序变化。

三个诊断搜索的 J、路径、状态、incumbent 来源、expanded/generated/pruned/peak_open 与既有无追踪结果逐项完全一致。诊断墙钟含额外记录开销，不作为性能成绩；本报告耗时来自上一轮三次独立进程基准。未重跑 OpenDrift。生产源码 SHA 前后不变。

## 1. 直接原因：尚未到达完整路径

| 方法 | 扩展数 | 最大展开深度 | 最深生成 | 完整候选数 | 剪枝 |
|---|---:|---:|---:|---:|---:|
| mass_lb | 5000 | {mass['actual_max_expanded_depth']} | {mass['max_generated_depth']} | {mass['generated_complete_candidates']} | 0 |
| STDC | 5000 | {s['actual_max_expanded_depth']} | {s['max_generated_depth']} | {s['generated_complete_candidates']} | 0 |
| paper_greedy | 107 | {paper['actual_max_expanded_depth']} | {paper['max_generated_depth']} | {paper['generated_complete_candidates']} | 4 |

任务要求 49 步。STDC 最深只生成 14 步，并非找到较好路径后评分或保存错误。search.py 仅在生成完整终点时更新 incumbent；扩展中止返回原 PT 是该行为的直接结果。STDC 比 mass 搜得更深，二者计数相同不代表搜索顺序相同。

在已知 paper 路径上，STDC 仅弹出到第 8 步的等价 (depth, vertex, belief) 状态；第 9 步候选已入队但未出队，其 f=g+1.1h=12.223390，高于所有已出队节点的最大 f=12.178884。更多低 f 前缀挡在该延伸之前。这是对已知可行路径的检查，不是对未知最优路径的识别，也不表示观测到了相同历史路径。

## 2. 下界更紧，但仍然非常乐观

| 根估值 | 数值 |
|---|---:|
| mass_lb | {root['root_h']['mass_lb']:.10f} |
| reach_lb | {root['root_h']['reach_lb']:.10f} |
| capacity_lb | {root['root_h']['capacity_lb']:.10f} |
| stepwise_lb | {root['root_h']['stepwise_lb']:.10f} |
| STDC | {root['root_h']['stdc_lb']:.10f} |
| paper_greedy（不是可认证下界） | {root['root_h']['paper_greedy']:.10f} |

STDC 的多格同时探测放松忽略了每步只能探测一个格子；capacity 的 U_k 使用未来无探测质量，对先前已经探测消耗过的潜在收益保持乐观。这些是允许的下界放松，不能写成代码漏更新或数学错误。

根状态第 20 步的耦合质量下界只有 {evidence['relaxed_root_mass_at_20']:.8g}；第 21–49 步的尾部代价下界合计只有 {evidence['relaxed_root_cost_after_20']:.8g}。作为对照，一条实际可行 paper 路径在第 20 步仍有未探测质量 {evidence['paper_path_mass_at_20']:.8f}，之后尾部代价为 {evidence['paper_path_cost_after_20']:.8f}。此比较仅展示放松程度；可行路径不是 Oracle 真最优值，不能把差额称为最优值估计误差。

## 3. 时序耦合的新增贡献很小

本真实根状态 STDC−stepwise = {evidence['root_coupling_gain']:.1f}，STDC−capacity = {evidence['root_capacity_gain']:.8g}。已完成的 160 个 toy 根状态中，耦合比 stepwise 严格提高超过 1e-8 的只有 {evidence['toy_roots_with_coupling_gain_gt_1e_8']} 个。

在所检验的 toy 根状态上，STDC 相对 mass 的下界增量主要已由可达性和容量约束解释；对整次搜索的收益归因仍需逐前缀消融。这里没有证明耦合对全部深度或全部输入均无作用。

## 4. 重复工作与计算成本

STDC 的 5001 次出队含最后一次未扩展的预算检查节点；其中 {s['duplicate_pops']} 次重复了之前的 (depth,vertex,belief逐字节指纹)。这些状态的 g 在本次 STDC 出队记录中也相同。20001 次启发式调用中有 {s['duplicate_evaluations']} 次重复相同状态身份，但生成状态的 g 不保证相同。

仅按 (depth,vertex) 合并仍不正确：诊断确实观察到同一位置/深度对应不同 belief。这里仅计数，没有实现去重、剪枝或缓存；完整状态上的支配规则能否在保持正确性的同时带来收益，需要独立验证。

在 ε=1.10 基准中，STDC 调用 h 20001 次，paper 仅 429 次；平均每次约 464 µs 与 272 µs。STDC 跟踪记录对应 {s['remaining_step_iterations']:,} 次剩余时步循环，paper 为 {paper['remaining_step_iterations']:,} 次。主要差距不仅是每次 h 较贵，也来自大量浅层节点反复计算很长的剩余时域。

独立 cProfile 诊断对已知路径深度 0–13 共求值 1400 次：stdc 主函数 Python 自身计算、reachable 的重复参数验证、NumPy 归约和 cell_mass 都产生开销。reachable 累积约 {profile_reach:.3f} s / 总 {profile_total:.3f} s，数组 copy 合计约 {profile_copy:.3f} s；不能把问题简单归咎为数组复制。该剖析包含 profiler 开销，不是搜索性能基准。

## 5. 已排除或未证实的解释

- 未见绝对时间 d+k 与相对 k 混淆、特殊 bin 质量丢弃、t=0 多探测、评分器差异或替换真实输入。
- STDC 和 mass 的中止均不是先触发 30 秒或 OPEN 上限；二者在三个 ε 的原基准中都先到 5000 次扩展。
- 不支持把 FIFO 同 f 平台当成 STDC 的主要归因：STDC 5001 次出队有 3270 个不同 f，最大完全同 f 组只有 11 次。mass 的最大同 f 组为 2167 次。没有修改 tie-break 做因果干预，故不声称其完全无影响。
- paper_greedy 更快、更好只是该冻结场景的有限预算事实；它仍不能认证动态 ε 界。不能为追求接近 paper 的估值而任意抬高 STDC 下界。

## 下一步应验证什么

1. 优先研究保留空间移动连续性、避免过分乐观尾部代价的下界；每项修改先对小图逐前缀 Oracle 检验可采纳性。仅把 h 调大不是合法修复。
2. 将已证实的重复状态作为单独实验：键必须包含完整 belief，且比较累计 g；不得使用 (depth,vertex) 粗合并。本轮未实施。
3. 计算加速可以改善耗时，但本轮 5000 扩展先中止，保持同一搜索顺序与扩展预算时，加速本身不会改善返回 J。
4. 若研究“可行解引导 + 可采纳界认证”的分工，应另立对照协议，给所有方法相同的初始解和预算；不能混写成本轮 STDC 的成果。

当前先冻结归因证据，不实施第二个创新点，不改原目标/forcing/预算，也不自动推送这些新增诊断。

## 证据

- diagnosis.json、三份 *.trace.jsonl：完整搜索轨迹与无追踪参考的一致性断言。
- root_decomposition.json/CSV、path_bounds.json、known_path_prefix_progress.json、mechanism_evidence.json。
- search_diagnosis.csv、heuristic_profile.txt/JSON/pstats、diagnosis.png。
- source_before.json、post_diagnosis_preservation.json：源码与旧数据保护记录。
'''
    (folder/'diagnosis_report.md').write_text(report,encoding='utf-8',newline='\n')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    main(parser.parse_args().output_dir.resolve())
