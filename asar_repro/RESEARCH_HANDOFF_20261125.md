# STDC 研究交接：改进设计、实验证据与下一步分析

整理日期：2026-11-25。研究分支 `stdc-research-v0.2`。供其他模型阅读的入口，不替代各轮冻结记录。

## 先读结论

目标始终是降低 J；Pd 独立报告。直接 STDC anytime 已在固定 Lake Ontario 归档上将最佳已测 paper baseline 的 J 从 17.29389415456 降至 17.264874448（约0.167803%），但 Pd 从0.89737041888降至0.897364416，且计算成本增加。后续多轮工程优化、rollout、DP和受限MILP没有进一步突破这个J。Hudsons Bay、Fundy对应直接STDC参考值见下表。

不能把“相对较弱seed有改善”“同扩展数更快”“下界更紧”“内存更小”写成“超过最好的直接STDC”。不能拼接不同路径的最好J与最好Pd。真实forcing是历史环境模型数据，目标轨迹仍是Leeway模拟粒子，不是实测遇险目标轨迹。

|场景|固定直接STDC参考J|同一路径Pd|约束标签|
|---|---:|---:|---|
|Lake Ontario|17.264874448|0.897364416|historical real forcing；all-water近似|
|Hudsons Bay（代码arctic_ocean）|20.386109349120|0.908583112320|historical real forcing；all-water近似|
|Bay of Fundy|45.881082400|0.415864800|另有physical_direction_unverified=true|

## 不可改变的数学与实验口径

- J=Σ M_t，t=1..T；Pd=1−M_T；t=0不探测。未探测权重不归一化，特殊格（水陆、域外等）质量保留。4连通无等待，固定离散探测模型和外生运动归档。
- 同一深度/位置的不同信念历史不能合并。等价粒子压缩只合并满足明确等价条件的轨迹，最终返回路径用原粒子ID评分器重放。
- paper_greedy按论文Algorithm 2无路径连续性逐步贪心；动态情况下不可无条件认证。研究anytime框架将其用于排序，安全下界另列。
- toy/Oracle一致是有限数值证据，不是一般证明。受限MILP的dual/gap只覆盖固定前缀/走廊，不能给原全问题认证；超时不证明无改善。本交接不新增任何ε最优声明。
- baseline-v1.1分支、B7原始数据、原评价器和forcing保持冻结；OpenDrift不在节点展开时运行。没有开展第二创新点。

## 改进演进：思路 → 设计 → 结果

各链接均指向原始归档。轮次的预算、源码和输入可能不同，不跨轮直接比较计时。

