"""Archive a failed gate without running further search, tests or real data."""
import csv,json,sys
from pathlib import Path
from run_optimization_validation import ROOT,read,save,digest,sources
from run_exact_repair_validation import preserved
from run_anytime_experiments import manifest
RUN=Path(__file__).resolve().parent

def main():
    validation=read(RUN/'validation_summary.json');assert validation['status']=='blocked'
    freeze=read(RUN/'freeze.json');assert sources()==freeze['source_sha256']
    audit=read(RUN/'oracle/audit/summary.json');failed=read(RUN/'oracle/audit/last_checked.json')
    model=failed['result'];oracle=failed['oracle'];gap=model['J']-oracle['J']
    keep=preserved();keep['current_frozen_source_unchanged']=True
    save(RUN/'final_preservation.json',keep)
    files=['src/asar_repro/exact_repair.py','tests/test_exact_repair.py','scripts/audit_exact_repair.py',
        'scripts/run_exact_repair_validation.py','scripts/run_exact_repair_experiments.py','docs/stdc_exact_repair.md']
    save(RUN/'code_files.json',dict(files=[dict(path=p,sha256=digest(ROOT/p)) for p in files],
        status='blocked_unvalidated_do_not_use_for_real_search',existing_source_files_modified=0))
    records=[dict(kind='MILP_returned',J=model['J'],Pd=model['Pd'],path=model['path']),
        dict(kind='MILP_solver_candidate',J=model['stats']['candidate_J'],Pd=model['stats']['candidate_Pd'],path=model['stats']['candidate_path']),
        dict(kind='independent_DFS_witness',J=oracle['J'],Pd=0.7325217391304348,path=oracle['path'])]
    with (RUN/'counterexample.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['kind','J','Pd','path']);writer.writeheader()
        for r in records:writer.writerow(dict(r,path=json.dumps(r['path'])))
    save(RUN/'blocked.json',dict(status='blocked',blocking_stage='oracle',seed=failed['seed'],
        prefix_depth=failed['prefix_depth'],corridor_radius=failed['corridor_radius'],
        oracle_J=oracle['J'],solver_claimed_J=model['J'],false_lower_bound=model['restricted_lower_bound'],
        objective_and_bound_error=gap,new_pytest_passed=77,oracle_checks_passed=audit['completed_repairs'],
        failed_check_index=audit['completed_repairs']+1,planned_oracle_checks=192,
        full_tests_run=False,real_runs=0,source_frozen=True,global_epsilon_certified=False,
        reason='strict objective and admissibility gate failed; do not continue to real archives',
        user_gate='若任何历史测试或可采纳性断言失败，立即停止，记录 blocked，不得绕过',
        readonly_followup='only replayed existing routes and inspected their feasibility in frozen generated constraints; optimizer_calls=0',
        cause_confirmed='known feasible lower-J model vector contradicts backend-reported restricted optimum and dual',
        cause_unresolved='specific model transfer/native presolve/backend fault not yet established',
        physical_direction_unverified_for_future_fundy=True))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axs=plt.subplots(1,2,figsize=(10,4.6),constrained_layout=True)
    for ax,record in zip(axs,(records[1],records[2])):
        path=record['path'];rr=[v//3 for v in path];cc=[v%3 for v in path]
        ax.plot(cc,rr,color='#2f69ad',lw=2,marker='o');ax.plot(cc[-2:],rr[-2:],color='#d26227',lw=4)
        for v in range(9):ax.text(v%3+.12,v//3+.12,str(v),fontsize=10)
        ax.scatter([2],[1],marker='*',s=220,c='#c64032',zorder=5,label='Detectable target at t=7')
        ax.set(xlim=(-.4,2.6),ylim=(2.6,-.4),xticks=range(3),yticks=range(3),aspect='equal',
            title=record['kind']+'\nJ='+format(record['J'],'.12f'));ax.grid(alpha=.3);ax.legend(fontsize=7)
    fig.suptitle('BLOCKED toy counterexample: seed 1059 / final move differs / NOT real data')
    fig.savefig(RUN/'counterexample.png',dpi=160);plt.close(fig)
    lines=['# 独立受限精确修复：blocked','',
        '日期：2026-11-24。正式独立Oracle验证失败。本轮未通过验收，不得接入默认规划器或真实归档实验。',
        '原目标、评价器、forcing、旧正式结果和baseline未修改；新增求解器及测试作为未验收研究代码保留。','',
        '## 已实现但未通过最终验收','',
        '固定前缀、自由终点的时空MILP；共享四连通路线、未来同轨迹后验分组、事件跨度计费、特殊质量保留。仅原评分器重放后严格J改善可替换incumbent。',
        '原生HiGHS严格数值选项、threads=1、random_seed=0和透传warning有记录。开发阶段修复了零/正节点预算状态映射，并增加长时域回归；没有放宽历史或Oracle断言。','',
        '## 正式门槛结果','',
        '|阶段|状态|结果|','|---|---|---|',
        '|新增pytest|passed|77 passed，0 failures/errors/skips|',
        '|独立随机Oracle|blocked|计划192次；前74次通过，第75次失败|',
        '|全量历史测试|未运行|按失败门槛停止|',
        '|真实输入门控与三个场景诊断|未运行|不能绕过Oracle失败|','',
        '## 固化反例','',
        'seed=1059，3×3，T=7，4粒子，prefix_depth=3，corridor_radius=0，q为空间非均匀数组。允许空间为{1,2,5,7,8}，终点自由。',
        f"求解器返回completed/optimal，J={model['J']:.16f}，restricted_lower_bound同值、gap=0。独立DFS已有合法路线J={oracle['J']:.16f}，差{gap:.16f}，远超1e-10门槛。",
        '|路线|J|Pd|','|---|---:|---:|']
    for r in records:lines.append(f"|{r['kind']}|{r['J']:.16f}|{r['Pd']:.16f}|")
    lines+=['',
        '原生候选：[4,5,2,1,2,5,2,1]；Oracle见证：[4,5,2,1,2,5,2,5]。两者只差最后一步，去cell5可再检测一次。公开返回路径保留原incumbent，因为原生候选与它J相同。',
        '失败后仅做只读复核：重放三条已存路线；截获冻结构建器的A/c/b（mock optimizer，求解次数0）并为已存Oracle路线构造12维变量向量。行约束、变量边界、整数残差均0；模型目标与原评分均为3.0744347826086957。',
        '唯一可检测组β=36/115，事件t5/t7在cell5、q=.6，offset=319/115；更优赋值r5=.4、r7=.16、z7=.4，精确计入原J。该见证说明不是走廊定义不同、评分口径不同或普通舍入误差。',
        '目前只能将问题范围缩到实际求解调用/矩阵传递/原生预处理链路。日志presolve=true且0 MIP节点即报optimal，尚不能直接断言是HiGHS自身bug。','',
        '## 后续必要工作（本轮未实施）','',
        '1. 将此反例升级为永久回归；导出实际模型及原生详细日志。',
        '2. 在独立修复轮中只针对该模型比较presolve开关及严格选项组合，区分后端、接口和构建问题；不得升级依赖或关闭验收来掩盖。',
        '3. 修复后重跑新增测试、全部192次独立Oracle、全量历史测试；全部通过才允许真实归档SHA验收与300秒受限诊断。',
        '4. 受限子问题状态和dual不作为全局epsilon证书；Fundy仍须physical_direction_unverified=true。','',
        '## 命令与产物','',
        '从asar_repro目录、使用原offline_guard和PYTHONPATH环境运行；完整环境在各阶段command.json。',
        '```powershell',
        "& 'C:\\Users\\35448\\.conda\\envs\\maritime-sar\\python.exe' -m pytest -x -q -p no:cacheprovider tests/test_exact_repair.py",
        "& 'C:\\Users\\35448\\.conda\\envs\\maritime-sar\\python.exe' scripts/audit_exact_repair.py --output-dir <新审计目录>",
        '```','',
        '新增文件清单及SHA：code_files.json。失败输入、原生返回与Oracle路径：oracle/audit/input_1059.json、last_checked.json。原始stdout/stderr/XML/git diff全部保留。',
        '完整模型向量只读检查：failure_readonly/solver_vector_check.json。路线重放：development/failure_readonly/saved_route_replay.json。',
        '可视化：counterexample.png；CSV：counterexample.csv；机器状态：blocked.json、validation_summary.json。',
        f"最终保全：{keep.get('research_files_byte_unchanged')}份既有研究文件、{keep.get('baseline_files')}份冻结baseline文件、上一轮{keep.get('adaptive_20261124_artifacts')}份实验产物保持不变；之前已记录的两份pytest缓存例外没有新变化。",
        '本轮的完成状态是blocked，不是正式完成。没有真实场景J/Pd提升可报告。']
    (RUN/'final_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    manifest(RUN);print('blocked archived; full_tests=not_run, real_runs=0',flush=True)

if __name__=='__main__':main()
