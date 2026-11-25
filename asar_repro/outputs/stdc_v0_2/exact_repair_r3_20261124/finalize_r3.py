"""Freeze the R3 evidence and record exact changed files without touching R2."""
from pathlib import Path
from run_optimization_validation import ROOT,read,save,digest,sources,require,snapshot
from run_exact_repair_validation import preserved
from run_anytime_experiments import manifest

run=Path(__file__).resolve().parent
require(read(run/'validation_summary.json')['status']=='passed','validation blocked')
require(read(run/'diagnostic/summary.json')['status']=='passed','real diagnostic blocked')
require(sources()==read(run/'freeze.json')['source_sha256'],'source changed')
keep=preserved();save(run/'final_preservation.json',keep)
before=read(run/'source_before/manifest.json')['files']
added=['src/asar_repro/highs_start.py','scripts/audit_exact_repair_warm.py','scripts/run_warm_repair_experiments.py']
changed=[dict(path=n,before_sha256=sha,after_sha256=digest(ROOT/n))
         for n,sha in before.items() if digest(ROOT/n)!=sha]
save(run/'code_files.json',dict(modified_files=changed,added_files=[dict(path=n,sha256=digest(ROOT/n)) for n in added],
    unchanged_reference_auditor=digest(ROOT/'scripts/audit_exact_repair.py'),
    original_objective_scorer_forcing_unchanged=True,dependencies_changed=False))
out=run/'final_diff';out.mkdir(exist_ok=False);snapshot(out,run)
s=read(run/'round_summary.json');v=read(run/'validation_summary.json')
s.update(new_tests=v['stages']['new_tests']['test_counts'],full_tests=v['stages']['full_tests']['test_counts'],
         cold_oracle=v['stages']['oracle']['audit'],warm_oracle=v['stages']['warm_oracle']['audit'],
         preservation=keep,dependencies_changed=False,original_objective_scorer_forcing_unchanged=True)
save(run/'round_summary.json',s)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
scenes=['lake_ontario','arctic_ocean','bay_of_fundy']
fig,axs=plt.subplots(1,2,figsize=(12,4.5),constrained_layout=True)
for k,variant in enumerate(('cold_reference','warm_cutoff')):
    records={r['scene']:r for r in s['comparison'] if r['variant']==variant}
    for ax,key,label in zip(axs,('elapsed_s','peak_mib'),('Extra diagnostic seconds','Peak process memory (MiB)')):
        bars=ax.bar(np.arange(3)+(k-.5)*.36,[records[a][key] for a in scenes],width=.36,label=variant)
        ax.bar_label(bars,fmt='%.1f',fontsize=8)
        ax.set_xticks(np.arange(3),['Lake Ontario','Hudsons Bay','Fundy*'])
        ax.set_ylabel(label);ax.legend(fontsize=8)
fig.suptitle('One run per method / scene; *Fundy physical direction unverified')
fig.savefig(run/'diagnostic/efficiency.png',dpi=160);plt.close(fig)
warnings=[]
for stage in ('new_tests','oracle','warm_oracle','full_tests'):
    path=run/stage/'stderr.txt'
    if path.exists() and path.read_text(encoding='utf-8').strip():warnings.append(stage)
report=run/'final_report.md'
with report.open('a',encoding='utf-8') as f:
    f.write('\n## 本轮结论与归因边界\n\n')
    f.write(f"热启动+上界相对直接STDC的严格J改善场景数为{s['strict_J_improved_scenes']}/3，J/Pd同时改善为{s['joint_improved_scenes']}/3。\n")
    f.write('热启动提交/读回成功说明原生求解器获得了原STDC可行解，不等于产生了新路线。预算停止仍不能证明全局近最优。\n')
    for scene in scenes:
        cold=next(r for r in s['comparison'] if r['scene']==scene and r['variant']=='cold_reference')
        warm=next(r for r in s['comparison'] if r['scene']==scene and r['variant']=='warm_cutoff')
        f.write(f"- {scene}: 热组减冷组 J={warm['J']-cold['J']:.12f}, Pd={warm['Pd']-cold['Pd']:.12f}, 峰值内存={warm['peak_mib']-cold['peak_mib']:.2f} MiB。\n")
    f.write('真实场景只比较两项修改的组合，尚未分别消融warm-only与cutoff-only；不能把运行时间/内存差异单独归因于某项。\n')
    f.write('模型层面的待验证假设：已知可行上界不会提高根LP的最小值（该最小值本就不大于已知可行J）；显式目标行可能重复原生incumbent剪枝并增加LP负担。这里不是已确认的性能根因，需独立消融才能判断。\n')
    f.write('本轮不将新组合设为默认算法。尚未进行真实warm-only消融、跨更早前缀的邻域探索、多次重复或全局最优性验证。数据/协议seed=41，原生HiGHS random_seed=0，线程数=1。\n')
    f.write('\n## 文件与复跑\n\n')
    f.write('修改/新增文件前后SHA见code_files.json，完整git diff见final_diff；各阶段command.json记录实际解释器、环境与命令。\n')
    f.write('新模块测试：114；全量测试：1228；冷Oracle192组、热启动/上界Oracle576组。详情以实际stage.json为准。\n')
    f.write('非空测试stderr阶段：'+str(warnings)+'。new_tests中pyreadline3退出析构的Windows句柄告警已保留，进程exit=0且pytest无失败/跳过；未屏蔽stderr。\n')
    f.write('保全检查：'+str(keep)+'\n')
    f.write('原可执行环境：C:\\Users\\35448\\.conda\\envs\\maritime-sar\\python.exe。离线PYTHONPATH= scripts/offline_guard;src;scripts，ASAR_OFFLINE=1，PROJ_NETWORK=OFF，PYTHONDONTWRITEBYTECODE=1，各线程变量=1。\n')
    f.write('```powershell\npython -m pytest -x -q -p no:cacheprovider tests/test_exact_repair.py\npython -m pytest -x -q -p no:cacheprovider tests\npython scripts/audit_exact_repair.py --output-dir <新的冷审计目录>\npython scripts/audit_exact_repair_warm.py --output-dir <新的热审计目录>\n```\n')
    f.write('真实复跑须在新run-dir按preflight→freeze→new_tests→oracle→warm_oracle→full_tests顺序通过，然后run_warm_repair_experiments.py prepare→smoke→diagnostic→report；每个命令均传同一新run-dir。禁止覆盖本轮或旧目录。\n')
manifest(run)
print('finalized R3',flush=True)