|轮次/思路|对应设计与代码|实测结论与证据|
|---|---|---|
|初期STDC修复/工程复用|检查下界、状态重用和重复计算；旧设计与对照|[早期对照](docs/stdc_v0_2/comparison_20261123.md)、[修复设计](docs/stdc_v0_2/repair_design.md)。不得将工程复用当作新质量优势。|
|固定时刻窗口|window_bounds/search：固定左右端点、精确后缀评分、endpoint可达约束|[窗口报告](outputs/stdc_v0_2/windows_20261123/FINAL_REPORT.md)：ε=1局部对照J 20.477608336→18.331441506，但未超过最佳baseline 17.29389415456；其他权重无质量改善。|
|全局anytime|anytime_search：完整候选后继续搜索；排序guide和安全剪枝界分离|[anytime报告](outputs/stdc_v0_2/anytime_20261124/FINAL_REPORT.md)：得到17.264874448；Pd略降、成本增，非普遍双指标优势。|
|计算与界优化|research_particle/search、lookahead_bound、tail_repair：快guide、级联/两步界、等价压缩、自由终点尾段、多排序|[优化报告](outputs/stdc_v0_2/optimization_20261124_resume/FINAL_REPORT.md)：66次正式运行未超过17.264874448。部分实现更快；较强下界不保证同预算质量更好。保留[中止轮](outputs/stdc_v0_2/optimization_20261124/FINAL_REPORT.md)。|
|中段多样化与单粒子DP|midpoint_rollout、particle_dp、trajectory_search：中段anchor后缀beam，每粒子可独立选择路线的DP松弛|[trajectory报告](outputs/stdc_v0_2/trajectory_20261124/final_report.md)：DP-only在Lake同扩展预算更快但J/Pd不变；多样化不稳定。实际LP诊断超预算，不能作为更优路线证据。|
|接入另两组真实场景|additional_forcing、run_additional_real、run_fundy_native：来源/UTC/reader/质量/SHA门控|[三场景对照](outputs/stdc_v0_2/three_real_20261124/three_real_comparison.md)、[Fundy接入](outputs/stdc_v0_2/fundy_repair_20261124/repair_report.md)。Fundy官方angle与地理网格约7°冲突未解决，按用户授权保留未验证标签接入。|
|调度、回退与紧凑DP|resumable_search、adaptive_search、short_window_rollout、sparse_particle_guide、compact_particle_dp：复用OPEN、局部余额归还、DP中止回退、短窗口冷却、可达时空/未来后缀压缩|[自适应报告](outputs/stdc_v0_2/adaptive_20261124/final_report.md)：180次正式运行；与直接STDC的144次配对，严格J胜出0。DP管理内存显著减少并恢复可运行性，但Fundy部分组合更差。|
|270候选零改善归因|按冻结额度重建候选；独立无beam窗口枚举；根下界审计|[诊断报告](outputs/stdc_v0_2/rollout_limit_diagnosis_20261124/diagnosis_report.md)：270/270等于当时incumbent，非270条新路径。最终路线447个4/6/8窗口、211237条累计窗口路径均无改善；10步完成部分同样无改善，12步未全完成。|
|独立受限MILP|exact_repair：位置二元变量、残余权重/乘积线性化、固定前缀、自由终点、扩大走廊|[首轮blocked](outputs/stdc_v0_2/exact_repair_20261124/final_report.md)：seed1059出现错误数值最优；停止真实实验。错误证据未覆盖。|
|MILP数值修复R2|关闭本地HiGHS presolve，保留严格容差及评分门槛|[R2](outputs/stdc_v0_2/exact_repair_r2_20261124/final_report.md)：6组同矩阵配置诊断，定位到本地参数/预处理交互，未证明原生内部根因。1197全量测试、192Oracle通过；3场景300秒诊断无改善。|
|完整可行解热启动+目标上界R3|highs_start、exact_repair：用本地SciPy内置HiGHS setSolution传入完整位置/残余/辅助变量，读回核对；加入非严格、向外舍入目标上界|[R3](outputs/stdc_v0_2/exact_repair_r3_20261124/final_report.md)：1228全量测试、192冷+576热/上界Oracle通过。三场景新跑冷/热各300秒；J/Pd无改善，内存均增加。默认仍为可选开关。|

## 关键实验结果与预算边界

正式搜索通常采用work（5000总扩展、30秒上限、OPEN≤20000）与wall（5秒、OPEN≤20000）两种协议，共同冻结PT起步；各方法三次计时重复，同一套粒子。辅助扩展、DP预处理、压缩与局部搜索按对应协议计费。三次重复不是三套独立环境，跨场景也不直接平均不同T下的J。

自适应DP管理数组中位数：Lake 55.143→8.720 MiB；Hudson 1286.016→70.948 MiB；Fundy 638.706→124.596 MiB。它们是管理数组需求，不能当作进程RSS。单粒子DP放松“所有粒子共享同一条路线”的耦合，和STDC没有一般支配关系。

R3是在已经算好的STDC路线之上另花300秒/方法/场景；此前路线成本未计入，不能与从头运行STDC作同预算胜出宣称。每组一次确定性运行，不做统计显著性结论。

|场景|冷启动秒→热启动秒|冷启动峰值→热启动峰值MiB|热组相对STDC ΔJ / ΔPd|
|---|---|---|---|
|Lake Ontario|300.447→300.039|428.11→475.54|0 / 0|
|Hudsons Bay|300.134→300.132|553.94→738.75|0 / 0|
|Bay of Fundy|300.122→300.642|961.30→989.93|0 / 0|

18个MILP子问题：6完成、12预算中止、0外部watchdog中止。前缀T−16/T−28/floor(T/3)，空间走廊半径1/2/3；均未覆盖完整全局可行域。原生候选现在可保持STDC质量，但没有新改善。Hudson热组最大模型建模约0.046秒、求解约205.77秒、结束节点计数0；主要成本在求解阶段，不能仅归因于Python构造。

