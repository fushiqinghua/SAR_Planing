"""Verify and independently replay three frozen datasets; never pool raw J."""
from pathlib import Path
from statistics import median
from collections import Counter
import xml.etree.ElementTree as ET
import numpy as np
from stdc_validation_guards import ROOT,read,save,require,digest,load_real,check_score
from compare_additional_real import load_input
from run_trajectory_experiments import VARIANTS,CAPS
from run_anytime_experiments import csv_save,manifest
from run_optimization_validation import sources,environment,snapshot
from run_additional_real import preservation
from asar_repro.objective import score_path

out=Path(__file__).resolve().parent;base=out.parent
folders={'lake_ontario':base/'trajectory_20261124','arctic_ocean':base/'additional_real_20261124','bay_of_fundy':base/'fundy_repair_20261124'}
NAMES={'lake_ontario':'Lake Ontario','arctic_ocean':'Hudsons Bay','bay_of_fundy':'Bay of Fundy [direction UNVERIFIED]'}
current=sources();records=[];provenance={};replay=[];aggregate=[];pairs=[]
current_env=environment()
for frozen_dir in ('additional_real_20261124','fundy_repair_20261124'):
    frozen=base/frozen_dir
    for f in read(frozen/'final_fingerprints.json')['files']:
        require(digest(frozen/f['path'])==f['sha256'],'prior archived file changed')
for scene,folder in folders.items():
    summary=read(folder/'benchmark/summary.json');require(summary['status']=='passed' and summary['runs']==48,'incomplete benchmark '+scene)
    for f in read(folder/'benchmark/artifact_manifest.json')['files']:
        require(digest(folder/'benchmark'/f['path'])==f['sha256'],'artifact changed '+scene+'/'+f['path'])
    if scene=='lake_ontario':
        proto,grid,cfg,pt,_,raw=load_real();sha=proto['particle_archive']['sha256'];mission=proto['mission'];ptJ=pt.J;ptPd=pt.pd_final
        source_env=read(folder/'final/environment.json');direction='no Fundy-specific angle policy; historical all-water approximation'
    else:
        grid,cfg,meta=load_input(folder,scene);sha=meta['particle_sha256'];mission=meta['config']
        proto=read(folder/'frozen_comparison/protocol.json');raw=meta['provenance']['input_fingerprints']['sources']
        ptJ=proto['scenarios'][scene]['PT_J'];ptPd=proto['scenarios'][scene]['PT_Pd'];source_env=proto['environment']
        direction=meta.get('direction_policy','historical all-water approximation')
    require(source_env['versions']==current_env['versions'] and source_env['python_version']==current_env['python_version'],'package environment mismatch')
    provenance[scene]=dict(particle_sha256=sha,mission=mission,original_forcing=raw,environment=source_env,
        data_label='historical model forcing; Leeway simulated frozen particles',direction_policy=direction,
        PT_J=ptJ,PT_Pd=ptPd,grid=[grid.rows,grid.cols],N=cfg['motion'].state_size,
        benchmark_path=str(folder/'benchmark'),results_sha256=digest(folder/'benchmark/results.json'),
        acquired_this_turn=scene=='bay_of_fundy',allwater_coast_approximation=True)
    rows=read(folder/'benchmark/results.json')['rows'];require(len(rows)==48,'row count')
    require(len({(r['variant'],r['protocol'],r['repeat']) for r in rows})==48,'duplicate run')
    for r in rows:
        require(r['particle_sha256']==sha and r['limits']==CAPS[r['protocol']],'input or cap changed')
        require(r['particle_seed']==41 and not r['smoke'] and not r['theory_certified'],'invalid scope')
        require(all(current.get(k)==v for k,v in r['source_sha256'].items()),'implementation drift')
        if scene=='bay_of_fundy':require('geography_unverified' in r['experiment_label'],'missing physical limitation')
        s=score_path(grid,r['path'],**cfg);check_score(s)
        eJ=abs(s.J-r['J']);eP=abs(s.pd_final-r['Pd_T']);require(max(eJ,eP)<1e-10,'final score mismatch')
        np.testing.assert_allclose(s.survival,r['survival'],rtol=0,atol=1e-10)
        for event in r.get('incumbent_history',[])+r.get('candidate_archive',[]):
            scored=score_path(grid,event['path'],**cfg);check_score(scored)
            require(abs(scored.J-event['J'])<1e-10 and abs(scored.pd_final-event['Pd'])<1e-10,'history score mismatch')
        replay.append(dict(scenario=scene,variant=r['variant'],protocol=r['protocol'],repeat=r['repeat'],J_error=eJ,Pd_error=eP,legal=True))
        origin=r.get('incumbent_origin',r['incumbent_source'])
        if r['incumbent_source']=='initial_path':origin='common_frozen_ParallelTrack'
        record={k:r[k] for k in ('variant','protocol','repeat','J','Pd_T','search_wall_s','work_expanded','process_peak_memory_mib','status','stop_reason','limits','input_verification_s','cooperative_overshoot_s','experiment_label')}
        record.update(scenario=scene,physical_direction_unverified=scene=='bay_of_fundy',incumbent_origin=origin,
                      particle_sha256=sha,PT_J=ptJ,PT_Pd=ptPd,epsilon_certified=False)
        records.append(record)
    for cap in CAPS:
        for method in VARIANTS:
            group=[r for r in records if (r['scenario'],r['protocol'],r['variant'])==(scene,cap,method)]
            require(len(group)==3,'repeats incomplete')
            a=dict(scenario=scene,protocol=cap,variant=method,n=3,
                   physical_direction_unverified=scene=='bay_of_fundy',
                   completed=sum(r['status']=='completed' for r in group),
                   budget_exceeded=sum(r['status']=='budget_exceeded' for r in group),
                   stops=dict(Counter(r['stop_reason'] or 'completed' for r in group)),
                   incumbents=dict(Counter(r['incumbent_origin'] for r in group)))
            for key in ('J','Pd_T','search_wall_s','work_expanded','process_peak_memory_mib'):
                a[key+'_median']=median(r[key] for r in group);a[key+'_min']=min(r[key] for r in group);a[key+'_max']=max(r[key] for r in group)
            aggregate.append(a)
