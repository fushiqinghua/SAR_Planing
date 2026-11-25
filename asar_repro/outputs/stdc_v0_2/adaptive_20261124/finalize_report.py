"""Generate the final adaptive experiment report only from completed frozen records."""
import hashlib,json
from pathlib import Path
from statistics import median
from collections import Counter
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from run_optimization_validation import read,save,digest,sources
RUN=Path(__file__).resolve().parent
def main():
    validation=read(RUN/'validation_summary.json')
    benchmark=read(RUN/'benchmark/summary.json')
    preservation=read(RUN/'final_preservation.json')
    assert validation['status']==benchmark['status']==preservation['status']=='passed'
    assert sources()==read(RUN/'freeze.json')['source_sha256']
    rows=read(RUN/'benchmark/results.json')['rows'];assert len(rows)==180
    agg=read(RUN/'benchmark/aggregate.json')['rows']
    oracle=read(RUN/'oracle/audit/summary.json')['stages']
    scene_names={'lake_ontario':'Lake Ontario','arctic_ocean':'Hudsons Bay','bay_of_fundy':'Bay of Fundy'}
    out=[]
    out+=['# STDC 自适应调度与紧凑 DP：最终实验报告','',
        '日期：2026-11-24。研究分支 stdc-research-v0.2。原目标、评价器、forcing、冻结 baseline 和旧实验数据未修改。',
        '本报告区分算法正确性、三个固定真实归档上的数值事实以及未认证的实际预算结果。','',
        '## 验证与实验范围','',
        f"新增测试 {validation['stages']['new_tests']['test_counts']['tests']} 项，全量测试 {validation['stages']['full_tests']['test_counts']['tests']} 项，均无 failures/errors/skips。",
        f"随机 160 案例、18024 前缀；compact/dense DP 9012 次，最大差 {oracle['random']['max_compact_dense_error']:.3g}；guide 9012 次选择序列完全一致、最大值差 {oracle['random']['max_guide_error']:.3g}。",
        f"45 小图、145 次完整搜索，最大 Oracle J 误差 {oracle['small']['max_J_error']:.3g}；组合小图实际进入局部阶段 {oracle['small']['local_phase_calls']['bursts']} 次。",
        '30 次真实 smoke 与 180 次正式实验全部独立重放最终路径、incumbent 历史、局部接受路径和候选档案。',
        f"正式实验：正常完成 {benchmark['completed']} 次、预算中止 {benchmark['budget_exceeded']} 次，认证数 0；J/Pd 最大重放误差均为 {benchmark['max_J_replay_error']:.3g}/{benchmark['max_Pd_replay_error']:.3g}。",
        'work：5000 次全局+局部扩展、30 秒、20000 OPEN；wall：5 秒、20000 OPEN。所有方法用同一冻结 PT；预处理和所有搜索阶段计入方法时间。',
        'DP 备份不是树节点扩展，单独记录备份数和时间。OPEN 计排队候选；pending/held 活动节点另列，进程 RSS 峰值覆盖输入、预处理、搜索、记录与重放。',
        '每场景固定 seed=41、500 粒子；三次是计时重复，不是独立粒子实现或新 forcing。','',
        '## 预先指定的完整组合与直接 STDC','',
        '|场景|预算|直接 STDC J / Pd|组合 J / Pd|直接→组合秒|直接→组合峰值 MiB|',
        '|---|---|---|---|---|---|']
    conclusions=[]
    for scene,label in scene_names.items():
        for protocol in ('work','wall'):
            a=next(x for x in agg if (x['scenario'],x['protocol'],x['variant'])==(scene,protocol,'prior_stdc'))
            b=next(x for x in agg if (x['scenario'],x['protocol'],x['variant'])==(scene,protocol,'adaptive_combo'))
            out.append(f"|{label}|{protocol}|{a['J_median']:.12f} / {a['Pd_T_median']:.9f}|{b['J_median']:.12f} / {b['Pd_T_median']:.9f}|{a['search_wall_s_median']:.3f}→{b['search_wall_s_median']:.3f}|{a['process_peak_memory_mib_median']:.2f}→{b['process_peak_memory_mib_median']:.2f}|")
            comparisons=[]
            for method in sorted({r['variant'] for r in rows} - {'prior_stdc'}):
                pairs=[]
                for r in range(3):
                    base=next(x for x in rows if (x['scenario'],x['protocol'],x['variant'],x['repeat'])==(scene,protocol,'prior_stdc',r))
                    new=next(x for x in rows if (x['scenario'],x['protocol'],x['variant'],x['repeat'])==(scene,protocol,method,r))
                    pairs.append(dict(delta_J=new['J']-base['J'],delta_Pd=new['Pd_T']-base['Pd_T'],
                        time_ratio=new['search_wall_s']/base['search_wall_s'],
                        memory_ratio=new['process_peak_memory_mib']/base['process_peak_memory_mib']))
                comparisons.append(dict(variant=method,median_delta_J=median(x['delta_J'] for x in pairs),
                    median_delta_Pd=median(x['delta_Pd'] for x in pairs),
                    J_wins=sum(x['delta_J'] < -1e-10 for x in pairs),
                    joint_wins=sum(x['delta_J'] < -1e-10 and x['delta_Pd'] > 1e-10 for x in pairs),
                    median_time_ratio=median(x['time_ratio'] for x in pairs),
                    median_memory_ratio=median(x['memory_ratio'] for x in pairs),pairs=pairs))
            conclusions.append(dict(scenario=scene,protocol=protocol,comparisons=comparisons))
    out+=['','## 所有消融结果','',
        '|场景|预算|方法|J 中位数|Pd 中位数|秒|峰值 MiB|扩展数|停止原因|',
        '|---|---|---|---:|---:|---:|---:|---:|---|']
    for a in agg:
        out.append(f"|{scene_names[a['scenario']]}|{a['protocol']}|{a['variant']}|{a['J_median']:.12f}|{a['Pd_T_median']:.9f}|{a['search_wall_s_median']:.3f}|{a['process_peak_memory_mib_median']:.2f}|{a['work_expanded_median']}|{a['stops']}|")
    out+=['','## DP 构建和回退','',
        '|场景|方法|成功构建/运行数|要求管理内存 MiB 中位数|构建秒中位数|DP 中止后仍搜索次数|',
        '|---|---|---:|---:|---:|---:|']
    for scene,label in scene_names.items():
        for variant in ('dense_fallback','compact_dp','adaptive_combo'):
            rs=[r for r in rows if r['scenario']==scene and r['variant']==variant]
            ds=[r['preprocessing']['dp'] for r in rs]
            out.append(f"|{label}|{variant}|{sum(d['status']=='completed' for d in ds)}/{len(ds)}|{median(d['required_peak_managed_bytes'] for d in ds)/2**20:.3f}|{median(d['wall_s'] for d in ds):.3f}|{sum(r['preprocessing'].get('dp_fallback',False) and r['work_expanded']>0 for r in rs)}|")
    out+=['','## 实现与解释边界','',
        '- 可恢复全局 OPEN；局部未用预算回到全局。DP 未完成明确记录并回退 STDC，使用同一剩余 deadline。',
        '- 短窗口保留绝对时刻、固定端点和精确后缀；24 个质量槽加可选 4 个多样性槽。新机会排序只决定尝试次序，不用于安全剪枝。',
        '- 默认局部工作占比上限 10%；未产生改善的已完成窗口触发 2/4 全局片冷却。所有额度和队列同时计费。',
        '- SparseParticleGuide 按实际占据单元计算，并以 4 MiB 距离缓存上限代替无界半径集合缓存；仍执行原 Algorithm 2 的无路径连续性逐步贪心。',
        '- CompactParticleDP 保留 Float64；只压缩起点可达的时空系数及相同未来轨迹后缀，不合并路径信念、不丢特殊 bin 质量。',
        '- 单粒子 DP 与 STDC 没有一般支配关系；速度、内存和 J/Pd 收益必须分开报告。',
        '- J=sum(M_t,t=1..T)，t=0不检测；Pd=1-M_T。最小 J 不保证最大最终 Pd，未加入新的 Pd 约束或改变接受目标。',
        '- 原 paper_greedy 仍只在新方法中排序；paper_baseline 的 completed 不代表已验证动态 epsilon 界。',
        '- 任何 beam/窗口完成、预算中止和本轮真实路线均不标记全局 epsilon 认证。未证明当前最好 J 接近全局最优。',
        '- 所有场景保留 all-water 碰撞近似。Fundy 始终 physical_direction_unverified=true，官方 angle 与地理网格方向的物理矛盾未解决。',
        '- 新增测试曾有 fixture/范围错误（缺 trajectory ID、预算提前完成假设、固定终点误比自由终点、mock 时钟未到期）。失败尝试与独立诊断保留；只修新测试，未修改历史测试、评价器或放宽可采纳性阈值。','',
        '## 保全与文件','',
        f"{preservation['research_files_byte_unchanged']} 份既有研究文件、{preservation['baseline_files']} 份冻结 baseline 文件逐字节不变。",
        '两份当前研究工作区的生成型 pytest 缓存被首次新测试更新，原/新 SHA 已在 transient_cache_incident.json 单列；不声称这两份缓存逐字节保全。后续测试全部禁用 cacheprovider。',
        '评价器、forcing、粒子、B7、Stage 7/8 和旧正式实验文件均在严格保全范围内。未重新运行 OpenDrift、未安装升级依赖。',
        '命令、seed、stdout/stderr、JUnit XML、源 SHA 和 git diff 分别在 source_freeze*、各 stage、new_tests、oracle、full_tests、experiment、smoke、benchmark 下。',
        'CSV：benchmark/metrics.csv、aggregate.csv、paired_comparisons.csv；图：*_paths.png、*_survival_anytime.png、*_efficiency.png、*_paired_deltas.png。',
        '代码清单：code_files.json。来源及模型参数：experiment/protocol.json。','']
    frozen=read(RUN/'freeze.json');pre=read(RUN/'preexisting.json')
    wins=sum(c['J_wins'] for group in conclusions for c in group['comparisons'] if c['variant']!='paper_baseline')
    joint=sum(c['joint_wins'] for group in conclusions for c in group['comparisons'] if c['variant']!='paper_baseline')
    out[4:4]=[f'核心结论：新增方法在 144 次与直接 STDC 的配对中，严格 J 胜出 {wins} 次、J/Pd 同时胜出 {joint} 次。速度或表内存变化不等同于核心指标突破。','']
    rollout=[]
    for r in rows:
        stats=r.get('stats',{});local=stats.get('rollout')
        if local is not None:
            rollout.append(dict(scenario=r['scenario'],protocol=r['protocol'],variant=r['variant'],repeat=r['repeat'],
                global_expanded=stats['global_expanded'],local_expanded=stats['local_expanded'],
                complete_candidates=local['complete_candidates'],local_improvement_events=local['accepted_improvements'],
                global_accepted_local=stats['external_improvements'],bound_calls=local['bound_calls'],
                bound_wall_s=local['bound_wall_s'],windows_completed=local['windows_completed'],
                unqueried_bound_discarded=local['unqueried_bound_discarded']))
    save(RUN/'rollout_efficiency_audit.json',dict(rows=rollout))
    out+=['## 新 rollout 的实际贡献','',
        f"{len(rollout)} 次短窗口运行合计生成 {sum(r['complete_candidates'] for r in rollout)} 个完整候选，局部接受 {sum(r['local_improvement_events'] for r in rollout)} 次 J 改善，向全局注入并改善 {sum(r['global_accepted_local'] for r in rollout)} 次。它们是否超过直接 STDC 以配对表为准。",
        '详细的生成/接受/下界调用/预算分配记录在 rollout_efficiency_audit.json；不把局部相对较弱 seed 的改善当成超过直接 STDC。','',
        '## 环境与复跑','',f"解释器：{frozen['environment']['interpreter']}",'',
        '|包|实际版本|','|---|---|']
    out += [f'|{name}|{version}|' for name,version in frozen['environment']['versions'].items()]
    out += ['','完整命令见各阶段 command.json；单次离线复跑可运行 offline_replay.ps1，例如：','',
        '```powershell',"& .\\offline_replay.ps1 -Scenario bay_of_fundy -Variant fast_stdc -Protocol wall",'```','',
        '脚本在新目录保存结果，复用并再次核验冻结协议、源码与输入；不会覆盖旧结果。完整 180 次调度见 benchmark/schedule.json。','']
    code=[p for p in frozen['source_sha256'] if 'asar_repro/'+p not in pre['protected']]
    save(RUN/'code_files.json',dict(files=[dict(path=p,sha256=frozen['source_sha256'][p]) for p in code]))
    save(RUN/'conclusions.json',dict(status='completed',strict_J_wins=wins,joint_J_Pd_wins=joint,comparisons=conclusions,validation=validation['stages'],
        preservation=preservation,benchmark=benchmark,global_epsilon_certified=False,
        physical_direction_unverified=['bay_of_fundy']))
    (RUN/'final_report.md').write_text('\n'.join(out),encoding='utf-8')
    record={p.relative_to(RUN).as_posix():digest(p) for p in sorted(RUN.rglob('*'))
            if p.is_file() and p.name!='artifact_sha256.json'}
    save(RUN/'artifact_sha256.json',dict(files=record))
    print('report generated',len(record),'artifacts')
if __name__=='__main__':main()

