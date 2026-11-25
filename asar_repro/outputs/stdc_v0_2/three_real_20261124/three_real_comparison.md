# 三个真实历史 forcing 场景的同预算对照

**Fundy 按用户授权的官方 native angle 接入；物理方向未验证。所有搜索结果均 uncertified。**

本轮新运行 Fundy 48 次；Lake Ontario 与 Hudsons Bay 各复用此前48次正式实验，并重新检查文件指纹、输入/forcing、算法实现及原评分器重放。没有重新运行 Leeway，也没有覆盖旧结果。
三个场景使用真实历史模型 forcing，但目标粒子由 Leeway 模拟，不是实测目标轨迹。全部保留既有 all-water 岸线碰撞近似；Fundy 另有 native angle 与地理网格约7°不一致，不能将其结果解释为物理方向已验证。

## 固定协议

- work：最多5000扩展、30秒、OPEN≤20000；wall：5秒、OPEN≤20000。各方法每协议3次重复，循环轮换方法顺序，独立子进程顺序执行。
- 同一场景共享同一冻结 PT 和500粒子、seed=41、q=.78；目标仍为原 J=sum(M[1:T+1])，t=0不探测。算法预处理计入时间；公共PT构造、SHA校验不计入方法时间。
- DP 管理数组上限128 MiB；不是进程内存上限。内存为 Windows 进程峰值 working set，包括解释器、导入、输入、预处理、搜索和重放。不同场景输入/导入开销不同，不直接跨场景比较绝对内存。
- 3次重复共用一套冻结粒子，只衡量运行波动，不能当作3个独立随机环境。跨场景只报告各自相对baseline的差值，不把不同T/网格的J直接平均排名。
- 方法：paper_baseline=原paper_greedy A^SAR；prior_stdc=直接STDC；compressed_stdc=等价粒子压缩；dp_only/stdc_dp=单粒子DP下界；mid_plain/mid_diverse/mid_dp=最新中段rollout及消融。所有变体完整列出，不事后挑一个代称“最新方法”。

## 核心指标（3次中位数；范围保留在 CSV）

### Lake Ontario

T=49，网格=[17, 17]；粒子 SHA `8b30a87e543f1b33c39e70e1d0054e1750ec046ba2e0b627dd311d9945749456`。

|预算|方法|J↓|Pd↑|耗时s|峰值MiB|扩展数|完成/预算中止|
|---|---|---:|---:|---:|---:|---:|---|
|work|paper_baseline|17.293894155|0.897370419|0.9503|90.11|1222|3/0|
|work|prior_stdc|17.264874448|0.897364416|3.8811|147.60|5000|0/3|
|work|compressed_stdc|17.264874448|0.897364416|3.6732|127.70|5000|0/3|
|work|dp_only|17.264874448|0.897364416|2.3707|147.33|5000|0/3|
|work|stdc_dp|17.264874448|0.897364416|4.0920|165.57|5000|0/3|
|work|mid_plain|17.264874448|0.897364416|4.6711|94.63|4142|0/3|
|work|mid_diverse|17.291968495|0.894972397|4.8677|94.13|4131|0/3|
|work|mid_dp|17.291968495|0.894972397|5.4252|132.07|4131|0/3|
|wall|paper_baseline|17.293894155|0.897370419|0.9377|90.18|1222|3/0|
|wall|prior_stdc|17.264874448|0.897364416|5.0196|173.57|6607|0/3|
|wall|compressed_stdc|17.264874448|0.897364416|4.8175|149.49|6887|0/3|
|wall|dp_only|17.264874448|0.897364416|4.0790|184.62|8861|0/3|
|wall|stdc_dp|17.264874448|0.897364416|5.0171|181.96|6392|0/3|
|wall|mid_plain|17.264874448|0.897364416|5.0020|102.17|4293|0/3|
|wall|mid_diverse|17.264874448|0.897364416|5.0022|101.10|4334|0/3|
|wall|mid_dp|17.264874448|0.897364416|5.0025|133.41|3518|0/3|

### Hudsons Bay

T=60，网格=[65, 85]；粒子 SHA `6ed4ca52ecccc9369adae67f7da75477057317599869389224b6ffb488babfb6`。

