# 阶段 7 · 四个 Table I 场景的常量环境对照

四组实验均对齐任务参数，环境标签均为 `constant_synthetic`。风流产品的历史目录已找到，本地尚未取得并验证对应任务全时段、区域与变量的风流文件对。下表经纬度顺序为 **经度、纬度**，时刻均为 2025 年 UTC。Table I 的 Lake Ontario 模拟事故在 8 月 26 日，论文现场试验另在 9 月 8 日。[论文 Table I、Table II 与 Fig. 4](https://arxiv.org/html/2511.10792v1)

| 场景 / 搜索对象 | LKP / 事故时刻 | CSP / CST | 论文风 / 流 | 扫宽 Nm / T | 本地步长 |
|---|---|---|---|---:|---:|
| Lake Ontario / PIW-2 | (−76.5, 44.21) · 08-26 14:45 | (−76.496, 44.215) · 08-26 15:45 | HRRR / LOOFS | 0.1 / 49 | 9.26 s |
| Bay of Fundy / PIW-1 | (−65.3, 45.2) · 02-14 00:00 | (−65.072, 45.283) · 02-14 09:00 | HRRR / GoMOFS | 0.4 / 55 | 37.04 s |
| Salish Sea / Fishing Vessel | (−123.07, 48.3) · 08-24 00:00 | (−123.187, 48.195) · 08-24 11:00 | HRRR / CIOPS Salish Sea | 1.6 / 41 | 148.16 s |
| Arctic Ocean（Hudson’s Bay）/ Deep Ballast Life Raft | (−90.6, 62.85) · 08-29 00:00 | (−90.447, 62.786) · 08-30 00:00 | GFS / ESPC-D-V02 | 0.5 / 60 | 46.30 s |

## 环境证据与复现偏差

2026-11-23 本地核查时，项目的 `data/raw` 为空。下列对日期目录和索引的本地 HTTP 探测均在取得服务器响应前返回 `WinError 10013`。这项记录只说明本次本地访问结果。数据可得性统一标识为 `historical_wind_current_pair_unverified_locally`。归档配置、作者所用循环和预测时效尚待核验。

| 场景 | 查阅的产品目录与本地探测对象 | 替代输入带来的主要偏差 |
|---|---|---|
| Lake Ontario | HRRR 20250826 14Z 地面 GRIB2 索引、NOS S3 的 `loofs/netcdf/2025/08/26/` 候选前缀。[HRRR](https://registry.opendata.aws/noaa-hrrr-pds/) · [NOAA Great Lakes 历史数据](https://www.glerl.noaa.gov/res/Programs/ipemf/glcfs_data_access.html) | 复用阶段 5 粒子，湖岸和时变湖流缺失。 |
| Bay of Fundy | HRRR 20250214 00Z 地面索引、NOS S3 的 `gomofs/netcdf/2025/02/14/` 候选前缀。[HRRR](https://registry.opendata.aws/noaa-hrrr-pds/) · [NOAA OFS 目录](https://opendap.co-ops.nos.noaa.gov/ofsdataagg/index.html) | 9 小时预漂移中采用恒流，未建模潮流反转。CST 粒子距 CSP 的中位数为 14.16 km。 |
| Salish Sea | HRRR 20250824 00Z 地面索引、加拿大 Datamart 的 `20250824/model_ciops/salish-sea/` 候选路径。[HRRR](https://registry.opendata.aws/noaa-hrrr-pds/) · [加拿大 CIOPS 文件和变量说明](https://eccc-msc.github.io/open-data/msc-data/nwp_ciops/readme_ciops-datamart_en/) | 网格边长 2.9632 km。全水域掩膜省略了岛屿和狭窄航道约束。 |
| Arctic Ocean | GFS 20250829 00Z 的 0.25° 地面分析索引及 ESPC-D-V02 的 2025 时序元数据候选端点。HYCOM 目录列有表层东西、南北流分量。[GFS](https://registry.opendata.aws/noaa-gfs-bdp-pds/) · [HYCOM 产品](https://www.hycom.org/dataserver/espc-d-v02/global-analysis) | 预漂移跨 UTC 日期，8 月 30 日 00:46:18 搜索结束。使用全水域，未建模海冰、冰缘和海岸相互作用。 |

本地统一取向东风分量 4 m/s、向北风分量 0 m/s，海流东、北分量分别为 0.15、0.05 m/s。这些数值沿用阶段 5 的合成设置。OpenDrift 1.14.12 的 Leeway 使用 500 个 ID、seed 41、播种半径参数 100 m。四个对象分别映射到本机对象表的 2、1、50、7 号，渔船和深压载救生筏采用该类的一般模型。Lake 原生积分和输出间隔均为 30 s，其余为 120 s。全量轨迹先按 UTC 插值，再在以 CSP 为原点的 AEQD 投影上分格。[实验配置](../configs/stage7_scenarios.yaml)

高度 300 ft，速度 20 m/s，均匀探测概率 0.78。边长取扫宽，步长取边长除以速度，离散预算省略转弯耗时。各方案从相同 CSP、相同 CST 权重出发，第 0 帧保留初始质量，首次探测在第 1 步。每个 ID 的剩余质量跨步传播。陆地、域外、停用和未知各有自己的质量格，四次运行的搜索窗口内这些格的先验总质量均为零。

## 同数据评分与计时

- **ParallelTrack** 按当步可探测质量的行、列边缘分布各取 5%–95% 包络。先沿四邻边进入包络，再沿东西向平行扫描，抵达端点时根据新的包络换一行。每次经过格子均更新相关 ID 的未探测权重。论文 PT 由认证搜救规划员设计，本地 PT 由上述规则生成。
- **ASAR_paper** 使用阶段 2/3 的同一搜索循环和动态 `paper_greedy`。每个 ε 单独启动，以上述 PT 作为可行初始上界。上限为 600 次扩展、2400 个 OPEN 节点、30 秒。CSV 中 `planner_wall_s` 包含搜索内部的上界重放，`total_wall_s` 另计构造 PT 的时间。两者均排除漂移预处理、最终统一重放和绘图。论文 Table II 的 3.2 GHz M1 Pro / C++ 秒数仅作来源参照。
- **ACO_inspired** 为本地蚁群基线，每轮 4 只蚂蚁、3 代，邻格采样权重取信息素和当步可探测质量，保留正探索概率。每代在挥发后用该代最佳路径强化有向边。每个场景固定同一批 100 个规划 seed（7000–7099），粒子和漂移 seed 固定。未复现文献 [4] 的 max–min、编码和调参细节。离开粒子云时相邻格的探测收益可能全部为零，这时移动仅受探索项和信息素影响。区间仅反映此粒子输入上规划随机性对 **J 中位数** 的影响，采用 10000 次有放回 bootstrap 的 0.5% 和 99.5% 分位数，seed 为 97。

三种方法均通过 `score_path` 得到 J、Pd 和完整的 M 序列。对比图分母为同场景 PT 的 J。动态 `paper_greedy` 存在阶段 3 的不可采纳反例，所有运行均保留 `certified=false`。路径图统一取 ε=1.10 和最接近 J 中位数的 ACO 试验，出现同距则取较小 seed。

| 场景 | PT 的 J | ASAR_paper 的 J / Pd（ε=1.10） | ACO_inspired 的 J 中位数 [99% CI] | ASAR 正常结束 / 8 |
|---|---:|---:|---:|---:|
| Lake Ontario | 18.610855 | 14.648152 / 0.915249 | 17.974345 [17.790984, 18.246771] | 3 / 8 |
| Bay of Fundy | 52.867480 | 47.986677 / 0.341983 | 55.000000 [54.968800, 55.000000] | 4 / 8 |
| Salish Sea | 26.407885 | 23.271249 / 0.763565 | 34.744606 [32.610254, 36.793778] | 5 / 8 |
| Arctic Ocean | 56.475523 | 51.918233 / 0.339893 | 60.000000 [60.000000, 60.000000] | 3 / 8 |

17 次中止全部发生在 600 次扩展处，均返回 PT 初始路径。表内 ε=1.10 的四条路径均由搜索产生。ACO 在 Bay of Fundy 与 Arctic Ocean 的中位 J 达到 T，表示这一试验预算下至少半数路线在数值精度内没有检测收益。

CSV 和 JSON 保留评分器的原始双精度结果。500 份等权重求和存在舍入误差，零检测收益路径的 `1-M_T` 最小记录为 −4.44e−16，按实验容差读作 0。

## 数据与复跑

配置固定了任务和本地假设。每个场景的 `results.json` 保存来源、历史产品目录、实际 reader 配置、粒子归档 SHA-256、UTC、路径、生存曲线与计算状态。Lake 复用阶段 5 归档，其余场景的 `particles.npz` 保存在各自结果目录中。时间数组为 UTC，坐标顺序为经度、纬度，轨迹列由 `trajectory_id` 唯一标识。

在 `asar_repro` 工作目录执行以下 PowerShell 命令。固定文件已存在时复用粒子；全新输出目录将按 Lake、Fundy、Salish、Arctic 顺序处理。单场景运行可给第一条脚本命令添加 `--scenario lake_ontario`。报告命令读取同一目录下的四份结果。

```powershell
$PY = 'C:\Users\35448\.conda\envs\maritime-sar\python.exe'
$env:PYTHONUSERBASE = Join-Path (Get-Location) '.python-user'
$env:PATH = (Join-Path (Split-Path $PY) 'Library\bin') + [IO.Path]::PathSeparator + $env:PATH
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
& $PY scripts/run_stage7.py
& $PY scripts/report_stage7.py
& $PY -m pytest -q tests/test_stage7.py
& $PY -m pytest -q
```

[436 次统一指标](../outputs/stage7/metrics.csv) · [逐时刻评分及路径](../outputs/stage7/step_metrics.csv) · [逐场景复现偏差](../outputs/stage7/deviations.csv) · [相对 PT 的 J](../outputs/stage7/relative_cost.png)

| 场景 | 来源、状态与全量路径 | t=19 与完整路线 | t=1、5、15、30 的逐格剩余质量 | 粒子归档 |
|---|---|---|---|---|
| Lake Ontario | [JSON](../outputs/stage7/lake_ontario/results.json) | [路径图](../outputs/stage7/lake_ontario/paths.png) | [概率图](../outputs/stage7/lake_ontario/belief_sequence.png) | [NPZ](../outputs/particles/stage5_leeway.npz) |
| Bay of Fundy | [JSON](../outputs/stage7/bay_of_fundy/results.json) | [路径图](../outputs/stage7/bay_of_fundy/paths.png) | [概率图](../outputs/stage7/bay_of_fundy/belief_sequence.png) | [NPZ](../outputs/stage7/bay_of_fundy/particles.npz) |
| Salish Sea | [JSON](../outputs/stage7/salish_sea/results.json) | [路径图](../outputs/stage7/salish_sea/paths.png) | [概率图](../outputs/stage7/salish_sea/belief_sequence.png) | [NPZ](../outputs/stage7/salish_sea/particles.npz) |
| Arctic Ocean | [JSON](../outputs/stage7/arctic_ocean/results.json) | [路径图](../outputs/stage7/arctic_ocean/paths.png) | [概率图](../outputs/stage7/arctic_ocean/belief_sequence.png) | [NPZ](../outputs/stage7/arctic_ocean/particles.npz) |
