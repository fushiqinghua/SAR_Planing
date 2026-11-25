# 独立受限精确修复：诊断报告

日期：2026-11-24。目标、评价器、forcing和粒子归档保持不变。使用原直接STDC路径作为已知可行上界，属于额外300秒/场景的改善存在性诊断，不是同预算性能胜出。
固定前缀，终点自由；空间走廊逐阶段扩大。所有dual/gap仅属于当前受限子问题，求解器数值最优不等于全局epsilon认证。
每次构建、求解和内部重放计入诊断时间；输入SHA验收另列。模型缓冲上限512MiB不是进程内存上限，原生求解器另用2GiB RSS监控。

|场景|原J|修复J|原Pd|修复Pd|过程状态|峰值MiB|
|---|---:|---:|---:|---:|---|---:|
|lake_ontario|17.264874448000|17.264874448000|0.897364416|0.897364416|completed, budget_exceeded:max_seconds, budget_exceeded:max_seconds|426.72|
|arctic_ocean|20.386109349120|20.386109349120|0.908583112|0.908583112|completed, budget_exceeded:max_seconds, budget_exceeded:max_seconds|555.08|
|bay_of_fundy|45.881082400000|45.881082400000|0.415864800|0.415864800|completed, budget_exceeded:max_seconds, budget_exceeded:max_seconds|960.59|

严格J改善场景 0/3；J/Pd同时改善 0/3。若无改善，不能据超时或有限走廊推断全局最优；若存在改善，必须与5秒基线性能分开讨论。

## 变化见证

- {'scene': 'lake_ontario', 'changed_steps': [], 'first_divergence': None, 'last_difference': None, 'terminal_changed': False, 'J_improvement': 0.0, 'Pd_change': 0.0}
- {'scene': 'arctic_ocean', 'changed_steps': [], 'first_divergence': None, 'last_difference': None, 'terminal_changed': False, 'J_improvement': 0.0, 'Pd_change': 0.0}
- {'scene': 'bay_of_fundy', 'changed_steps': [], 'first_divergence': None, 'last_difference': None, 'terminal_changed': False, 'J_improvement': 0.0, 'Pd_change': 0.0}

## 验证与文件

新测试：{'tests': 83, 'errors': 0, 'failures': 0, 'skipped': 0}；全量测试：{'tests': 1197, 'errors': 0, 'failures': 0, 'skipped': 0}。
独立Oracle报告：oracle/audit/summary.json；每例保存候选、受限最优值和下界误差。
每阶段JSON包含solver状态、停止原因、受限dual/gap、模型大小、耗时和来源；每场景单独保存命令、stdout/stderr及watchdog记录。
Fundy始终physical_direction_unverified=true；沿用既有all-water碰撞近似，未更换forcing或生成合成替代粒子。
本轮只完成独立修复求解器与诊断，未把新方法接入A^SAR默认搜索，也未开展事件导向大邻域或新的正式同预算比赛。

## 第二轮修复证据

本地SciPy1.17.1内置HiGHS1.12.0（版本见diagnosis原生日志）。只使用已导出的同一12变量/17约束toy模型，6组受控配置独立进程运行；未修改数学目标或输入矩阵。
|原生配置|J|dual|与原DFS一致|
|---|---:|---:|---|
|strict_on|3.149565217391|3.149565217391|False|
|strict_off|3.074434782609|3.074434782609|True|
|default_on|3.074434782609|3.074434782609|True|
|default_off|3.074434782609|3.074434782609|True|
|strict_without_small_value|3.074434782609|3.074434782609|True|
|strict_default_feasibility|3.074434782609|3.074434782609|True|

