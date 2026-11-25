"""Post-experiment descriptive analysis only; never runs or tunes a planner."""
import json
from pathlib import Path
import sys
import numpy as np
from stdc_validation_guards import load_real, digest, save, require

root=Path(__file__).resolve().parent
agg=json.loads((root/'benchmark/aggregate.json').read_text(encoding='utf-8'))['rows']
rows=json.loads((root/'benchmark/results.json').read_text(encoding='utf-8'))['rows']
work={a['variant']:a for a in agg if a['protocol']=='work'}
protocol,grid,cfg,pt,times,raw=load_real()
cells=cfg['motion'].cell_ids
before,after=cells[:-1],cells[1:]
water=(before<grid.size)&(after<grid.size)
distance=np.abs(before//grid.cols-after//grid.cols)+np.abs(before%grid.cols-after%grid.cols)
unique,counts=np.unique(distance[water],return_counts=True)
kinematics=dict(water_to_water_steps=int(water.sum()),
    manhattan_step_histogram={str(int(k)):int(v) for k,v in zip(unique,counts)},
    jumps_larger_than_one=int(((distance>1)&water).sum()),
    special_to_water=int(((before>=grid.size)&(after<grid.size)).sum()),
    water_to_special=int(((before<grid.size)&(after>=grid.size)).sum()))
audit=[json.loads(s) for s in (root/'planning_validation/oracle_audit/audit/prefixes.jsonl').read_text(encoding='utf-8').splitlines()]
particles=[a for a in audit if 'dp_only' in a['bounds']]
require(len(particles)==9012,'prefix evidence count changed')
dp_cases=dict(checked=len(particles),stronger=sum(a['bounds']['dp_only']>a['bounds']['stdc_lb']+1e-10 for a in particles),
    weaker=sum(a['bounds']['dp_only']<a['bounds']['stdc_lb']-1e-10 for a in particles),
    equal_within_tolerance=sum(abs(a['bounds']['dp_only']-a['bounds']['stdc_lb'])<=1e-10 for a in particles),tolerance=1e-10)
phases=[]
for row in rows:
    if not row['variant'].startswith('mid_'):continue
    path=root/'benchmark'/f"{row['variant']}_{row['protocol']}_r{row['repeat']}"/'raw_result.json'
    detail=json.loads(path.read_text(encoding='utf-8'))
    seed,roll=detail['phases']
    phases.append(dict(variant=row['variant'],protocol=row['protocol'],repeat=row['repeat'],
        seed_J=seed['result']['J'],final_J=row['J'],rollout_improvement=seed['result']['J']-row['J'],
        anchors=roll['result']['stats']['anchor_depths'],seed_status=seed['result']['status'],
        rollout_status=roll['result']['status'],seed_expanded=seed['result']['expanded'],
        rollout_expanded=roll['result']['expanded'],beam_discarded=roll['result']['stats']['beam_discarded']))
dp_row=next(r for r in rows if r['variant']=='dp_only' and r['protocol']=='work' and r['repeat']==0)
evidence=dict(status='passed',analysis_kind='post-experiment descriptive; no parameter tuning',
    command=[sys.executable,*sys.argv],script_sha256=digest(Path(__file__)),
    benchmark_sha256=digest(root/'benchmark/results.json'),real_kinematics=kinematics,
    prefix_dp_comparison=dp_cases,midpoint_phases=phases,
    root_dp_lb=dp_row['preprocessing']['root_dp_lb'],dp_preprocessing=dp_row['preprocessing']['dp'],
    dp_time_reduction_vs_prior_stdc=1-work['dp_only']['search_wall_s_median']/work['prior_stdc']['search_wall_s_median'],
    dp_time_reduction_vs_compressed_stdc=1-work['dp_only']['search_wall_s_median']/work['compressed_stdc']['search_wall_s_median'],
    epsilon_certified=False)
save(root/'interpretation.json',evidence)
lines=['# 本轮结果解释','',
    '未突破 J=17.264874448。以下为冻结实验完成后的描述性分析，没有据此修改参数或追加挑选结果的试跑。','',
    f"DP-only 同扩展预算的耗时中位数为 {work['dp_only']['search_wall_s_median']:.4f} s；较本轮 prior_stdc 低 {100*evidence['dp_time_reduction_vs_prior_stdc']:.1f}%，较同样压缩的 compressed_stdc 低 {100*evidence['dp_time_reduction_vs_compressed_stdc']:.1f}%。J/Pd均相同。尚未在本轮重新对照上一轮的最快zero/mass方法，因此不能称已打破所有既有速度纪录。",
    'DP根下界为5.691508494964136，弱于STDC的9.179977673619849；max(STDC,DP)额外建表和查询没有改善本轮最佳J。真实LP30秒中止且未取得非平凡已验证对偶下界，不能以其primal值或未闭合gap宣称最优或声称必有改善空间。',
    '中段改写确有局部作用：work协议里，mid_plain把2000扩展seed的J=17.2919684950528降到17.264874448，补回已有最佳水平；multi-anchor实际为[6,10,18]。diverse与mid_dp在该协议保持较弱seed，有限beam的多样性保留挤占了此例更有用的quality候选。后一句是消融结果支持的解释，并非全部场景的定理。',
    'wall协议三种中段方法均返回已有最佳值；需查看interpretation.json逐次seed_J，不能把seed已经达到的收益归给rollout。','',
    f"随机前缀DP比较：{dp_cases}。该随机生成器的粒子每步只停留或走邻格，special永久停留，因此本组无加强具有结构性解释。",
    '在至少两格的四连通矩形图中，若目标每步移动距离≤1且始终在域内，其两个exact-reachable探测时刻a<b间，目标位置距离≤b-a，奇偶也与b-a一致。于是可用恰好b-a步的合法搜索路径连接。串接所有可达探测时刻，可实现reach_lb对该粒子的全部理想探测；因而此特殊条件下h_DP=h_reach≤h_STDC。永久special粒子贡献完整剩余质量。此论证不包括任意跳跃或离域再入域，不能推广成一般动态场景的支配定理。',
    f"真实归档逐帧检查（原SHA门禁重验成功）：{kinematics}。是否满足上述特殊条件可据此判断；无论如何，本轮只以已报告的真实根下界数值作为真实强度证据。",'',
    '全部903项测试、随机前缀Oracle和150次小图搜索均通过。真实结果没有epsilon认证，beam完成也不是穷尽全局搜索。',
    '保留本轮可用模块与负结果。未来若另立协议，宜针对共同平台的多粒子竞争约束研究更紧放松，并用探测事件的长期收益设计多样性；本轮没有实现这些扩展，也未改变原目标或forcing。']
(root/'interpretation.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
fig,axes=plt.subplots(2,2,figsize=(13,9),constrained_layout=True)
for i,protocol_name in enumerate(('work','wall')):
    group=[a for a in agg if a['protocol']==protocol_name]
    names=[a['variant'] for a in group]
    delta=[1000*(a['J_median']-17.264874448) for a in group]
    bars=axes[i,0].barh(names,delta,color=['#D55E00' if v>1e-7 else '#009E73' for v in delta])
    axes[i,0].axvline(0,color='black',lw=.8);axes[i,0].invert_yaxis()
    axes[i,0].set(xlabel='1000 x (J - previous best); lower is better',title=protocol_name+' budget: no J breakthrough',xlim=(-1,36))
    for bar,value in zip(bars,delta):axes[i,0].text(max(0,value)+.3,bar.get_y()+bar.get_height()/2,f'{value:.3f}',va='center',fontsize=8)
    bars=axes[i,1].barh(names,[a['search_wall_s_median'] for a in group],color='#0072B2')
    axes[i,1].invert_yaxis();axes[i,1].set(xlabel='Paid method seconds (median of 3)',title='Preprocessing included',xlim=(0,6.2))
    for bar in bars:axes[i,1].text(bar.get_width()+.04,bar.get_y()+bar.get_height()/2,f'{bar.get_width():.3f}',va='center',fontsize=8)
fig.suptitle('One frozen real Lake Ontario archive | all-water approximation | all routes uncertified')
fig.savefig(root/'core_comparison.png',dpi=170);plt.close(fig)
print(json.dumps({k:evidence[k] for k in ('status','real_kinematics','prefix_dp_comparison','dp_time_reduction_vs_prior_stdc','dp_time_reduction_vs_compressed_stdc')},ensure_ascii=False),flush=True)
