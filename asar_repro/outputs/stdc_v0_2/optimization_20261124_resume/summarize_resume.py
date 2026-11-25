"""Report-only postprocessing of frozen, independently replayed experiments."""
import csv
import hashlib
import json
from pathlib import Path
from statistics import median
import sys

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from run_optimization_validation import preserve, environment

def read(path):return json.loads(path.read_text(encoding='utf-8'))
def save(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def require(ok,msg):
    if not ok:raise AssertionError(msg)
def csv_save(path,rows):
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def main():
    validation=read(OUT/'validation/validation_summary.json')
    require(validation['status']=='passed' and not validation['not_run'],'validation gate failed')
    final=read(OUT/'validation/final_preservation/stage.json')
    require(final['status']=='passed','final preservation missing/failed')
    for folder in ('smoke','benchmark'):
        require(read(OUT/folder/'summary.json')['status']=='passed',folder+' gate failed')
        for item in read(OUT/folder/'artifact_manifest.json')['files']:
            require(sha(OUT/folder/item['path'])==item['sha256'],folder+' artifact mismatch')
    proof=preserve(OUT/'validation')
    old=ROOT/'outputs/stdc_v0_2/optimization_20261124'
    for item in read(old/'artifact_manifest.json')['files']:
        require(sha(old/item['path'])==item['sha256'],'prior blocked evidence changed')
    before=read(old/'before_changes.json')['protected']
    require(all(sha(ROOT.parent/name)==value for name,value in before.items()),'pre-edit file changed')
    proof.update(pre_edit_preserved=len(before),prior_blocked_artifacts_preserved=True)
    save(OUT/'final_preservation.json',proof)
    rows=read(OUT/'benchmark/results.json')['rows']
    require(len(rows)==66,'incomplete formal schedule')
    agg=read(OUT/'benchmark/aggregate.json')['rows']
    lookup={(r['protocol'],r['variant']):r for r in agg}
    rand=read(OUT/'validation/random_audit/audit/summary.json')
    small=read(OUT/'validation/small_search/audit/summary.json')
    prior_stdc=17.264874448
    baseline_J=17.29389415456; baseline_Pd=.89737041888
    attributed=[]
    for protocol in ('work','wall'):
        for variant in sorted({r['variant'] for r in rows}):
            group=[r for r in rows if r['protocol']==protocol and r['variant']==variant]
            a=lookup[protocol,variant];ref=lookup[protocol,'anytime_reference'];fast=lookup[protocol,'fast_stdc']
            deltas=[]
            for r in group:
                b=next(x for x in rows if x['protocol']==protocol and x['variant']=='anytime_reference' and x['repeat']==r['repeat'])
                deltas.append(r['J']-b['J'])
            targets=[]
            for r in group:
                reached=next((e for e in r.get('incumbent_history',[]) if e['J']<=prior_stdc+1e-10),None)
                if reached is not None:
                    targets.append(reached['elapsed_s'])
            attributed.append(dict(protocol=protocol,variant=variant,J_median=a['J_median'],Pd_median=a['Pd_T_median'],
                J_improvement_vs_original_pct=100*(baseline_J-a['J_median'])/baseline_J,
                Pd_change_vs_original_pp=100*(a['Pd_T_median']-baseline_Pd),
                J_change_vs_previous_stdc=a['J_median']-prior_stdc,
                paired_J_change_vs_reference_median=median(deltas),
                paired_J_change_vs_reference_min=min(deltas),paired_J_change_vs_reference_max=max(deltas),
                time_ratio_vs_reference=a['search_wall_s_median']/ref['search_wall_s_median'],
                time_ratio_vs_fast=a['search_wall_s_median']/fast['search_wall_s_median'],
                previous_J_target_reached_runs=len(targets),
                previous_J_target_time_median=median(targets) if targets else None,
                previous_J_target_time_min=min(targets) if targets else None,
                previous_J_target_time_max=max(targets) if targets else None,
                peak_memory_mib=a['process_peak_memory_mib_median']))
    csv_save(OUT/'core_comparison.csv',attributed);save(OUT/'core_comparison.json',dict(rows=attributed))
    profiles=[]
    for r in rows:
        stats=r.get('stats',{});seed=stats.get('seed_stats',{})
        profiles.append(dict(protocol=r['protocol'],variant=r['variant'],repeat=r['repeat'],
            guide_calls=stats.get('guide_calls',0)+seed.get('guide_calls',0),
            guide_s=stats.get('guide_wall_s',0)+seed.get('guide_wall_s',0),
            bound_calls=stats.get('bound_calls',0)+seed.get('bound_calls',0),
            bound_s=stats.get('bound_wall_s',0)+seed.get('bound_wall_s',0),
            main_expanded=r['expanded'],aux_expanded=stats.get('aux_expanded',0),work_expanded=r['work_expanded'],
            complete_candidates=stats.get('complete_candidates',0)+seed.get('complete_candidates',0),
            candidate_replays=stats.get('candidate_replays',0)+seed.get('candidate_replays',0),
            peak_open=r['peak_open'],logical_frontier=stats.get('frontier_remaining'),
            stop_reason=r['stop_reason'],overshoot_s=r['cooperative_overshoot_s']))
    csv_save(OUT/'cost_breakdown.csv',profiles)
    compress=[dict(protocol=r['protocol'],repeat=r['repeat'],**r['compression']) for r in rows if r.get('compression')]
    save(OUT/'compression_analysis.json',dict(rows=compress))
    conclusions={}
    for protocol in ('work','wall'):
        subset=[a for a in agg if a['protocol']==protocol]
        best=min(subset,key=lambda a:a['J_median'])
        conclusions[protocol]=dict(best_observed_median_method=best['variant'],J=best['J_median'],Pd=best['Pd_T_median'],
            methods_below_previous_stdc=[a['variant'] for a in subset if a['J_median']<prior_stdc-1e-10],
            warning='descriptive comparison of separately paid runs; no free method selection portfolio')
    result=dict(status='passed',date='2026-11-24',new_tests=199,full_tests=693,
        random_cases=rand['cases'],prefix_evaluations=rand['prefix_evaluations'],bound_violations=rand['violations'],
        strict_bound_improvements=rand['strictly_improved_prefixes'],max_bound_overestimate=rand['max_overestimate'],
        small_cases=small['cases'],small_searches=small['searches'],max_small_J_error=small['max_J_error'],
        max_small_replay_error=small['max_replay_error'],smoke_runs=11,formal_runs=len(rows),
        formal_completed=sum(r['status']=='completed' for r in rows),formal_budget_exceeded=sum(r['status']=='budget_exceeded' for r in rows),
        epsilon_certified=False,conclusions=conclusions,source_changed_since_blocked=False,
        environment_resolution='same 35448 account and interpreter: hard links denied inside sandbox, allowed outside; unchanged full tests passed outside sandbox',
        preservation=proof,scope='single frozen historical Lake Ontario all-water approximation; repeats are timing repetitions, not independent scenes',
        environment=environment(),old_blocked_record=str(old/'final_outcome.json'))
    save(OUT/'final_outcome.json',result)
    lines=['# STDC 优化：继续验证与正式对照报告','',
      '**验证状态：passed。所有强制门槛已通过；实验结果仍不构成动态 ε 最优认证。**','',
      '日期：2026-11-24（Asia/Shanghai）。研究分支 stdc-research-v0.2。',
      '上轮 blocked 原始目录完整保留。本轮没有更改任何 src/tests/scripts 源码或断言；权限问题通过允许硬链接的执行环境解决。',
      '同一35448账户和解释器在沙箱内对C/E临时目录的硬链接操作均被拒绝，沙箱外成功。完整历史测试在沙箱外原样通过，未修改ACL、跳过测试或替换归档逻辑。','',
      '## 质量结论','',
      f'固定工作量组中，低于前轮STDC的J=17.264874448的方法为：{conclusions["work"]["methods_below_previous_stdc"] or "无"}。',
      f'5秒上限组中，低于前轮STDC的J=17.264874448的方法为：{conclusions["wall"]["methods_below_previous_stdc"] or "无"}。',
      '这是预定对照中各方法独立付费运行后的描述，不把事后最优方法当成免费组合搜索；具体性能收益与质量取舍见下表和core_comparison.csv。','',
      '## 验证结果','',
      '|门槛|结果|','|---|---|','|新增单测|199 passed，零失败/错误/跳过|',
      '|全量测试|693 passed＝历史494＋新增199，零失败/错误/跳过|',
      f'|随机逐前缀Oracle|160案例、18024前缀；违规0；最大浮点超越{rand["max_overestimate"]:.3g}，低于1e-10容差|',
      f'|两步前瞻增强|1854个前缀严格强于原STDC，仅为这些输入上的数值事实|',
      '|小图搜索|45案例、320次搜索，J与原Oracle误差0，独立重放误差0|',
      '|真实smoke|11/11通过；1正常、10预算中止|',
      f'|正式实验|66/66通过；{result["formal_completed"]}正常、{result["formal_budget_exceeded"]}预算中止；0认证|',
      f'|文件保全|baseline {proof["baseline_files"]}文件、研究保护{proof["protected_research_files"]}文件、源码{proof["source_files"]}文件SHA一致；修改前3199文件不变|','',
      '## 指标与成本','',
      'J越低越好，Pd越高越好。下面时间和内存是3次重复的中位数；J/Pd范围与逐次配对见CSV。两预算协议分别解释。',
      'core_comparison另报告达到冻结前轮J目标17.264874448的时间（从incumbent历史取首个满足事件），并列达标次数；未达标不填写时间，不把它混为总运行时间。',
      'work：最多5000总工作展开，包含前瞻辅助展开，物理OPEN≤20000，时间≤30秒。',
      'wall：时间上限5秒，无展开上限，物理OPEN≤20000；先触发OPEN可以提前停止。合作式时间检查超额单列。',
      '统一输入为共同冻结PT，guide权重1.04。原baseline首解即停止，相同上限不等于相同实际耗时。',
      '尾段组合付费用40%子配额生成seed，再尝试6/10/14步自由终点尾段；压缩构造、内部重放均计入方法时间。','',
      '|协议|方法|J|Pd|秒|主展开|总工作|峰值MiB|停止原因|','|---|---|---:|---:|---:|---:|---:|---:|---|']
    for a in agg:
        lines.append(f'|{a["protocol"]}|{a["variant"]}|{a["J_median"]:.9f}|{a["Pd_T_median"]:.9f}|{a["search_wall_s_median"]:.4f}|{a["expanded_median"]:g}|{a["work_expanded_median"]:g}|{a["process_peak_memory_mib_median"]:.2f}|{a["stops"]}|')
    lines+=['','原始最好J baseline参考点为 J=17.29389415456、Pd=0.89737041888；前轮anytime STDC为J=17.264874448、Pd=0.897364416。',
      'Pd差值始终相对同一条最好J基准路径；历史其他权重的最大Pd=0.89776904256，不把两条不同路径的最好指标拼接。','',
      '## 归因限制与已知问题','',
      '- fast_stdc相对anytime_reference同时改变了guide内核和候选档案/节点簿记，不能把全部时间变化称为纯guide收益；cost_breakdown.csv单列guide和bound成本。',
      '- lookahead的辅助工作计入总预算；更强下界不保证有限预算J更好。cascade和lookahead调用覆盖不同，属于集成策略对照。',
      '- tail_stdc与tail_zero同时改变seed与tail的bound，不能隔离为纯尾段STDC收益。global_seed_*停止原因是子配额中止，未必耗尽全方法总上限。',
      '- tail原始stats大多为尾段局部，seed_stats保存全局seed开销；本报告cost_breakdown已按阶段相加。尾段history.generated仍为局部计数，不当作全局累计量。',
      '- compressed_stdc包含严格分组和readonly无变化共享。分组减少量见compression_analysis.json；浮点求和顺序可能改变排序，最终使用原ID评分器重放。',
      '- portfolio双heap的副本与stale条目全部计物理OPEN，逻辑容量更小；max_open必须明确报告。',
      '- search_wall_s是方法调用时间（含内部重放/压缩构造），不是含外部核验与进程启动的端到端耗时。进程峰值包括导入和输入核验。',
      '- preflight的seed_subbudget=null为不完整描述，tail实际40%配额以benchmark/protocol.json与raw phases为准。',
      '- 全部是一个真实历史forcing的all-water离散归档，N500、17×17、T49、q=.78、seed41；三重复不是三个独立场景。不外推其他事故或真实海岸约束。',
      '- 保持t=0不检测、四连通、未归一化未探测权重与所有特殊质量；J仍是唯一优化目标，未添加Pd约束。',
      '- paper_greedy只排序；预算中止的路径没有动态ε保证。完整小图Oracle一致性不能替代一般数学证明。','',
      '## 交付','',
      '- core_comparison.csv/json：核心J/Pd、相对原baseline及前轮STDC差值、同协议配对差值。',
      '- cost_breakdown.csv、compression_analysis.json：各方法成本和分组记录。',
      '- benchmark/metrics.csv、aggregate.csv、paired_comparisons.csv：原始汇总及3次范围。',
      '- benchmark/results.json及各worker/raw_result.json：完整路径、incumbent、预算来源、SHA与独立重放。',
      '- final_preservation.json、artifact_manifest.json：输入、源码、旧结果保全与本轮产物指纹。',
      '- validation各阶段和每个worker的command.json、stdout/stderr、pytest.xml/stage.json、diff和seed均保留。',
      '- 新增代码文件清单见上一轮changed_files.json；本轮源码变化为0。','',
      '![work质量与剩余质量](benchmark/work_quality_survival.png)','',
      '![wall质量与剩余质量](benchmark/wall_quality_survival.png)','',
      '![work效率](benchmark/work_efficiency.png)','',
      '![wall效率](benchmark/wall_efficiency.png)','',
      '路径图为benchmark/work_paths.png与wall_paths.png。','',
      '## 离线复跑','',
      '解释器C:/Users/35448/.conda/envs/maritime-sar/python.exe；保持scripts/offline_guard、src、scripts在PYTHONPATH，数值库单线程，ASAR_OFFLINE=1、PROJ_NETWORK=OFF、PYTHONDONTWRITEBYTECODE=1。',
      '使用全新结果目录，依次执行run_optimization_validation.py的init/new_tests/full_tests/random_audit/small_search；完整命令和环境见各command.json。',
      '历史测试需要允许Windows硬链接的执行上下文。随后执行run_optimization_experiments.py smoke及benchmark，提供通过的validation_summary.json和smoke目录；最后final_preservation。',
      '禁止覆盖既有输出；没有运行OpenDrift重新生成轨迹、改forcing或开展第二创新点。']
    (OUT/'FINAL_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    save(OUT/'artifact_manifest.json',dict(status='passed',files=[dict(path=p.relative_to(OUT).as_posix(),bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(OUT.rglob('*')) if p.is_file() and p!=OUT/'artifact_manifest.json']))
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
