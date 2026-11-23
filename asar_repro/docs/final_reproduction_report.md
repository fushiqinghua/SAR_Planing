# A^SAR 论文复现最终报告

## 数学复现成功

在已实现的有限离散模型内，信念递推、累积目标和小图搜索通过了手算及独立路径枚举核验。相同三步预算下，先搜高质量格得 J=0.6，交换顺序得 J=1.4，两者 Pd(T) 均为 1；无检测案例 J=3、Pd(T)=0。阶段 2 的 8 组输入分别比较 DFS、无剪枝堆和剪枝堆，J 对 Oracle 的最大绝对误差为 0。[阶段 1 手算](../outputs/metrics/stage1_toy.json) · [阶段 2 对照](../outputs/metrics/stage2_comparison.csv)

阶段 3 在 5 个 toy 上逐前缀核验。动态反例的 paper_greedy 高估余下最优代价 0.0753468392。本文对数学复现的判定覆盖定义、实现和上述实例；论文的一般动态 ε 界不能从这些实验推出。[定理适用条件与反例](paper_comparison.md)

阶段 4 的静态 toy 按论文思想重建。交换两段同长往返路径后，最终 Pd(T) 同为 0.600040，J 分别为 21.568613 和 21.764661。这是路径顺序改变截断代价的独立对照。[顺序实验](../outputs/figures/stage4_order.png)

## OpenDrift 场景近似

四组 Table I 任务采用 OpenDrift 1.14.12 的 Leeway 预漂移，CST 对齐第 0 帧。Lake Ontario 的质量账本最大绝对残差为 4.44e-16。特殊格继续持有不可搜索粒子的质量。离散时钟仅在每条边结束时探测一次。[粒子账本](../outputs/metrics/stage5_mass.csv) · [粒子图](../outputs/figures/stage5_particles.png)

阶段 6 在冻结的湖区轨迹上扫描 8 个 ε，4 次触及预算。进程峰值工作集为 52.89–139.12 MiB，另存一次 cProfile 运行。阶段 6 初始上界来自固定审计路线；阶段 7 使用动态 PT，并有单独的计算上限。[阶段 6 全部测量](../outputs/metrics/stage6_epsilon.csv) · [profile](../outputs/logs/stage6_profile.txt)

阶段 7 同输入比较覆盖 436 条可行路径。按 ID 独立重放 M、J 与 Pd(T) 的最大绝对误差为 8.53e-14。32 次 ASAR_paper 中 15 次正常结束；按停止原因计数为 max_expansions × 17。预算中止行保留当时的可行路径及其来源，全部四场景的 paper_greedy 实验均未认证。[逐 ε 状态及数值](paper_comparison.md) · [逐时刻路径与评分](../outputs/stage7/step_metrics.csv)

## 原论文真实 forcing/原作者手工 PT 未复现

Table I 指定的历史风流产品与实际 reader 分列记录。当前缺少经过变量、区域和对应 UTC 窗口验证的原始 forcing 文件对，也缺少作者当次粒子集、地图边界和认证搜救规划员的原始 PT 路径。本地使用全水域恒风恒流、规则生成的动态 ParallelTrack 和 ACO_inspired。海岸、潮汐变化、海冰及作者现场飞行未纳入结果。结论限于同一合成输入上的算法对照。[数据来源与缺口](stage7_scenarios.md) · [逐场景复现偏差](../outputs/stage7/deviations.csv)

## 配置、指标与复跑

| 输入配置 | 文件 SHA-256 |
| --- | --- |
| [`lake_ontario_constant.yaml`](../configs/lake_ontario_constant.yaml) | `f04f2c86e650a4111727c73e441f7832bf1d9ac2c88c15ca2df1e23ead30fb59` |
| [`schema.json`](../configs/schema.json) | `c800b491f9094d85d8a143186b91e8dbd5ec6fdf3c981176b1b98fe265c6ca92` |
| [`stage6_particle_search.yaml`](../configs/stage6_particle_search.yaml) | `962ee28b53c869be90ff5601cedbcf0e79624db2d6edf08e3f5ba92229c936e7` |
| [`stage7_scenarios.yaml`](../configs/stage7_scenarios.yaml) | `40311df54d7e43dcebdb2e618ebcb81a86add4d83db7a8ac925253ff73f391d6` |
| [`toy_dynamic.yaml`](../configs/toy_dynamic.yaml) | `694336bde45b61531fd69ac2bc566ff4b79a17589a8a944cf4554b753ce29804` |
| [`toy_static.yaml`](../configs/toy_static.yaml) | `a9648c135b9f2f3a6848f48b47d753a5acc35bf6a4260a93271b1f481680e422` |

[统一指标 CSV](../outputs/metrics/summary.csv) 共 527 条；阶段 1 至 7 的条数依次为 4, 24, 45, 8, 1, 9, 436。阶段 0 保存环境与 smoke 证据。每条记录以 config_hash、seed、algorithm、epsilon 区分，source_file 指向原始证据。input_seed 描述输入，algorithm_seed 描述随机规划。确定性输入的 seed 留空。阶段 1–3 对固化输入取配置摘要；阶段 6 将粒子摘要、搜索配置及 profile 标志联合取哈希，阶段 7 沿用每个场景的实验配置摘要。无适用参考解或未测量的列留空。max_open 为实测队列峰值，限制值保存于实验配置。工作区无 Git 历史，git_commit 留空。

逐步序列及诊断继续保存在[阶段 1–6 指标目录](../outputs/metrics/)和[阶段 7 归档](../outputs/stage7/)；[四场景输入清单](../data/processed/manifest.json)及同目录 NPZ 足以离线调用规划器。生成报告时重新核对粒子 SHA-256 和阶段 7 全部路径。Python 3.11.18，指定解释器为 `C:\Users\35448\.conda\envs\maritime-sar\python.exe`。本轮全量测试日志记录为 **130 passed in 11.58s**。[测试日志](../outputs/logs/) · [环境快照](../outputs/logs/environment.json)

## 接入现有仿真的边界

独立 Python 接口返回原始格号路径、对应的格心 WGS84 经纬度和 UTC、逐步 M、J、Pd(T)、停止原因及解来源。调用方可以传入自己的预分格轨迹，或加载已固化的场景。航迹平滑、最小转弯半径、速度约束及返航由宿主另行评估；改变路径或采样时刻后应重新计算探测与目标值。离散格路径的结果仅适用于给定 T 和时钟。[接口与复跑命令](../README.md) · [模型假设](assumptions.md) · [阶段日志](reproduction_log.md)