for r in records:
    for ref in ('paper_baseline','prior_stdc'):
        if r['variant']==ref:continue
        b=next(b for b in records if (b['scenario'],b['protocol'],b['repeat'],b['variant'])==(r['scenario'],r['protocol'],r['repeat'],ref))
        pairs.append(dict(scenario=r['scenario'],protocol=r['protocol'],variant=r['variant'],reference=ref,repeat=r['repeat'],
            J_reduction_percent=100*(b['J']-r['J'])/b['J'],Pd_delta_percentage_points=100*(r['Pd_T']-b['Pd_T']),
            time_ratio=r['search_wall_s']/b['search_wall_s'],memory_ratio=r['process_peak_memory_mib']/b['process_peak_memory_mib'],
            physical_direction_unverified=r['physical_direction_unverified']))
dp_details={}
for scene,folder in folders.items():
    r=next(r for r in read(folder/'benchmark/results.json')['rows'] if (r['variant'],r['protocol'],r['repeat'])==('dp_only','work',0))
    dp_details[scene]=dict(build=r['preprocessing']['dp'],compression={k:v for k,v in r['preprocessing']['compression'].items() if k not in ('groups','original_trajectory_ids')})
save(out/'dp_preprocessing_audit.json',dp_details)
save(out/'provenance.json',provenance);save(out/'aggregate.json',dict(rows=aggregate));save(out/'replay_audit.json',dict(rows=replay))
csv_save(out/'all_runs.csv',records);csv_save(out/'aggregate.csv',aggregate);csv_save(out/'paired_comparisons.csv',pairs)
tests=ET.parse(folders['bay_of_fundy']/'full_tests.xml').getroot()
tc={k:sum(int(s.get(k,0)) for s in tests.iter('testsuite')) for k in ('tests','failures','errors','skipped')}
require(tc==dict(tests=926,failures=0,errors=0,skipped=0),'historical test evidence')
save(out/'environment.json',environment())
summary=dict(status='passed_with_fundy_physical_direction_unverified',new_runs=48,reused_runs=96,total_runs=144,
 completed=sum(r['status']=='completed' for r in records),budget_exceeded=sum(r['status']=='budget_exceeded' for r in records),
 max_J_replay_error=max(r['J_error'] for r in replay),max_Pd_replay_error=max(r['Pd_error'] for r in replay),
 previous_tests=tc,tests_rerun_this_turn=False,source_sha256=current,preservation=preservation(folders['bay_of_fundy']),
 opendrift_runs_this_turn=0,epsilon_certified=False,physical_direction_unverified_scenarios=['bay_of_fundy'])
