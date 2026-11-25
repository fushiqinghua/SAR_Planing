# STDC 自适应调度与紧凑 DP：最终实验报告

日期：2026-11-24。研究分支 stdc-research-v0.2。原目标、评价器、forcing、冻结 baseline 和旧实验数据未修改。
本报告区分算法正确性、三个固定真实归档上的数值事实以及未认证的实际预算结果。
核心结论：新增方法在 144 次与直接 STDC 的配对中，严格 J 胜出 0 次、J/Pd 同时胜出 0 次。速度或表内存变化不等同于核心指标突破。


## 验证与实验范围

新增测试 188 项，全量测试 1114 项，均无 failures/errors/skips。
随机 160 案例、18024 前缀；compact/dense DP 9012 次，最大差 8.88e-16；guide 9012 次选择序列完全一致、最大值差 0。
45 小图、145 次完整搜索，最大 Oracle J 误差 0；组合小图实际进入局部阶段 43 次。
30 次真实 smoke 与 180 次正式实验全部独立重放最终路径、incumbent 历史、局部接受路径和候选档案。
正式实验：正常完成 18 次、预算中止 162 次，认证数 0；J/Pd 最大重放误差均为 0/0。
work：5000 次全局+局部扩展、30 秒、20000 OPEN；wall：5 秒、20000 OPEN。所有方法用同一冻结 PT；预处理和所有搜索阶段计入方法时间。
DP 备份不是树节点扩展，单独记录备份数和时间。OPEN 计排队候选；pending/held 活动节点另列，进程 RSS 峰值覆盖输入、预处理、搜索、记录与重放。
每场景固定 seed=41、500 粒子；三次是计时重复，不是独立粒子实现或新 forcing。

## 预先指定的完整组合与直接 STDC

|场景|预算|直接 STDC J / Pd|组合 J / Pd|直接→组合秒|直接→组合峰值 MiB|
|---|---|---|---|---|---|
|Lake Ontario|work|17.264874448000 / 0.897364416|17.264874448000 / 0.897364416|3.444→4.287|147.89→152.89|
|Lake Ontario|wall|17.264874448000 / 0.897364416|17.264874448000 / 0.897364416|4.469→5.015|177.49→168.82|
|Hudsons Bay|work|20.386109349120 / 0.908583112|20.386109349120 / 0.908583112|4.741→6.236|388.03→392.31|
|Hudsons Bay|wall|20.386109349120 / 0.908583112|20.386109349120 / 0.908583112|5.029→5.008|393.59→374.09|
|Bay of Fundy|work|45.881082400000 / 0.415864800|45.881082400000 / 0.415864800|5.251→5.797|400.02→436.27|
|Bay of Fundy|wall|45.881082400000 / 0.415864800|45.888820000000 / 0.402760800|5.030→5.008|397.65→423.63|

## 所有消融结果

