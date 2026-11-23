# 论文对照 · A^SAR

以工作区 8 页 PDF（arXiv v2）为准。生成器将独立转录的第 7 页 Table I 的四个任务和 Table II 的 32 个时间值逐项与阶段 7 采用的 v1 表格核对。以下本地数值由已保存的实验逐条生成。[本地 PDF 表格转录与指纹](../data/fixtures/paper_tables_v2.json) · [论文 v2](https://arxiv.org/abs/2511.10792v2) · [阶段 7 来源记录](stage7_scenarios.md)

## 数学复现成功的范围

| 原文 | 实现与可复验事实 |
| --- | --- |
| Eq. (1) | 令 b₀=p，按 Pₜ 的行源列目的约定先传播，再仅将访问格的质量乘以 1−q。粒子后验权重沿轨迹 ID 承接。 |
| Eq. (5)–(7) | 第一次探测在第 1 步。Mₜ 为联合未探测质量之和，J=Σₜ₌₁ᵀ Mₜ，以步计；g 累积至当前深度。初始质量为 1 时 Pd(T)=1−M_T。 |
| Algorithm 1 | 用堆按 g+εh 排序；同位置、同深度的不同路径分别保留信念。静态和时变 toy 的零启发式搜索与完整 DFS 对照。 |
| Algorithm 2 | 深度 d 处的第 k 个未来动作按绝对时刻 d+k 传播，在距当前顶点 ≤k 的集合内逐步贪心，允许两次模拟选择之间跳格。代码另保留绝对时间半径作诊断。 |

论文 Theorem 1 对其贪心启发式提出下界与 ε 界主张。按上述离散约定，zero 的依据是余下代价非负；在运动守恒、单格探测且 0≤q≤1 时，第 k 步余下质量至少为 M·(1−q_max)ᵏ，给出 mass_lb。适用性还要求满足搜索终止条件。有限 toy 对照的精度与普遍推导分别记录。[阶段 3 逐前缀审计](../outputs/metrics/heuristic_validity_report.json)

在本地 3×3、T=4、q=0.78 的时变反例中，DFS 枚举 96 条合法路径，根处 h_paper=2.6170801771，最优余下代价为 2.5417333379，高估 0.0753468392。另一时变 toy（seed 213）在 ε=1 时确实返回次优路线，J=2.1977712387，Oracle 为 2.1857465891。静态 toy 的检查仅覆盖该输入。四个海域的 paper_greedy 结果均标记为未认证。

## Table I · 任务与本地输入

经纬度按 [经度, 纬度] 给出，Z 表示 UTC。扫宽单位为海里，T 为边数。最后一列依次为本地格宽（米）、步长（秒）、预漂移（小时）。

| 场景 | 论文对象 / Leeway 映射 | LKP / 事故 UTC | CSP / CST | 论文风 / 流 | 扫宽 / T | 格宽 / 步长 / 预漂移 |
| --- | --- | --- | --- | --- | --- | --- |
| Lake Ontario | PIW-2 / PIW-2 | [-76.5, 44.21] · 2025-08-26T14:45:00Z | [-76.496, 44.215] · 2025-08-26T15:45:00Z | HRRR / LOOFS | 0.1 / 49 | 185.2 / 9.26 / 1 |
| Bay of Fundy | PIW-1 / PIW-1 | [-65.3, 45.2] · 2025-02-14T00:00:00Z | [-65.072, 45.283] · 2025-02-14T09:00:00Z | HRRR / GoMOFS | 0.4 / 55 | 740.8 / 37.04 / 9 |
| Salish Sea | Fishing Vessel / FISHING-VESSEL-1 | [-123.07, 48.3] · 2025-08-24T00:00:00Z | [-123.187, 48.195] · 2025-08-24T11:00:00Z | HRRR / CIOPS Salish Sea | 1.6 / 41 | 2963.2 / 148.16 / 11 |
| Arctic Ocean | Deep Ballast Life Raft / LIFE-RAFT-DB-10 | [-90.6, 62.85] · 2025-08-29T00:00:00Z | [-90.447, 62.786] · 2025-08-30T00:00:00Z | GFS / ESPC-D-V02 | 0.5 / 60 | 926 / 46.3 / 24 |

各场景均采用 500 粒子、恒风（东、北）=(4, 0) m/s、恒流=(0.15, 0.05) m/s、全水域掩膜，按扫宽和 20 m/s 换算步时，q=0.78。四组标记为 `constant_synthetic`。历史产品目录及本次本地访问记录、岸线与海冰偏差见[逐场景可得性表](../outputs/stage7/deviations.csv)。

## Fig. 2–4 · 可逐项核对的图像

- **Fig. 2**　按论文思想重建同一起点、完美传感器、T=30 的 toy。1、5、15、30 步展示访问高质量格后剩余质量的变化。作者的具体先验矩阵缺失，像素与路径坐标均无逐点参照。[静态 toy](../outputs/figures/stage4_toy_static.png) · [自建时变对照](../outputs/figures/stage4_toy_dynamic.png)
- **Fig. 3**　论文以其最优参考值归一化。本地以各场景动态 PT 的 J 为分母。图上空心点表示计算预算已触发。ACO_inspired 各 100 次，本地带状区间为同粒子集上 J 中位数的 99% bootstrap 区间。[相对代价](../outputs/stage7/relative_cost.png)
- **Fig. 4**　Lake Ontario 在同一 UTC 的第 19 步并列显示漂移、ASAR_paper、动态 PT 与 ACO_inspired。路径叠加在各自的剩余质量上。作者的风流、手工 PT 和文献 [4] 的原版 ACO 均缺少本地等价输入或实现。[湖区路径与质量曲线](../outputs/stage7/lake_ontario/paths.png)

| 常量场景 | PT 的 J | A^SAR 的 J（ε=1.10） | A^SAR Pd(T) | ACO_inspired 中位 J [99% CI] | 正常结束 / ε 数 |
| --- | --- | --- | --- | --- | --- |
| Lake Ontario | 18.610855 | 14.648152 | 91.5249% | 17.974345 [17.7910, 18.2468] | 3/8 |
| Bay of Fundy | 52.867480 | 47.986677 | 34.1983% | 55.000000 [54.9688, 55.0000] | 4/8 |
| Salish Sea | 26.407885 | 23.271249 | 76.3565% | 34.744606 [32.6103, 36.7938] | 5/8 |
| Arctic Ocean | 56.475523 | 51.918233 | 33.9893% | 60.000000 [60.0000, 60.0000] | 3/8 |

## Table II · 逐 ε 的运行记录

原文列为 3.2 GHz M1 Pro 上的 C++ 秒数。本地列为 Windows/Python 的 `planner_wall_s`，包括初始上界评分，PT 构造耗时另存。各 ε 从同一 PT 独立启动。处理器、实现、输入、初始上界与计算预算均影响时间，表中保留了提前中止的运行。[J、运行时间与扩展数](../outputs/figures/stage8_search_comparison.png)

| 场景 | ε | 论文 s | 本地 s | 扩展数 | 状态 | 停止原因 | 返回路径来源 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Lake Ontario | 1.1 | 0.09 | 0.0834 | 75 | completed | — | search |
| Lake Ontario | 1.08 | 0.09 | 0.1182 | 134 | completed | — | search |
| Lake Ontario | 1.06 | 0.10 | 0.1315 | 157 | completed | — | search |
| Lake Ontario | 1.04 | 0.13 | 0.4312 | 600 | budget_exceeded | max_expansions | ParallelTrack |
| Lake Ontario | 1.02 | 0.19 | 0.6302 | 600 | budget_exceeded | max_expansions | ParallelTrack |
| Lake Ontario | 1.01 | 0.30 | 0.6849 | 600 | budget_exceeded | max_expansions | ParallelTrack |
| Lake Ontario | 1.005 | 0.52 | 0.7549 | 600 | budget_exceeded | max_expansions | ParallelTrack |
| Lake Ontario | 1 | 0.86 | 0.8034 | 600 | budget_exceeded | max_expansions | ParallelTrack |
| Bay of Fundy | 1.1 | 0.10 | 1.0372 | 56 | completed | — | search |
| Bay of Fundy | 1.08 | 0.11 | 1.0258 | 56 | completed | — | search |
| Bay of Fundy | 1.06 | 0.12 | 0.9943 | 56 | completed | — | search |
| Bay of Fundy | 1.04 | 0.17 | 1.0512 | 85 | completed | — | search |
| Bay of Fundy | 1.02 | 0.29 | 1.5331 | 600 | budget_exceeded | max_expansions | ParallelTrack |
| Bay of Fundy | 1.01 | 1.97 | 1.6970 | 600 | budget_exceeded | max_expansions | ParallelTrack |
| Bay of Fundy | 1.005 | 5.45 | 1.6725 | 600 | budget_exceeded | max_expansions | ParallelTrack |
| Bay of Fundy | 1 | 19.73 | 1.8014 | 600 | budget_exceeded | max_expansions | ParallelTrack |
| Salish Sea | 1.1 | 0.05 | 0.1848 | 42 | completed | — | search |
| Salish Sea | 1.08 | 0.05 | 0.2149 | 59 | completed | — | search |
| Salish Sea | 1.06 | 0.07 | 0.1810 | 69 | completed | — | search |
| Salish Sea | 1.04 | 0.22 | 0.2260 | 126 | completed | — | search |
| Salish Sea | 1.02 | 0.75 | 0.3604 | 332 | completed | — | search |
| Salish Sea | 1.01 | 1.32 | 0.7359 | 600 | budget_exceeded | max_expansions | ParallelTrack |
| Salish Sea | 1.005 | 1.70 | 0.7525 | 600 | budget_exceeded | max_expansions | ParallelTrack |
| Salish Sea | 1 | 2.24 | 0.7434 | 600 | budget_exceeded | max_expansions | ParallelTrack |
| Arctic Ocean | 1.1 | 0.10 | 1.9748 | 62 | completed | — | search |
| Arctic Ocean | 1.08 | 0.10 | 1.9786 | 63 | completed | — | search |
| Arctic Ocean | 1.06 | 0.10 | 2.4193 | 201 | completed | — | search |
| Arctic Ocean | 1.04 | 0.50 | 2.3124 | 600 | budget_exceeded | max_expansions | ParallelTrack |
| Arctic Ocean | 1.02 | 0.52 | 2.2845 | 600 | budget_exceeded | max_expansions | ParallelTrack |
| Arctic Ocean | 1.01 | 3.09 | 2.3369 | 600 | budget_exceeded | max_expansions | ParallelTrack |
| Arctic Ocean | 1.005 | 10.78 | 2.5950 | 600 | budget_exceeded | max_expansions | ParallelTrack |
| Arctic Ocean | 1 | 35.26 | 2.5306 | 600 | budget_exceeded | max_expansions | ParallelTrack |