save(out/'validation_summary.json',summary)

lines=['# 三个真实历史 forcing 场景的同预算对照','',
 '**Fundy 按用户授权的官方 native angle 接入；物理方向未验证。所有搜索结果均 uncertified。**','',
 '本轮新运行 Fundy 48 次；Lake Ontario 与 Hudsons Bay 各复用此前48次正式实验，并重新检查文件指纹、输入/forcing、算法实现及原评分器重放。没有重新运行 Leeway，也没有覆盖旧结果。',
 '三个场景使用真实历史模型 forcing，但目标粒子由 Leeway 模拟，不是实测目标轨迹。全部保留既有 all-water 岸线碰撞近似；Fundy 另有 native angle 与地理网格约7°不一致，不能将其结果解释为物理方向已验证。','',
 '## 固定协议','',
 '- work：最多5000扩展、30秒、OPEN≤20000；wall：5秒、OPEN≤20000。各方法每协议3次重复，循环轮换方法顺序，独立子进程顺序执行。',
 '- 同一场景共享同一冻结 PT 和500粒子、seed=41、q=.78；目标仍为原 J=sum(M[1:T+1])，t=0不探测。算法预处理计入时间；公共PT构造、SHA校验不计入方法时间。',
 '- DP 管理数组上限128 MiB；不是进程内存上限。内存为 Windows 进程峰值 working set，包括解释器、导入、输入、预处理、搜索和重放。不同场景输入/导入开销不同，不直接跨场景比较绝对内存。',
 '- 3次重复共用一套冻结粒子，只衡量运行波动，不能当作3个独立随机环境。跨场景只报告各自相对baseline的差值，不把不同T/网格的J直接平均排名。',
 '- 方法：paper_baseline=原paper_greedy A^SAR；prior_stdc=直接STDC；compressed_stdc=等价粒子压缩；dp_only/stdc_dp=单粒子DP下界；mid_plain/mid_diverse/mid_dp=最新中段rollout及消融。所有变体完整列出，不事后挑一个代称“最新方法”。','',
 '## 核心指标（3次中位数；范围保留在 CSV）','']
for scene in folders:
    lines+=['### '+NAMES[scene],'',f"T={provenance[scene]['mission']['budget']}，网格={provenance[scene]['grid']}；粒子 SHA `{provenance[scene]['particle_sha256']}`。",'',
      '|预算|方法|J↓|Pd↑|耗时s|峰值MiB|扩展数|完成/预算中止|',
      '|---|---|---:|---:|---:|---:|---:|---|']
    for a in aggregate:
        if a['scenario']!=scene:continue
        lines.append(f"|{a['protocol']}|{a['variant']}|{a['J_median']:.9f}|{a['Pd_T_median']:.9f}|{a['search_wall_s_median']:.4f}|{a['process_peak_memory_mib_median']:.2f}|{a['work_expanded_median']:.0f}|{a['completed']}/{a['budget_exceeded']}|")
    lines+=['']
lines+=['## 配对结论','', '|场景/预算|STDC相对baseline的J下降%|Pd变化（百分点）|耗时比|峰值内存比|','|---|---:|---:|---:|---:|']
for scene in folders:
    for cap in CAPS:
        group=[p for p in pairs if (p['scenario'],p['protocol'],p['variant'],p['reference'])==(scene,cap,'prior_stdc','paper_baseline')]
        lines.append(f"|{NAMES[scene]} / {cap}|{median(p['J_reduction_percent'] for p in group):.6f}|{median(p['Pd_delta_percentage_points'] for p in group):+.6f}|{median(p['time_ratio'] for p in group):.3f}|{median(p['memory_ratio'] for p in group):.3f}|")