|场景|预算|方法|J 中位数|Pd 中位数|秒|峰值 MiB|扩展数|停止原因|
|---|---|---|---:|---:|---:|---:|---:|---|
|Lake Ontario|work|paper_baseline|17.293894154560|0.897370419|0.925|90.08|1222|{'completed': 3}|
|Lake Ontario|work|prior_stdc|17.264874448000|0.897364416|3.444|147.89|5000|{'max_expansions': 3}|
|Lake Ontario|work|recycle_stdc|17.264874448000|0.897364416|4.916|120.95|5000|{'max_expansions': 3}|
|Lake Ontario|work|short_eager|17.264874448000|0.897364416|3.366|145.66|5000|{'max_expansions': 3}|
|Lake Ontario|work|short_lazy|17.264874448000|0.897364416|3.290|145.97|5000|{'max_expansions': 3}|
|Lake Ontario|work|short_diverse|17.264874448000|0.897364416|3.377|145.73|5000|{'max_expansions': 3}|
|Lake Ontario|work|fast_stdc|17.264874448000|0.897364416|4.162|147.49|5000|{'max_expansions': 3}|
|Lake Ontario|work|dense_fallback|17.264874448000|0.897364416|3.866|204.61|5000|{'max_expansions': 3}|
|Lake Ontario|work|compact_dp|17.264874448000|0.897364416|3.154|142.92|5000|{'max_expansions': 3}|
|Lake Ontario|work|adaptive_combo|17.264874448000|0.897364416|4.287|152.89|5000|{'max_expansions': 3}|
|Lake Ontario|wall|paper_baseline|17.293894154560|0.897370419|0.911|90.06|1222|{'completed': 3}|
|Lake Ontario|wall|prior_stdc|17.264874448000|0.897364416|4.469|177.49|6870|{'max_open': 3}|
|Lake Ontario|wall|recycle_stdc|17.264874448000|0.897364416|5.008|123.48|5185|{'max_seconds': 3}|
|Lake Ontario|wall|short_eager|17.264874448000|0.897364416|4.739|182.05|7365|{'max_open': 3}|
|Lake Ontario|wall|short_lazy|17.264874448000|0.897364416|4.644|181.80|7365|{'max_open': 3}|
|Lake Ontario|wall|short_diverse|17.264874448000|0.897364416|4.700|181.30|7365|{'max_open': 3}|
|Lake Ontario|wall|fast_stdc|17.264874448000|0.897364416|5.014|168.18|6281|{'max_seconds': 3}|
|Lake Ontario|wall|dense_fallback|17.264874448000|0.897364416|4.882|234.51|6870|{'max_open': 2, 'max_seconds': 1}|
|Lake Ontario|wall|compact_dp|17.264874448000|0.897364416|4.782|182.66|9130|{'max_open': 3}|
|Lake Ontario|wall|adaptive_combo|17.264874448000|0.897364416|5.015|168.82|6029|{'max_seconds': 3}|
|Hudsons Bay|work|paper_baseline|20.390881326720|0.906729745|1.282|284.54|696|{'completed': 3}|
|Hudsons Bay|work|prior_stdc|20.386109349120|0.908583112|4.741|388.03|5000|{'max_expansions': 3}|
|Hudsons Bay|work|recycle_stdc|20.386109349120|0.908583112|9.664|416.26|5000|{'max_expansions': 3}|
|Hudsons Bay|work|short_eager|20.386109349120|0.908583112|4.868|390.12|5000|{'max_expansions': 3}|
|Hudsons Bay|work|short_lazy|20.386109349120|0.908583112|4.868|389.68|5000|{'max_expansions': 3}|
|Hudsons Bay|work|short_diverse|20.386109349120|0.908583112|4.740|389.94|5000|{'max_expansions': 3}|
|Hudsons Bay|work|fast_stdc|20.386109349120|0.908583112|4.355|323.48|5000|{'max_expansions': 3}|
|Hudsons Bay|work|dense_fallback|20.386109349120|0.908583112|4.959|389.41|5000|{'max_expansions': 3}|
|Hudsons Bay|work|compact_dp|20.386109349120|0.908583112|4.153|356.75|5000|{'max_expansions': 3}|
|Hudsons Bay|work|adaptive_combo|20.386109349120|0.908583112|6.236|392.31|5000|{'max_expansions': 3}|
|Hudsons Bay|wall|paper_baseline|20.390881326720|0.906729745|1.286|284.21|696|{'completed': 3}|
|Hudsons Bay|wall|prior_stdc|20.386109349120|0.908583112|5.029|393.59|5460|{'max_seconds': 3}|
|Hudsons Bay|wall|recycle_stdc|20.390576889600|0.906963945|5.008|384.07|1351|{'max_seconds': 3}|
|Hudsons Bay|wall|short_eager|20.386109349120|0.908583112|5.013|392.96|5238|{'max_seconds': 3}|
|Hudsons Bay|wall|short_lazy|20.386109349120|0.908583112|5.012|394.82|5516|{'max_seconds': 3}|
|Hudsons Bay|wall|short_diverse|20.386109349120|0.908583112|5.013|393.70|5458|{'max_seconds': 3}|
|Hudsons Bay|wall|fast_stdc|20.386109349120|0.908583112|5.015|336.96|5978|{'max_seconds': 3}|
|Hudsons Bay|wall|dense_fallback|20.386109349120|0.908583112|5.011|392.00|5185|{'max_seconds': 3}|
|Hudsons Bay|wall|compact_dp|20.386109349120|0.908583112|5.015|392.21|7823|{'max_seconds': 3}|
|Hudsons Bay|wall|adaptive_combo|20.386109349120|0.908583112|5.008|374.09|3348|{'max_seconds': 3}|
|Bay of Fundy|work|paper_baseline|45.903608800000|0.399984000|1.164|298.30|348|{'completed': 3}|
|Bay of Fundy|work|prior_stdc|45.881082400000|0.415864800|5.251|400.02|5000|{'max_expansions': 3}|
|Bay of Fundy|work|recycle_stdc|45.884564320000|0.414268608|6.147|404.39|5000|{'max_expansions': 3}|
|Bay of Fundy|work|short_eager|45.881082400000|0.415864800|4.954|402.30|5000|{'max_expansions': 3}|
|Bay of Fundy|work|short_lazy|45.881082400000|0.415864800|4.930|402.15|5000|{'max_expansions': 3}|
|Bay of Fundy|work|short_diverse|45.881082400000|0.415864800|5.093|401.62|5000|{'max_expansions': 3}|
|Bay of Fundy|work|fast_stdc|45.881082400000|0.415864800|4.526|311.16|5000|{'max_expansions': 3}|
|Bay of Fundy|work|dense_fallback|45.881082400000|0.415864800|5.039|401.27|5000|{'max_expansions': 3}|
|Bay of Fundy|work|compact_dp|45.892345600000|0.413774400|2.772|351.44|5000|{'max_expansions': 3}|
|Bay of Fundy|work|adaptive_combo|45.881082400000|0.415864800|5.797|436.27|5000|{'max_expansions': 3}|
|Bay of Fundy|wall|paper_baseline|45.903608800000|0.399984000|1.144|298.30|348|{'completed': 3}|
|Bay of Fundy|wall|prior_stdc|45.881082400000|0.415864800|5.030|397.65|4795|{'max_seconds': 3}|
|Bay of Fundy|wall|recycle_stdc|45.892345600000|0.413774400|5.005|373.81|3224|{'max_seconds': 3}|
|Bay of Fundy|wall|short_eager|45.881082400000|0.415864800|5.010|405.14|5205|{'max_seconds': 3}|
|Bay of Fundy|wall|short_lazy|45.881082400000|0.415864800|5.009|402.70|4952|{'max_seconds': 3}|
|Bay of Fundy|wall|short_diverse|45.881082400000|0.415864800|5.010|403.86|5123|{'max_seconds': 3}|
|Bay of Fundy|wall|fast_stdc|45.881082400000|0.415864800|5.011|318.63|5516|{'max_seconds': 3}|
|Bay of Fundy|wall|dense_fallback|45.881082400000|0.415864800|5.012|398.87|4848|{'max_seconds': 3}|
|Bay of Fundy|wall|compact_dp|45.892345600000|0.413774400|5.005|373.46|14111|{'max_seconds': 3}|
|Bay of Fundy|wall|adaptive_combo|45.888820000000|0.402760800|5.008|423.63|3852|{'max_seconds': 3}|