|预算|方法|J↓|Pd↑|耗时s|峰值MiB|扩展数|完成/预算中止|
|---|---|---:|---:|---:|---:|---:|---|
|work|paper_baseline|20.390881327|0.906729745|1.3710|284.97|696|3/0|
|work|prior_stdc|20.386109349|0.908583112|4.8865|387.85|5000|0/3|
|work|compressed_stdc|20.386109349|0.908583112|5.1346|377.45|5000|0/3|
|work|dp_only|25.293460991|0.817636947|0.0065|219.14|0|0/3|
|work|stdc_dp|25.293460991|0.817636947|0.0060|219.21|0|0/3|
|work|mid_plain|20.386109349|0.908583112|10.9870|335.24|4922|0/3|
|work|mid_diverse|20.386109349|0.908583112|12.2964|346.41|4919|0/3|
|work|mid_dp|25.293460991|0.817636947|0.0057|219.32|0|0/3|
|wall|paper_baseline|20.390881327|0.906729745|1.2855|284.30|696|3/0|
|wall|prior_stdc|20.386109349|0.908583112|5.0257|386.33|4881|0/3|
|wall|compressed_stdc|20.386109349|0.908583112|5.0252|370.28|4396|0/3|
|wall|dp_only|25.293460991|0.817636947|0.0061|218.96|0|0/3|
|wall|stdc_dp|25.293460991|0.817636947|0.0056|218.92|0|0/3|
|wall|mid_plain|20.390576890|0.906963945|5.0080|316.14|1130|0/3|
|wall|mid_diverse|25.293460991|0.817636947|5.0082|321.62|852|0/3|
|wall|mid_dp|25.293460991|0.817636947|0.0058|219.20|0|0/3|

### Bay of Fundy [direction UNVERIFIED]

T=55，网格=[49, 61]；粒子 SHA `3cb169401cc0c4a98306a2d3535f73e92e5cf31dc6db984eabcd9cc7d4ec9ad0`。

|预算|方法|J↓|Pd↑|耗时s|峰值MiB|扩展数|完成/预算中止|
|---|---|---:|---:|---:|---:|---:|---|
|work|paper_baseline|45.903608800|0.399984000|1.1724|298.22|348|3/0|
|work|prior_stdc|45.881082400|0.415864800|5.3493|400.28|5000|0/3|
|work|compressed_stdc|45.881082400|0.415864800|5.5245|402.08|5000|0/3|
|work|dp_only|53.067097600|0.102055200|0.0051|216.85|0|0/3|
|work|stdc_dp|53.067097600|0.102055200|0.0048|216.39|0|0/3|
|work|mid_plain|45.892345600|0.413774400|5.8021|363.61|3192|0/3|
|work|mid_diverse|45.892345600|0.413774400|6.2148|363.58|3065|0/3|
|work|mid_dp|53.067097600|0.102055200|0.0052|216.65|0|0/3|
|wall|paper_baseline|45.903608800|0.399984000|1.2006|298.21|348|3/0|
|wall|prior_stdc|45.881082400|0.415864800|5.0307|396.69|4704|0/3|
|wall|compressed_stdc|45.881082400|0.415864800|5.0313|390.59|4089|0/3|
|wall|dp_only|53.067097600|0.102055200|0.0050|216.66|0|0/3|
|wall|stdc_dp|53.067097600|0.102055200|0.0049|216.82|0|0/3|
|wall|mid_plain|45.895278400|0.409000800|4.2860|330.32|1461|0/3|
|wall|mid_diverse|45.895278400|0.409000800|5.0059|332.09|1192|0/3|
|wall|mid_dp|53.067097600|0.102055200|0.0050|216.73|0|0/3|

## 配对结论

|场景/预算|STDC相对baseline的J下降%|Pd变化（百分点）|耗时比|峰值内存比|
|---|---:|---:|---:|---:|
|Lake Ontario / work|0.167803|-0.000600|4.014|1.638|
|Lake Ontario / wall|0.167803|-0.000600|5.359|1.924|
|Hudsons Bay / work|0.023403|+0.185337|3.703|1.361|
|Hudsons Bay / wall|0.023403|+0.185337|3.910|1.356|
|Bay of Fundy [direction UNVERIFIED] / work|0.049073|+1.588080|4.558|1.342|
|Bay of Fundy [direction UNVERIFIED] / wall|0.049073|+1.588080|4.188|1.331|

最新方法相对直接STDC的逐次配对差值见 `paired_comparisons.csv`（reference=prior_stdc）。J更小不意味着Pd必然更高；没有改变原始优化目标。

- Lake Ontario / work：最新变体中，中位 J 严格优于直接 STDC 的方法：无。
  同 J 的最新变体中耗时最低的是 dp_only：2.3707s，对照 STDC 3.8811s；这只是本批同分结果的描述，不是跨场景方法选择规则。