机器可读证据：[R3 comparison.json](outputs/stdc_v0_2/exact_repair_r3_20261124/diagnostic/comparison.json)、[逐阶段效率](outputs/stdc_v0_2/exact_repair_r3_20261124/diagnostic/model_efficiency.csv)、[R3总验证](outputs/stdc_v0_2/exact_repair_r3_20261124/round_summary.json)。

## 已知事实、假设与待决问题

**事实**：短邻域存在局部稳定；270候选实际重复；完整热启动已成功提交；最近大邻域多数超时；最新组合没有超过直接STDC。三个根下界仍未闭合，不能证明全局近最优。Lake/Hudson/Fundy的(U−STDC根界)/U约46.83%/48.59%/7.48%，这是未排除区间，不是可获得收益预测。

**待验证假设**：固定前缀与端点/走廊约束可能锁住轨迹簇访问顺序；需要更早分歧或跨簇方案。显式目标上界行可能重复已有incumbent剪枝并增加LP负担。已有可行上界不会提高根LP最小值，因为根LP最小值本就不大于可行J；但实际性能影响尚无真实场景单项消融，不能宣称已定位。

**建议下一个分析模型先回答**：
1. 将warm-only与cutoff-only分开，是否能低成本排除冗余目标行造成的负担？应预注册什么指标/停止规则？
2. 哪个实验最有力地区分“STDC接近最优”与“固定早期前缀/走廊漏掉改善”？不要再建议只增大4/6/8步beam。
3. 如何构造跨轨迹簇、可改变早期航向/终点的少量合法候选，并把生成成本计入相同预算？已有midpoint/free-end后缀beam做过，不应仅改名重做。
4. 如何保留共同路径耦合而获得比单粒子独立DP更有用的界？给出数学前提、复杂度、toy反例和Oracle验收。
5. 提出最多3个方案，按预期信息增益/成本排序；分别说明事实依据、未验证假设、toy测试、真实对照、淘汰条件。允许结论“暂不继续该方向”。

## 环境、复跑与交付可得性

本地解释器 `C:/Users/35448/.conda/envs/maritime-sar/python.exe`；Python3.11.18、NumPy2.4.6、SciPy1.17.1、内置HiGHS1.12.0、OpenDrift1.14.12。没有安装升级依赖。详见各轮环境JSON。

设置PYTHONPATH包含scripts/offline_guard、src、scripts；ASAR_OFFLINE=1、PROJ_NETWORK=OFF、PYTHONDONTWRITEBYTECODE=1，数值库线程数1。模块命令为 `python -m pytest -x -q -p no:cacheprovider tests/test_exact_repair.py`，全量为 `python -m pytest -x -q -p no:cacheprovider tests`。R3模块114项（新增31）、全量1228；冷Oracle192、热/上界576，最大J误差0。原始command.json、stderr和JUnit均保存；非空pyreadline退出告警没有被隐瞒。

真实复跑必须先通过输入SHA门控，写入新输出目录。各轮脚本带冻结源SHA、历史test inventory和Windows绝对路径；旧阶段脚本在最新源码或另一台机器上可能因冻结检查而拒绝执行。不要绕过检查或宣称克隆即可一键复跑：需建立新实验协议、配置真实归档路径并重新冻结，或恢复相应历史源码快照。原粒子路径/UTC/对象/forcing指纹见[最新协议](outputs/stdc_v0_2/exact_repair_r3_20261124/experiment/protocol.json)。

本次推送研究代码、测试、报告、JSON/CSV、图、日志和可用的小型粒子归档。大体积NOAA原始.nc、下载分片.bin、zip及本地缓存不纳入这次提交，留在本地；具体排除文件及SHA见[上传清单](docs/research_handoff_20261125/upload_inventory.json)。部分Lake归档仍位于本地冻结baseline工作树，见协议中的绝对路径；不以合成粒子补齐。GitHub材料足以审阅结论与实现，不等于完整原始forcing镜像。

本次整理没有重跑全部科学实验，复核方式是核验已冻结源码/产物指纹、解析测试与指标JSON、检查交接链接和上传清单。具体通过项见[复核结果](docs/research_handoff_20261125/review.json)。保留所有blocked和负结果；不覆盖旧报告。