lines+=['','最新方法相对直接STDC的逐次配对差值见 `paired_comparisons.csv`（reference=prior_stdc）。J更小不意味着Pd必然更高；没有改变原始优化目标。','']
for scene in folders:
    for cap in CAPS:
        st=next(a for a in aggregate if (a['scenario'],a['protocol'],a['variant'])==(scene,cap,'prior_stdc'))
        later=[a for a in aggregate if a['scenario']==scene and a['protocol']==cap and a['variant'] not in ('prior_stdc','paper_baseline')]
        improved=[a['variant'] for a in later if a['J_median']<st['J_median']-1e-10]
        same=[a for a in later if abs(a['J_median']-st['J_median'])<1e-10 and not any(k.startswith('dp_') for k in a['stops'])]
        lines.append(f"- {NAMES[scene]} / {cap}：最新变体中，中位 J 严格优于直接 STDC 的方法：{improved or '无'}。")
        if same:
            fast=min(same,key=lambda a:a['search_wall_s_median'])
            lines.append(f"  同 J 的最新变体中耗时最低的是 {fast['variant']}：{fast['search_wall_s_median']:.4f}s，对照 STDC {st['search_wall_s_median']:.4f}s；这只是本批同分结果的描述，不是跨场景方法选择规则。")
lines+=['','## 中止及可验证范围','']
for scene in folders:
    rows=[r for r in records if r['scenario']==scene]
    lines.append(f"- {NAMES[scene]}：停止原因 {dict(Counter(r['stop_reason'] or 'completed' for r in rows))}；incumbent来源 {dict(Counter(r['incumbent_origin'] for r in rows))}。")
lines += ['',
 'DP因内存预算未初始化的结果只保留共同PT，不可当成正常搜索或声称耗时优势；midpoint的global_seed_*表示全局种子阶段预算受限，即使局部提案完成，也不代表全局搜索完成。每次中止原因和incumbent来源均保存在 all_runs.csv。',
 f"三场景共{summary['total_runs']}条最终路径全部独立重放合法；J最大误差{summary['max_J_replay_error']:.3g}、Pd最大误差{summary['max_Pd_replay_error']:.3g}。共{summary['completed']}次正常结束、{summary['budget_exceeded']}次预算中止。",
 f"协作式时间预算最大余量 {max(r['cooperative_overshoot_s'] for r in records):.6f} s；未将该余量隐藏为严格硬实时截止。",
 '原paper_greedy动态启发式仍无可采纳性保证；completed不等于认证最优。本批无ε证书。不能把三个固定任务上的数值差异推断为对一般场景的普适提升或统计显著性。','',
 '## 保全与复跑','',
 '规划器、评价器和forcing没有改动；沿用已通过的926项全量测试，未因仅新增实验启动/汇总脚本重复跑同一测试集。阶段manifest、source_sha256、每次command/stdout/stderr及seed均保存。',
 '本轮脚本：本目录 run_fundy_benchmark.py、summarize.py、plot_results.py；Fundy正式结果保存在相邻 fundy_repair_20261124/benchmark 新目录。旧smoke/blocked/repair报告是当时记录，没有回写成正式实验报告。',
 '离线执行需要 maritime-sar、offline_guard/src/scripts PYTHONPATH、UTF-8及单线程环境；精确子进程命令见每次 command.json。正式 benchmark 目录已存在时拒绝覆盖。',
 '汇总可读文件：all_runs.csv（144行）、aggregate.csv（48组）、paired_comparisons.csv、provenance.json（UTC/对象/CSP/扫宽/T/来源/指纹）、replay_audit.json、validation_summary.json。','']
lines+=['图件：three_scenes_work.png、three_scenes_wall.png；Fundy 带未验证标签的路径图 fundy_paths_qualified.png、质量曲线 fundy_work_survival_qualified.png / fundy_wall_survival_qualified.png。','',
 'DP 预处理细节见 dp_preprocessing_audit.json：Hudsons Bay 需要约 992.89 MiB、Fundy 约 638.71 MiB，均超过 128 MiB 上限；Fundy 等价压缩仍保留 500 列。','']
(out/'three_real_comparison.md').write_text('\n'.join(lines),encoding='utf-8')
print(summary)
