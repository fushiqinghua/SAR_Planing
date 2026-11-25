# STDC 可行解热启动与目标上界：第三轮验证

日期：2026-11-24。原目标、评价器、forcing和粒子归档不变；真实输入SHA门控通过。
完整位置/残余质量/乘积辅助变量经原评分与所有线性约束检查后传入本地HiGHS setSolution，并从原生对象读回逐项核对。
增加 c·x ≤ J_incumbent−offset 的向外舍入上界，始终保留已知可行解；presolve=false及严格容差保持。
接口依据[HiGHS官方示例](https://ergo-code.github.io/HiGHS/stable/interfaces/python/example-py/)；本地使用SciPy内置私有绑定，未安装或升级依赖。
冷启动与热启动+上界各300秒/场景，均从同一先前STDC路径出发；三场景交错顺序，单次确定性seed41。不能作为与从头运行STDC同预算的胜出或统计显著性结论。

|场景|方法|J|Pd|额外秒|峰值MiB|完成/预算停止|
|---|---|---:|---:|---:|---:|---|
|lake_ontario|cold_reference|17.264874448000|0.897364416|300.447|428.11|1/2|
|lake_ontario|warm_cutoff|17.264874448000|0.897364416|300.039|475.54|1/2|
|arctic_ocean|warm_cutoff|20.386109349120|0.908583112|300.132|738.75|1/2|
|arctic_ocean|cold_reference|20.386109349120|0.908583112|300.134|553.94|1/2|
|bay_of_fundy|cold_reference|45.881082400000|0.415864800|300.122|961.30|1/2|
|bay_of_fundy|warm_cutoff|45.881082400000|0.415864800|300.642|989.93|1/2|

## 验证

- new_tests: {'tests': 114, 'errors': 0, 'failures': 0, 'skipped': 0}
- oracle: {'status': 'passed', 'synthetic_cases': 48, 'repair_checks': 192, 'complete_path_evaluations': 39689, 'max_objective_error': 0.0, 'max_replay_error': 0.0, 'max_bound_overestimate': 8.881784197001252e-16, 'violations': 0, 'theory_certified': False, 'wall_s': 5.481696499977261, 'source_preserved': True}
- warm_oracle: {'status': 'passed', 'repair_checks': 576, 'synthetic_cases': 48, 'complete_path_evaluations': 39689, 'max_objective_error': 0.0, 'max_replay_error': 0.0, 'max_bound_overestimate': 8.881784197001252e-16, 'violations': 0, 'wall_s': 7.350648200022988, 'global_epsilon_certified': False}
- full_tests: {'tests': 1228, 'errors': 0, 'failures': 0, 'skipped': 0}

## 假设与局限

固定历史粒子、4连通无等待、t0不探测、保留特殊格质量；固定前缀及空间走廊，终点自由。原目标仅最小化J，Pd独立评价，不改变为多目标。
Fundy physical_direction_unverified=true；沿用既有all-water近似。所有dual/gap仅是受限子问题数值估计；completed不等于全局epsilon认证，超时不证明无改善。
SciPy私有绑定存在版本兼容风险：接口/选项/热启动拒绝均blocked，不静默冷回退。模型缓冲512MiB与原生进程2GiB限制分别记录。
完整命令、seed、stdout/stderr、阶段JSON及git diff在每个阶段目录。旧baseline、旧结果与R2产物保全见final_preservation.json。

## 下一阶段尚未实施

未接入A^SAR默认搜索，未改变前缀/走廊策略，未开展多次重复或从头运行的同预算算法比赛，未添加最优性声明。

## 本轮结论与归因边界

热启动+上界相对直接STDC的严格J改善场景数为0/3，J/Pd同时改善为0/3。
热启动提交/读回成功说明原生求解器获得了原STDC可行解，不等于产生了新路线。预算停止仍不能证明全局近最优。
- lake_ontario: 热组减冷组 J=0.000000000000, Pd=0.000000000000, 峰值内存=47.43 MiB。
- arctic_ocean: 热组减冷组 J=0.000000000000, Pd=0.000000000000, 峰值内存=184.81 MiB。
- bay_of_fundy: 热组减冷组 J=0.000000000000, Pd=0.000000000000, 峰值内存=28.63 MiB。
真实场景只比较两项修改的组合，尚未分别消融warm-only与cutoff-only；不能把运行时间/内存差异单独归因于某项。
模型层面的待验证假设：已知可行上界不会提高根LP的最小值（该最小值本就不大于已知可行J）；显式目标行可能重复原生incumbent剪枝并增加LP负担。这里不是已确认的性能根因，需独立消融才能判断。
本轮不将新组合设为默认算法。尚未进行真实warm-only消融、跨更早前缀的邻域探索、多次重复或全局最优性验证。数据/协议seed=41，原生HiGHS random_seed=0，线程数=1。

## 文件与复跑

修改/新增文件前后SHA见code_files.json，完整git diff见final_diff；各阶段command.json记录实际解释器、环境与命令。
新模块测试：114；全量测试：1228；冷Oracle192组、热启动/上界Oracle576组。详情以实际stage.json为准。
非空测试stderr阶段：['new_tests']。new_tests中pyreadline3退出析构的Windows句柄告警已保留，进程exit=0且pytest无失败/跳过；未屏蔽stderr。
保全检查：{'status': 'passed', 'research_files_byte_unchanged': 5589, 'generated_pytest_cache_changes': 2, 'cache_incident_sha256': 'ffe4804132a7bbbf6e98a3a27d72149b0597e6c89702f8ede165593bdf76ef5d', 'baseline_files': 654, 'adaptive_20261124_artifacts': 1493, 'rollout_limit_diagnosis_20261124_artifacts': 43, 'existing_source_files': 154, 'blocked_round_artifacts': 108, 'r2_artifacts': 221}
原可执行环境：C:\Users\35448\.conda\envs\maritime-sar\python.exe。离线PYTHONPATH= scripts/offline_guard;src;scripts，ASAR_OFFLINE=1，PROJ_NETWORK=OFF，PYTHONDONTWRITEBYTECODE=1，各线程变量=1。
```powershell
python -m pytest -x -q -p no:cacheprovider tests/test_exact_repair.py
python -m pytest -x -q -p no:cacheprovider tests
python scripts/audit_exact_repair.py --output-dir <新的冷审计目录>
python scripts/audit_exact_repair_warm.py --output-dir <新的热审计目录>
```
真实复跑须在新run-dir按preflight→freeze→new_tests→oracle→warm_oracle→full_tests顺序通过，然后run_warm_repair_experiments.py prepare→smoke→diagnostic→report；每个命令均传同一新run-dir。禁止覆盖本轮或旧目录。
