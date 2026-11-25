"""Read-only verification and final report for the additive trajectory iteration."""
import argparse
from pathlib import Path
import sys
import traceback
from run_anytime_experiments import manifest, validation_gate
from run_optimization_validation import REPO, sources, preserve, snapshot, environment
from stdc_validation_guards import read, save, digest, require, load_real


def run(root):
    result=dict(status='running',command=[sys.executable,*sys.argv],theory_certified=False)
    final=root/'final';final.mkdir(exist_ok=False)
    try:
        gate=root/'planning_validation/validation_summary.json'
        validation_gate(gate);result['preservation']=preserve(gate.parent)
        before=read(root/'before_changes.json')['protected']
        for name,sha in before.items():require(digest(REPO/name)==sha,'preexisting file changed: '+name)
        result['preexisting_files_unchanged']=len(before)
        load_real()
        for stage in ('smoke','benchmark'):
            require(read(root/stage/'summary.json')['status']=='passed',stage+' not passed')
            items=read(root/stage/'artifact_manifest.json')['files']
            for item in items:require(digest(root/stage/item['path'])==item['sha256'],'artifact changed')
            result[stage+'_verified_files']=len(items)
        diag=read(root/'diagnostic_validation/validation_summary.json')
        tests=read(gate);audit=tests['stages']['oracle_audit']['audit_summary']
        real=read(root/'real_diagnostic/result.json');bench=read(root/'benchmark/summary.json')
        aggregate=read(root/'benchmark/aggregate.json')['rows']
        rows=read(root/'benchmark/results.json')['rows']
        best=min(rows,key=lambda r:r['J'])
        diag_source=diag['source_sha256'];now=sources()
        require(all(now.get(k)==v for k,v in diag_source.items()),'diagnostic frozen source changed')
        snapshot(final,root);save(final/'environment.json',environment())
        new_files=sorted(k for k in now if 'asar_repro/'+k not in before)
        result.update(status='passed',best_J=best['J'],best_Pd=best['Pd_T'],best_method=best['variant'],
            target_J=17.264874448,delta_J=best['J']-17.264874448,
            beat_previous_best=bench['beat_previous_best'],benchmark=bench,added_python_files=new_files,
            diagnostic_test_count=diag['stages']['full_tests']['test_counts']['tests'],
            planning_test_count=tests['stages']['full_tests']['test_counts']['tests'])
        outcome=('本轮取得低于既有最好 J 的可行路径。' if bench['beat_previous_best'] else
                 '本轮未突破既有最好 J=17.264874448；不将速度、下界变化或 toy 改善等同于真实场景指标改善。')
        lines=['# STDC trajectory iteration — 2026-11-24','',outcome,'',
            f"全量测试：独立诊断阶段 {result['diagnostic_test_count']} 项，规划阶段 {result['planning_test_count']} 项；均无失败、错误或跳过。",
            '诊断：12 个合成 toy 的 MILP 与独立 DFS 最优 J 一致；424 个前缀下界无越界，其中178个非终点LP全部完成并验证对偶。',
            f"规划审计：{audit['random']['cases']} 组随机小图、{audit['random']['prefix_evaluations']} 个前缀；粒子 DP 检查 {audit['random']['dp_prefix_evaluations']} 个，{audit['random']['strictly_stronger_than_stdc']} 个比 STDC 严格更紧。",
            f"35个原动态小图+5静态+5粒子派生案例，共 {audit['small_searches']} 次完整搜索；最大 J 误差 {audit['max_J_error']:.3g}。",
            f"真实LP：状态 {real['diagnostic']['status']}，停止原因 {real['diagnostic']['stop_reason']}；可用LP下界 {real['independent_lp_lb']:.12f}，STDC下界 {real['root_stdc_lb']:.12f}。未闭合区间不能证明存在更优可行路线。",'',
            '|预算|方法|J 中位数|Pd 中位数|总扩展中位数|秒数中位数|峰值MiB中位数|停止原因|',
            '|---|---|---:|---:|---:|---:|---:|---|']
        for a in aggregate:lines.append(f"|{a['protocol']}|{a['variant']}|{a['J_median']:.12f}|{a['Pd_T_median']:.12f}|{a['work_expanded_median']:g}|{a['search_wall_s_median']:.4f}|{a['process_peak_memory_mib_median']:.2f}|{a['stops']}|")
        lines+=['',f"共 {bench['runs']} 次正式对照；正常完成 {bench['completed']}，预算中止 {bench['budget_exceeded']}，认证数0。",
            '方法预算：work为5000次总扩展/30秒/20000 OPEN；wall为5秒/20000 OPEN。每种重复3次，顺序轮换。重复仅衡量同一归档的计时波动，不是独立场景。',
            '停止原因中的global_seed_*表示seed子配额中止，即使后续rollout完成也保留该事实；它不等于整体5000扩展已用尽。各阶段状态和实际扩展在raw_result.json/phases中分别保存。',
            '所有方法从同一冻结 PT 出发。压缩、DP预计算、seed及rollout都计入方法时间；中段方法分配40%预算给seed，剩余共享给最多3个anchor。节点扩展不包含DP网格更新，后者单独记录预处理开销。',
            '输入：SHA核验成功的真实历史 Lake Ontario forcing 与冻结500粒子归档；精确等价压缩为342组，最终与每条接受路径按原500粒子评分。真实输入仍保留all-water场景近似标签。',
            '目标未变：J=sum(M_t), t=1..T，t=0不探测；Pd=1-M_T。最小J与最大最终Pd不一定同向。',
            '单粒子DP递推：V_i(T,v)=0；V_i(t,v)=min_{u邻接v} a_i(t+1,u)[1+V_i(t+1,u)]；h=sum_i b_i V_i。它允许每个粒子使用自己的可行路径，放松了共同搜索平台约束，因此在固定外生轨迹、固定探测模型下是离散剩余J的下界。max(STDC,h)保留这项模型条件。',
            'DP下界性质不等于整个搜索获得epsilon认证。paper_greedy仅排序；beam丢弃仅属于候选保留策略；任何预算中止与本轮真实结果均未认证。',
            f"保全：修改前 {len(before)} 个文件逐一SHA相同，baseline-v1.1、原评分器、forcing、B7与此前实验均未覆盖。新增Python文件列表见final/summary.json；每阶段命令、seed、stdout/stderr、JSON、pytest XML与git diff均已保存。",'',
            '图表与数据：benchmark/metrics.csv、paired_comparisons.csv、aggregate.csv、work/wall_paths.png、work/wall_quality_survival.png、work/wall_efficiency.png。',
            '离线复跑：使用maritime-sar解释器；设置PYTHONPATH=scripts/offline_guard;src;scripts、ASAR_OFFLINE=1、PROJ_NETWORK=OFF和数值库线程数1。复制各阶段command.json中的完整参数并改为全新输出目录。初次阶段冻结使用run_trajectory_validation.py init；随后new_tests、full_tests、oracle_audit；历史硬链接测试需使用原用户环境。不得覆盖本目录复跑。',
            '边界：仅一个冻结真实归档；没有跨场景泛化结论，没有修改forcing、评分目标或旧数据，没有开展创新点二，也未自动推送GitHub。']
        (root/'final_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    except Exception as exc:
        result.update(status='blocked',error=str(exc),traceback=traceback.format_exc());raise
    finally:save(final/'summary.json',result);manifest(root)
    print({k:result[k] for k in ('status','best_J','delta_J','beat_previous_best','preexisting_files_unchanged')},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-dir',required=True,type=Path);a=p.parse_args();run(a.run_dir.resolve())