## DP 构建和回退

|场景|方法|成功构建/运行数|要求管理内存 MiB 中位数|构建秒中位数|DP 中止后仍搜索次数|
|---|---|---:|---:|---:|---:|
|Lake Ontario|dense_fallback|6/6|55.143|0.253|0|
|Lake Ontario|compact_dp|6/6|8.720|0.182|0|
|Lake Ontario|adaptive_combo|6/6|8.720|0.186|0|
|Hudsons Bay|dense_fallback|0/6|1286.016|0.000|6|
|Hudsons Bay|compact_dp|6/6|70.948|1.861|0|
|Hudsons Bay|adaptive_combo|6/6|70.948|1.823|0|
|Bay of Fundy|dense_fallback|0/6|638.706|0.000|6|
|Bay of Fundy|compact_dp|6/6|124.596|1.361|0|
|Bay of Fundy|adaptive_combo|6/6|124.596|1.342|0|

## 实现与解释边界

- 可恢复全局 OPEN；局部未用预算回到全局。DP 未完成明确记录并回退 STDC，使用同一剩余 deadline。
- 短窗口保留绝对时刻、固定端点和精确后缀；24 个质量槽加可选 4 个多样性槽。新机会排序只决定尝试次序，不用于安全剪枝。
- 默认局部工作占比上限 10%；未产生改善的已完成窗口触发 2/4 全局片冷却。所有额度和队列同时计费。
- SparseParticleGuide 按实际占据单元计算，并以 4 MiB 距离缓存上限代替无界半径集合缓存；仍执行原 Algorithm 2 的无路径连续性逐步贪心。
- CompactParticleDP 保留 Float64；只压缩起点可达的时空系数及相同未来轨迹后缀，不合并路径信念、不丢特殊 bin 质量。
- 单粒子 DP 与 STDC 没有一般支配关系；速度、内存和 J/Pd 收益必须分开报告。
- J=sum(M_t,t=1..T)，t=0不检测；Pd=1-M_T。最小 J 不保证最大最终 Pd，未加入新的 Pd 约束或改变接受目标。
- 原 paper_greedy 仍只在新方法中排序；paper_baseline 的 completed 不代表已验证动态 epsilon 界。
- 任何 beam/窗口完成、预算中止和本轮真实路线均不标记全局 epsilon 认证。未证明当前最好 J 接近全局最优。
- 所有场景保留 all-water 碰撞近似。Fundy 始终 physical_direction_unverified=true，官方 angle 与地理网格方向的物理矛盾未解决。
- 新增测试曾有 fixture/范围错误（缺 trajectory ID、预算提前完成假设、固定终点误比自由终点、mock 时钟未到期）。失败尝试与独立诊断保留；只修新测试，未修改历史测试、评价器或放宽可采纳性阈值。