- Lake Ontario / wall：最新变体中，中位 J 严格优于直接 STDC 的方法：无。
  同 J 的最新变体中耗时最低的是 dp_only：4.0790s，对照 STDC 5.0196s；这只是本批同分结果的描述，不是跨场景方法选择规则。
- Hudsons Bay / work：最新变体中，中位 J 严格优于直接 STDC 的方法：无。
  同 J 的最新变体中耗时最低的是 compressed_stdc：5.1346s，对照 STDC 4.8865s；这只是本批同分结果的描述，不是跨场景方法选择规则。
- Hudsons Bay / wall：最新变体中，中位 J 严格优于直接 STDC 的方法：无。
  同 J 的最新变体中耗时最低的是 compressed_stdc：5.0252s，对照 STDC 5.0257s；这只是本批同分结果的描述，不是跨场景方法选择规则。
- Bay of Fundy [direction UNVERIFIED] / work：最新变体中，中位 J 严格优于直接 STDC 的方法：无。
  同 J 的最新变体中耗时最低的是 compressed_stdc：5.5245s，对照 STDC 5.3493s；这只是本批同分结果的描述，不是跨场景方法选择规则。
- Bay of Fundy [direction UNVERIFIED] / wall：最新变体中，中位 J 严格优于直接 STDC 的方法：无。
  同 J 的最新变体中耗时最低的是 compressed_stdc：5.0313s，对照 STDC 5.0307s；这只是本批同分结果的描述，不是跨场景方法选择规则。

## 中止及可验证范围

- Lake Ontario：停止原因 {'completed': 6, 'max_expansions': 12, 'global_seed_max_expansions': 9, 'max_seconds': 14, 'max_open': 7}；incumbent来源 {'search': 45, 'midpoint_rollout': 3}。
- Hudsons Bay：停止原因 {'completed': 6, 'max_expansions': 6, 'dp_max_memory_bytes': 18, 'global_seed_max_expansions': 6, 'max_seconds': 12}；incumbent来源 {'search': 27, 'common_frozen_ParallelTrack': 21}。
- Bay of Fundy [direction UNVERIFIED]：停止原因 {'completed': 6, 'max_expansions': 6, 'dp_max_memory_bytes': 18, 'global_seed_max_expansions': 6, 'max_seconds': 8, 'global_seed_max_seconds': 4}；incumbent来源 {'search': 29, 'common_frozen_ParallelTrack': 18, 'midpoint_rollout': 1}。

DP因内存预算未初始化的结果只保留共同PT，不可当成正常搜索或声称耗时优势；midpoint的global_seed_*表示全局种子阶段预算受限，即使局部提案完成，也不代表全局搜索完成。每次中止原因和incumbent来源均保存在 all_runs.csv。
三场景共144条最终路径全部独立重放合法；J最大误差0、Pd最大误差0。共18次正常结束、126次预算中止。
协作式时间预算最大余量 0.040188 s；未将该余量隐藏为严格硬实时截止。
原paper_greedy动态启发式仍无可采纳性保证；completed不等于认证最优。本批无ε证书。不能把三个固定任务上的数值差异推断为对一般场景的普适提升或统计显著性。

## 保全与复跑

规划器、评价器和forcing没有改动；沿用已通过的926项全量测试，未因仅新增实验启动/汇总脚本重复跑同一测试集。阶段manifest、source_sha256、每次command/stdout/stderr及seed均保存。
本轮脚本：本目录 run_fundy_benchmark.py、summarize.py、plot_results.py；Fundy正式结果保存在相邻 fundy_repair_20261124/benchmark 新目录。旧smoke/blocked/repair报告是当时记录，没有回写成正式实验报告。
离线执行需要 maritime-sar、offline_guard/src/scripts PYTHONPATH、UTF-8及单线程环境；精确子进程命令见每次 command.json。正式 benchmark 目录已存在时拒绝覆盖。
汇总可读文件：all_runs.csv（144行）、aggregate.csv（48组）、paired_comparisons.csv、provenance.json（UTC/对象/CSP/扫宽/T/来源/指纹）、replay_audit.json、validation_summary.json。

图件：three_scenes_work.png、three_scenes_wall.png；Fundy 带未验证标签的路径图 fundy_paths_qualified.png、质量曲线 fundy_work_survival_qualified.png / fundy_wall_survival_qualified.png。

DP 预处理细节见 dp_preprocessing_audit.json：Hudsons Bay 需要约 992.89 MiB、Fundy 约 638.71 MiB，均超过 128 MiB 上限；Fundy 等价压缩仍保留 500 列。