原组合presolve=true+严格可行性容差+small_matrix_value=1e-12稳定复现错误。仅关闭presolve即恢复正确；取消small_matrix覆盖或恢复默认feasibility也可消除此单例。这里识别的是本地参数/预处理交互，尚未定位原生内部代码根因，不能断言所有HiGHS版本或所有模型都有此问题。
采取保守修复：固定presolve=false，全部严格评分/Oracle门槛和原生精度选项保持不变。新增seed1059在q=.6/.78/1及两种粒子列顺序下的6个永久回归；旧77个测试断言未削弱，审计脚本原样保留。未安装或升级任何依赖。
HiGHS选项含义参考[官方文档](https://ergo-code.github.io/HiGHS/dev/options/definitions/)。本报告的错误复现与修复结果来自本地同矩阵实验，不以外部类似issue作为根因证据。

## 正式测试与保全

新增83 tests、全量1197 tests全部通过，0 failures/errors/skips。48个toy×4设置共192次独立Oracle检查，累计39689条完整路径；最大J误差0，最大原评分重放误差0，最大下界超出8.881784197001252e-16（容差1e-10），违规0。
保全检查通过：5589份原研究文件、654份冻结baseline文件、1493份旧正式实验产物、108份上一轮blocked产物均不变。两份已记录的旧pytest缓存例外没有进一步变化。

## 实际求解与解释边界

|场景|阶段|状态|J|受限下界|受限gap|秒|原生节点|原生候选J|
|---|---|---|---:|---:|---:|---:|---:|---:|
|lake_ontario|late_suffix|completed:|17.264874448000|17.264874448|0.000000000|4.563|5|17.264874448|
|lake_ontario|long_suffix|budget_exceeded:max_seconds|17.264874448000|17.040648486|0.012987408|90.204|2|17.507811332|
|lake_ontario|early_divergence|budget_exceeded:max_seconds|17.264874448000|16.889492376|0.021742531|205.677|102|17.485855561|
|arctic_ocean|late_suffix|completed:|20.386109349120|20.386109349|0.000000000|4.168|3|20.386109349|
|arctic_ocean|long_suffix|budget_exceeded:max_seconds|20.386109349120|20.303543742|0.004050091|90.095|144|20.410334290|
|arctic_ocean|early_divergence|budget_exceeded:max_seconds|20.386109349120|19.758081231|0.030806669|205.880|0|22.679612196|
|bay_of_fundy|late_suffix|completed:|45.881082400000|45.881082400|0.000000000|5.573|3|45.881082400|
|bay_of_fundy|long_suffix|budget_exceeded:max_seconds|45.881082400000|45.453015557|0.009329920|90.101|2|46.251746512|
|bay_of_fundy|early_divergence|budget_exceeded:max_seconds|45.881082400000|45.158984910|0.015738458|204.443|2|46.416231277|

已有STDC路径作为外部可行上界保留；SciPy milp接口未向原生求解器传入该完整向量作为MIP start。因此原生搜索可能只找到更差候选，返回值仍保留已知较优STDC，不将原生较差路径冒充改进。受限gap使用保留的可行上界与该子问题dual计算。
三层邻域固定前缀深度依次T−16、T−28、floor(T/3)，空间走廊半径1/2/3，终点自由；不覆盖更早前缀的所有改动。即使某层正常完成且无改善，也不证明全局近最优。
本轮的300秒诊断带有先前已找到的STDC路径，不能与5秒从共同PT起步的方法做公平耗时比较。未把诊断获得的路径免费提供给后续比赛。所有budget_exceeded/外部中止都在JSON与CSV中单列；数值completed不提升为全局epsilon认证。

## 离线复跑与代码清单

完整命令、seed、环境与stderr在各stage/command.json中；新增修改文件和前后SHA见code_files.json。命令示例（在项目根目录，沿用offline_guard+src+scripts的PYTHONPATH）：
```powershell
& 'C:\Users\35448\.conda\envs\maritime-sar\python.exe' -m pytest -x -q -p no:cacheprovider tests/test_exact_repair.py
& 'C:\Users\35448\.conda\envs\maritime-sar\python.exe' scripts/audit_exact_repair.py --output-dir <新的审计输出目录>
```
真实诊断必须先通过新目录中的验证和输入SHA门控，再运行prepare→smoke→diagnostic；不覆盖本目录的已冻结结果。
下一阶段尚未实施：向求解器注入已知可行向量/其他更强修复机制、事件导向大邻域以及新的正式同墙钟预算对照。原目标仍只最小化J，Pd独立评估；Fundy保留物理方向未验证。