## 保全与文件

5589 份既有研究文件、654 份冻结 baseline 文件逐字节不变。
两份当前研究工作区的生成型 pytest 缓存被首次新测试更新，原/新 SHA 已在 transient_cache_incident.json 单列；不声称这两份缓存逐字节保全。后续测试全部禁用 cacheprovider。
评价器、forcing、粒子、B7、Stage 7/8 和旧正式实验文件均在严格保全范围内。未重新运行 OpenDrift、未安装升级依赖。
命令、seed、stdout/stderr、JUnit XML、源 SHA 和 git diff 分别在 source_freeze*、各 stage、new_tests、oracle、full_tests、experiment、smoke、benchmark 下。
CSV：benchmark/metrics.csv、aggregate.csv、paired_comparisons.csv；图：*_paths.png、*_survival_anytime.png、*_efficiency.png、*_paired_deltas.png。
代码清单：code_files.json。来源及模型参数：experiment/protocol.json。

## 新 rollout 的实际贡献

72 次短窗口运行合计生成 270 个完整候选，局部接受 0 次 J 改善，向全局注入并改善 0 次。它们是否超过直接 STDC 以配对表为准。
详细的生成/接受/下界调用/预算分配记录在 rollout_efficiency_audit.json；不把局部相对较弱 seed 的改善当成超过直接 STDC。

## 环境与复跑

解释器：C:\Users\35448\.conda\envs\maritime-sar\python.exe

|包|实际版本|
|---|---|
|numpy|2.4.6|
|scipy|1.17.1|
|pytest|9.2.0|
|opendrift|1.14.12|
|psutil|7.2.2|
|matplotlib|3.11.2|
|netCDF4|1.7.5|
|pyproj|3.7.2|

完整命令见各阶段 command.json；单次离线复跑可运行 offline_replay.ps1，例如：

```powershell
& .\offline_replay.ps1 -Scenario bay_of_fundy -Variant fast_stdc -Protocol wall
```

脚本在新目录保存结果，复用并再次核验冻结协议、源码与输入；不会覆盖旧结果。完整 180 次调度见 benchmark/schedule.json。
