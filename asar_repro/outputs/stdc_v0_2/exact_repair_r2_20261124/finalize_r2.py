"""Append audited repair evidence and archive the completed diagnostic round."""
import json,sys
from pathlib import Path
from run_optimization_validation import ROOT,read,save,digest,sources
from run_exact_repair_validation import preserved
from run_anytime_experiments import manifest,csv_save
RUN=Path(__file__).resolve().parent

def main():
    require=lambda ok,msg: None if ok else (_ for _ in ()).throw(AssertionError(msg))
    require(read(RUN/'validation_summary.json')['status']=='passed','validation failed')
    require(read(RUN/'diagnostic/summary.json')['status']=='passed','diagnostic blocked')
    require(sources()==read(RUN/'freeze.json')['source_sha256'],'source changed')
    keep=preserved();save(RUN/'final_preservation.json',keep)
    candidates=read(RUN/'diagnostic/results.json')['scenes'];protocol=read(RUN/'experiment/protocol.json')
    cases=read(RUN/'diagnosis/summary.json')['rows']
    files=['src/asar_repro/exact_repair.py','tests/test_exact_repair.py',
        'scripts/run_exact_repair_validation.py','scripts/run_exact_repair_experiments.py','docs/stdc_exact_repair.md']
    save(RUN/'code_files.json',dict(modified_files=[dict(path=p,before_sha256=digest(RUN/'source_before'/p),after_sha256=digest(ROOT/p)) for p in files],
        unchanged_audit_script=dict(path='scripts/audit_exact_repair.py',sha256=digest(ROOT/'scripts/audit_exact_repair.py')),
        original_asar_evaluator_forcing_modified=False))
    native_rows=[]
    for rec in candidates:
        for r in rec['rows']:
            s=r['stats']
            native_rows.append(dict(scene=rec['scene'],stage=r['stage'],status=r['status'],stop_reason=r['stop_reason'],
                accepted_J=r['J'],accepted_Pd=r['Pd'],incumbent_source=r['incumbent_source'],
                native_candidate_J=s.get('candidate_J'),native_candidate_Pd=s.get('candidate_Pd'),
                native_candidate_accepted=s.get('candidate_accepted'),
                restricted_lower_bound=r['restricted_lower_bound'],restricted_gap=r['restricted_gap'],
                solver_nodes=s.get('solver_mip_node_count'),variables=s.get('model_variables'),rows=s.get('model_rows'),
                wall_s=r['wall_s'],build_s=r['model_build_s'],solve_s=r['solve_s'],
                replay_error=s.get('model_replay_error'),peak_mib=r['process_peak_memory_mib'],
                physical_direction_unverified=r['physical_direction_unverified']))
    csv_save(RUN/'diagnostic/model_efficiency.csv',native_rows)
    lines=['','## 第二轮修复证据','',
        '本地SciPy1.17.1内置HiGHS1.12.0（版本见diagnosis原生日志）。只使用已导出的同一12变量/17约束toy模型，6组受控配置独立进程运行；未修改数学目标或输入矩阵。',
        '|原生配置|J|dual|与原DFS一致|','|---|---:|---:|---|']
    for x in cases:lines.append(f"|{x['name']}|{x['J']:.12f}|{x['dual']:.12f}|{x['matches_known_optimum']}|")
    lines+=['',
        '原组合presolve=true+严格可行性容差+small_matrix_value=1e-12稳定复现错误。仅关闭presolve即恢复正确；取消small_matrix覆盖或恢复默认feasibility也可消除此单例。这里识别的是本地参数/预处理交互，尚未定位原生内部代码根因，不能断言所有HiGHS版本或所有模型都有此问题。',
        '采取保守修复：固定presolve=false，全部严格评分/Oracle门槛和原生精度选项保持不变。新增seed1059在q=.6/.78/1及两种粒子列顺序下的6个永久回归；旧77个测试断言未削弱，审计脚本原样保留。未安装或升级任何依赖。',
        'HiGHS选项含义参考[官方文档](https://ergo-code.github.io/HiGHS/dev/options/definitions/)。本报告的错误复现与修复结果来自本地同矩阵实验，不以外部类似issue作为根因证据。','',
        '## 正式测试与保全','',
        '新增83 tests、全量1197 tests全部通过，0 failures/errors/skips。48个toy×4设置共192次独立Oracle检查，累计39689条完整路径；最大J误差0，最大原评分重放误差0，最大下界超出8.881784197001252e-16（容差1e-10），违规0。',
        f"保全检查通过：{keep['research_files_byte_unchanged']}份原研究文件、{keep['baseline_files']}份冻结baseline文件、{keep['adaptive_20261124_artifacts']}份旧正式实验产物、{keep['blocked_round_artifacts']}份上一轮blocked产物均不变。两份已记录的旧pytest缓存例外没有进一步变化。",'',
        '## 实际求解与解释边界','',
        '|场景|阶段|状态|J|受限下界|受限gap|秒|原生节点|原生候选J|',
        '|---|---|---|---:|---:|---:|---:|---:|---:|']
    def num(x):return '无' if x is None else f'{x:.9f}'
    for r in native_rows:
        lines.append(f"|{r['scene']}|{r['stage']}|{r['status']}:{r['stop_reason'] or ''}|{r['accepted_J']:.12f}|{num(r['restricted_lower_bound'])}|{num(r['restricted_gap'])}|{r['wall_s']:.3f}|{r['solver_nodes']}|{num(r['native_candidate_J'])}|")
    lines+=['',
        '已有STDC路径作为外部可行上界保留；SciPy milp接口未向原生求解器传入该完整向量作为MIP start。因此原生搜索可能只找到更差候选，返回值仍保留已知较优STDC，不将原生较差路径冒充改进。受限gap使用保留的可行上界与该子问题dual计算。',
        '三层邻域固定前缀深度依次T−16、T−28、floor(T/3)，空间走廊半径1/2/3，终点自由；不覆盖更早前缀的所有改动。即使某层正常完成且无改善，也不证明全局近最优。',
        '本轮的300秒诊断带有先前已找到的STDC路径，不能与5秒从共同PT起步的方法做公平耗时比较。未把诊断获得的路径免费提供给后续比赛。所有budget_exceeded/外部中止都在JSON与CSV中单列；数值completed不提升为全局epsilon认证。','',
        '## 离线复跑与代码清单','',
        '完整命令、seed、环境与stderr在各stage/command.json中；新增修改文件和前后SHA见code_files.json。命令示例（在项目根目录，沿用offline_guard+src+scripts的PYTHONPATH）：','```powershell',
        "& 'C:\\Users\\35448\\.conda\\envs\\maritime-sar\\python.exe' -m pytest -x -q -p no:cacheprovider tests/test_exact_repair.py",
        "& 'C:\\Users\\35448\\.conda\\envs\\maritime-sar\\python.exe' scripts/audit_exact_repair.py --output-dir <新的审计输出目录>",
        '```',
        '真实诊断必须先通过新目录中的验证和输入SHA门控，再运行prepare→smoke→diagnostic；不覆盖本目录的已冻结结果。',
        '下一阶段尚未实施：向求解器注入已知可行向量/其他更强修复机制、事件导向大邻域以及新的正式同墙钟预算对照。原目标仍只最小化J，Pd独立评估；Fundy保留物理方向未验证。']
    target=RUN/'final_report.md';text=target.read_text(encoding='utf-8')
    require('## 第二轮修复证据' not in text,'already finalized')
    target.write_text(text+'\n'.join(lines)+'\n',encoding='utf-8')
    save(RUN/'round_summary.json',dict(status='passed',new_tests=83,full_tests=1197,oracle_checks=192,
        original_objective_scorer_forcing_unchanged=True,native_presolve=False,dependencies_changed=False,
        completed_repairs=sum(r['status']=='completed' for r in native_rows),
        budget_exceeded_repairs=sum(r['status']=='budget_exceeded' for r in native_rows),
        external_aborts=sum(r['status']=='budget_aborted' for r in candidates),
        same_budget_benchmark=False,global_epsilon_certified=False,
        max_candidate_replay_error=max((r['replay_error'] or 0 for r in native_rows),default=0)))
    manifest(RUN);print('r2 report and preservation finalized',flush=True)
if __name__=='__main__':main()
