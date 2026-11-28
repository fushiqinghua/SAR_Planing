# 精确状态等价合并实验分析

## 1. 版本与有效性

- 本次分析状态 **rolling_merge_development_screen_not_passed**。当前检出提交 `6b69d5d0242cb8eb7e24bbe1c5219737f39cab34`，分支 `eight-neighbor-rolling-pilot-20261128`。
- 父参考 `6084c7d6528a863709466e1dfbb0930459d95414`。既有 rolling pilot 资料保持原判定。
- 输出目录 `outputs/eight_neighbor_rolling_merge_20261128/local_r1`。
- 四份 H2 固定粒子档案和共同初始路线属于已见开发数据。每组重复反映计时差异。
- 冻结时间 2026-11-28T05:01:55.424985+00:00。任务排列 seed 2026112802。
- 协议 SHA-256 `6889d21a3b9ee9d75ef33b5127125972735ada1acbf1efc4ab94d4000bb213ce`。配置 SHA-256 `d44117addd25e7983b6c88539d7fd113de9581b7ae6d2d7cde3dda39fa7b2087`。[冻结协议](protocol.json) · [预检](preflight.json) · [冻结配置](../../../configs/eight_neighbor_rolling_merge.json) · [参考清单](../../../docs/eight_neighbor_rolling_merge/reference_manifest.json)
- Python 3.11.18 \| packaged by conda-forge \| (main, Oct 26 2026, 11:29:07) [MSC v.1944 64 bit (AMD64)]。Windows-10-10.0.26200-SP0，32 个逻辑核。五个数值线程设置均为 1。RSS 监控上限 2 GiB。
- 软件版本 numpy 2.4.6、scipy 1.17.1、pytest 9.2.0、psutil 7.2.2、pyproj 3.7.2、opendrift 1.14.12、xarray 2026.9.0、PyYAML 6.0.3、netCDF4 1.7.5、shapely 2.2.0。
- 来源证据包含 68 份直接文件 SHA 和 225 份继承 Git blob。

| 阶段 | 计划 | 有效 | 尚缺 | 失败或无效 | 阶段状态 |
| --- | --- | --- | --- | --- | --- |
| D0 | 4 | 4 | 0 | 0 | complete |
| F30 | 48 | 48 | 0 | 0 | complete |

### 本地软件验证

| 尝试 | 状态 | 通过 | 失败 | 错误 | 跳过 | 证据 |
| --- | --- | --- | --- | --- | --- | --- |
| 20261128T050149844589Z | passed | 294 | 0 | 0 | 0 | [命令与结果](validation/20261128T050149844589Z/result.json) · [JUnit](validation/20261128T050149844589Z/pytest.xml) · [stdout](validation/20261128T050149844589Z/stdout.log) · [stderr](validation/20261128T050149844589Z/stderr.log) |

执行命令、耗时和退出记录。 [命令日志](commands)

## 2. D0 严格等价机会

D0 各项使用原八邻接问题和共同路线，计入影子索引开销。主搜索呈交索引的非终止子状态为分母。原 J 剪除的子状态、根、终端和贪心补全的内部候选均排除。更低 J 代表的更新也从可合并数量排除。四项全部有效且至少一个实例同时达到 100 个和 5%，才进入 F30。

| 实例 | 非终止 child | 可合并 | 比例 | 更低 J 更新 | 登记键数 | 容量拒绝 | 键 payload 峰值 MiB | 查找秒 | 达标 | 记录 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lake_h2_d1_s3101 | 106306 | 201 | 0.189% | 6 | 16384 | 89716 | 62.750 | 0.698 | False | [D0_adbf09ccfef739638fde](runs/D0_adbf09ccfef739638fde/result.json) |
| lake_h2_d2_s3201 | 117099 | 13 | 0.011% | 0 | 16384 | 100703 | 62.750 | 0.771 | False | [D0_3eed8b138cfc56d08fe2](runs/D0_3eed8b138cfc56d08fe2/result.json) |
| hudson_h2_d1_s4101 | 75208 | 5566 | 7.401% | 1 | 16384 | 53258 | 62.750 | 0.385 | True | [D0_d42c61537fe542148537](runs/D0_d42c61537fe542148537/result.json) |
| hudson_h2_d2_s4201 | 88401 | 13369 | 15.123% | 3757 | 16384 | 54892 | 62.750 | 0.754 | True | [D0_94b2379427259c620fda](runs/D0_94b2379427259c620fda/result.json) |

查找时间包含键构造。容量拒绝只表示没有登记新键，可能限制测得的机会。键 payload 只含保留的位置和权重数据。

| 实例 | 展开数 | 末两 tick 占比 | 终端生成事件 | guide / transition 秒 | 键构造秒 | 影子丢弃 / 陈旧跳过 | 内层停止 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hudson_h2_d1_s4101 | 16883 | 49.405% | 59851 | 22.216 / 5.997 | 0.227 | 0 / 0 | max_seconds |
| lake_h2_d2_s3201 | 63513 | 87.396% | 390805 | 4.812 / 21.423 | 0.479 | 0 / 0 | max_seconds |
| lake_h2_d1_s3101 | 72369 | 92.283% | 466812 | 3.957 / 22.302 | 0.428 | 0 / 0 | max_seconds |
| hudson_h2_d2_s4201 | 88062 | 96.770% | 602970 | 1.359 / 24.381 | 0.443 | 0 / 0 | max_seconds |

- D0 判定 **D0_admitted**。满足两个数值门槛的实例 2/4。 [冻结机会门槛](D0_gate.json) · [详细诊断](D0/merge_diagnostics.csv) · [自动汇总](D0/summary.json)
- 终端生成数以事件计。固定预算中的影子机会率只用于本轮准入。

## 3. F30 同预算对照

| 配对 | 角色 | 通过 | J 达标实例 | Lake / Hudson 达标 | J 无退化 | Pd 通过 |
| --- | --- | --- | --- | --- | --- | --- |
| C0_M_vs_C0 | generic merging increment | False | 0 | 0 / 0 | True | True |
| C1_M_vs_C1 | merging increment inside rolling | False | 0 | 0 / 0 | True | True |
| C1_M_vs_C0_M | primary net rolling increment | False | 0 | 0 / 0 | False | True |
| C1_M_vs_C0 | protected current strong control | False | 0 | 0 / 0 | False | True |

### C0_M_vs_C0

| 实例 | 对照 J | 候选 J | J 改善 | 对照 Pd | 候选 Pd | ΔPd 百分点 | J ≥ 0.5% | J 退化 | Pd 超限 | 代表运行 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lake_h2_d1_s3101 | 14.30706662 | 14.30706662 | +0.0000% | 94.91033% | 94.91033% | +0.00000 | False | False | False | [F30_5b4c442b35b5350ca094](runs/F30_5b4c442b35b5350ca094/result.json) / [F30_06da3ac7286ecbd7a002](runs/F30_06da3ac7286ecbd7a002/result.json) |
| lake_h2_d2_s3201 | 14.05850857 | 14.05850857 | +0.0000% | 93.04004% | 93.04004% | +0.00000 | False | False | False | [F30_88a4e6e4c3a0796ef8b2](runs/F30_88a4e6e4c3a0796ef8b2/result.json) / [F30_4ae59e3cac6bc5b59217](runs/F30_4ae59e3cac6bc5b59217/result.json) |
| hudson_h2_d1_s4101 | 28.44897988 | 28.44897988 | +0.0000% | 81.24606% | 81.24606% | +0.00000 | False | False | False | [F30_d0424f9f71624167360c](runs/F30_d0424f9f71624167360c/result.json) / [F30_712a396f350e00081925](runs/F30_712a396f350e00081925/result.json) |
| hudson_h2_d2_s4201 | 58.73970720 | 58.73970720 | +0.0000% | 8.58081% | 8.58081% | +0.00000 | False | False | False | [F30_d362368fa80b3ca35a9f](runs/F30_d362368fa80b3ca35a9f/result.json) / [F30_3d937ebe8de5f861e408](runs/F30_3d937ebe8de5f861e408/result.json) |

### C1_M_vs_C1

| 实例 | 对照 J | 候选 J | J 改善 | 对照 Pd | 候选 Pd | ΔPd 百分点 | J ≥ 0.5% | J 退化 | Pd 超限 | 代表运行 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lake_h2_d1_s3101 | 14.30706662 | 14.30706662 | +0.0000% | 94.91033% | 94.91033% | +0.00000 | False | False | False | [F30_a65069321fc0f385fcdb](runs/F30_a65069321fc0f385fcdb/result.json) / [F30_bae812538cc1fefce2d3](runs/F30_bae812538cc1fefce2d3/result.json) |
| lake_h2_d2_s3201 | 14.05850857 | 14.05850857 | +0.0000% | 93.04004% | 93.04004% | +0.00000 | False | False | False | [F30_88bfeb10ba8bbc420df2](runs/F30_88bfeb10ba8bbc420df2/result.json) / [F30_17a4c190f5aaa301e793](runs/F30_17a4c190f5aaa301e793/result.json) |
| hudson_h2_d1_s4101 | 28.63817833 | 28.63817833 | +0.0000% | 81.76178% | 81.76178% | +0.00000 | False | False | False | [F30_43a9e6328e7a23b77e6e](runs/F30_43a9e6328e7a23b77e6e/result.json) / [F30_de22123389e38fcf3d56](runs/F30_de22123389e38fcf3d56/result.json) |
| hudson_h2_d2_s4201 | 58.67765539 | 58.67765539 | +0.0000% | 8.81300% | 8.81300% | +0.00000 | False | False | False | [F30_345be821a234e73f4a38](runs/F30_345be821a234e73f4a38/result.json) / [F30_f034a0beb06a6efce3cc](runs/F30_f034a0beb06a6efce3cc/result.json) |

### C1_M_vs_C0_M

| 实例 | 对照 J | 候选 J | J 改善 | 对照 Pd | 候选 Pd | ΔPd 百分点 | J ≥ 0.5% | J 退化 | Pd 超限 | 代表运行 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lake_h2_d1_s3101 | 14.30706662 | 14.30706662 | +0.0000% | 94.91033% | 94.91033% | +0.00000 | False | False | False | [F30_06da3ac7286ecbd7a002](runs/F30_06da3ac7286ecbd7a002/result.json) / [F30_bae812538cc1fefce2d3](runs/F30_bae812538cc1fefce2d3/result.json) |
| lake_h2_d2_s3201 | 14.05850857 | 14.05850857 | +0.0000% | 93.04004% | 93.04004% | +0.00000 | False | False | False | [F30_4ae59e3cac6bc5b59217](runs/F30_4ae59e3cac6bc5b59217/result.json) / [F30_17a4c190f5aaa301e793](runs/F30_17a4c190f5aaa301e793/result.json) |
| hudson_h2_d1_s4101 | 28.44897988 | 28.63817833 | -0.6650% | 81.24606% | 81.76178% | +0.51571 | False | True | False | [F30_712a396f350e00081925](runs/F30_712a396f350e00081925/result.json) / [F30_de22123389e38fcf3d56](runs/F30_de22123389e38fcf3d56/result.json) |
| hudson_h2_d2_s4201 | 58.73970720 | 58.67765539 | +0.1056% | 8.58081% | 8.81300% | +0.23219 | False | False | False | [F30_3d937ebe8de5f861e408](runs/F30_3d937ebe8de5f861e408/result.json) / [F30_f034a0beb06a6efce3cc](runs/F30_f034a0beb06a6efce3cc/result.json) |

### C1_M_vs_C0

| 实例 | 对照 J | 候选 J | J 改善 | 对照 Pd | 候选 Pd | ΔPd 百分点 | J ≥ 0.5% | J 退化 | Pd 超限 | 代表运行 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lake_h2_d1_s3101 | 14.30706662 | 14.30706662 | +0.0000% | 94.91033% | 94.91033% | +0.00000 | False | False | False | [F30_5b4c442b35b5350ca094](runs/F30_5b4c442b35b5350ca094/result.json) / [F30_bae812538cc1fefce2d3](runs/F30_bae812538cc1fefce2d3/result.json) |
| lake_h2_d2_s3201 | 14.05850857 | 14.05850857 | +0.0000% | 93.04004% | 93.04004% | +0.00000 | False | False | False | [F30_88a4e6e4c3a0796ef8b2](runs/F30_88a4e6e4c3a0796ef8b2/result.json) / [F30_17a4c190f5aaa301e793](runs/F30_17a4c190f5aaa301e793/result.json) |
| hudson_h2_d1_s4101 | 28.44897988 | 28.63817833 | -0.6650% | 81.24606% | 81.76178% | +0.51571 | False | True | False | [F30_d0424f9f71624167360c](runs/F30_d0424f9f71624167360c/result.json) / [F30_de22123389e38fcf3d56](runs/F30_de22123389e38fcf3d56/result.json) |
| hudson_h2_d2_s4201 | 58.73970720 | 58.67765539 | +0.1056% | 8.58081% | 8.81300% | +0.23219 | False | False | False | [F30_d362368fa80b3ca35a9f](runs/F30_d362368fa80b3ca35a9f/result.json) / [F30_f034a0beb06a6efce3cc](runs/F30_f034a0beb06a6efce3cc/result.json) |

J 和 Pd 来自按 J、重复序号排序选出的同一个中位代表运行。全部重复保留在 [逐次对照](F30/comparison.csv)。

每个配对需至少 3/4 实例达到 0.5% J 相对改善，两地区各至少一例，任一实例的 J 退化不得超出相对容差 1e-8，终点 Pd 降幅不得超过 0.5 个百分点。

## 4. 机制证据

| 实例 / 方法 / 槽 | 展开 | 最大展开 tick | 末两 tick 展开 | 终端生成事件 | OPEN 计数 / tick 范围 | 下层首次 / 最终改善秒·来源 | 外层可接替时刻 / 接纳决定 | 原始记录 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lake_h2_d1_s3101 / C0 / 0 | 74982 | 48 | 69227 | 483941 | 34924 / 1–48 | 1.098·search / 1.146·search | 0.000 / accepted | [F30_5b4c442b35b5350ca094](runs/F30_5b4c442b35b5350ca094/result.json) |
| lake_h2_d1_s3101 / C1 / 0 | 10963 | 48 | 9352 | 65020 | 10551 / 1–48 | 1.118·search / 1.166·search | 0.000 / accepted | [F30_a65069321fc0f385fcdb](runs/F30_a65069321fc0f385fcdb/result.json) |
| lake_h2_d1_s3101 / C1 / 1 | 14440 | 48 | 13012 | 90495 | 9018 / 12–48 | — | 102.204 / no_strict_J_improvement | [F30_a65069321fc0f385fcdb](runs/F30_a65069321fc0f385fcdb/result.json) |
| lake_h2_d1_s3101 / C1 / 2 | 14370 | 48 | 12993 | 90361 | 8664 / 22–48 | — | 191.625 / no_strict_J_improvement | [F30_a65069321fc0f385fcdb](runs/F30_a65069321fc0f385fcdb/result.json) |
| lake_h2_d1_s3101 / C1 / 3 | 15561 | 48 | 14364 | 99849 | 7388 / 31–48 | — | 282.632 / no_strict_J_improvement | [F30_a65069321fc0f385fcdb](runs/F30_a65069321fc0f385fcdb/result.json) |
| lake_h2_d1_s3101 / C1 / 4 | 15755 | 48 | 15063 | 108002 | 1977 / 42–48 | — | 377.473 / no_strict_J_improvement | [F30_a65069321fc0f385fcdb](runs/F30_a65069321fc0f385fcdb/result.json) |
| lake_h2_d1_s3101 / C0_M / 0 | 73996 | 48 | 68277 | 477109 | 34705 / 1–48 | 1.124·search / 1.177·search | 0.000 / accepted | [F30_06da3ac7286ecbd7a002](runs/F30_06da3ac7286ecbd7a002/result.json) |
| lake_h2_d1_s3101 / C1_M / 0 | 10716 | 48 | 9112 | 63209 | 10487 / 1–48 | 1.106·search / 1.154·search | 0.000 / accepted | [F30_bae812538cc1fefce2d3](runs/F30_bae812538cc1fefce2d3/result.json) |
| lake_h2_d1_s3101 / C1_M / 1 | 13787 | 48 | 12389 | 85908 | 8862 / 12–48 | — | 102.213 / no_strict_J_improvement | [F30_bae812538cc1fefce2d3](runs/F30_bae812538cc1fefce2d3/result.json) |
| lake_h2_d1_s3101 / C1_M / 2 | 14224 | 48 | 12839 | 89107 | 8673 / 22–48 | — | 191.636 / no_strict_J_improvement | [F30_bae812538cc1fefce2d3](runs/F30_bae812538cc1fefce2d3/result.json) |
| lake_h2_d1_s3101 / C1_M / 3 | 15090 | 48 | 13902 | 96386 | 7297 / 31–48 | — | 282.648 / no_strict_J_improvement | [F30_bae812538cc1fefce2d3](runs/F30_bae812538cc1fefce2d3/result.json) |
| lake_h2_d1_s3101 / C1_M / 4 | 15458 | 48 | 14753 | 105441 | 2043 / 42–48 | — | 377.488 / no_strict_J_improvement | [F30_bae812538cc1fefce2d3](runs/F30_bae812538cc1fefce2d3/result.json) |
| lake_h2_d2_s3201 / C0 / 0 | 71779 | 48 | 62964 | 443116 | 59089 / 1–48 | 1.285·completion / 1.334·search | 0.000 / accepted | [F30_88a4e6e4c3a0796ef8b2](runs/F30_88a4e6e4c3a0796ef8b2/result.json) |
| lake_h2_d2_s3201 / C1 / 0 | 7984 | 48 | 6009 | 41886 | 13997 / 1–48 | 1.419·completion / 1.473·search | 0.000 / accepted | [F30_88bfeb10ba8bbc420df2](runs/F30_88bfeb10ba8bbc420df2/result.json) |
| lake_h2_d2_s3201 / C1 / 1 | 8215 | 48 | 6314 | 44064 | 13436 / 12–48 | — | 100.623 / no_strict_J_improvement | [F30_88bfeb10ba8bbc420df2](runs/F30_88bfeb10ba8bbc420df2/result.json) |
| lake_h2_d2_s3201 / C1 / 2 | 9194 | 48 | 7284 | 50874 | 13483 / 22–48 | — | 191.647 / no_strict_J_improvement | [F30_88bfeb10ba8bbc420df2](runs/F30_88bfeb10ba8bbc420df2/result.json) |
| lake_h2_d2_s3201 / C1 / 3 | 11002 | 48 | 9376 | 65576 | 11438 / 31–48 | — | 281.055 / no_strict_J_improvement | [F30_88bfeb10ba8bbc420df2](runs/F30_88bfeb10ba8bbc420df2/result.json) |
| lake_h2_d2_s3201 / C1 / 4 | 11818 | 48 | 10926 | 77214 | 5511 / 42–48 | — | 375.903 / no_strict_J_improvement | [F30_88bfeb10ba8bbc420df2](runs/F30_88bfeb10ba8bbc420df2/result.json) |
| lake_h2_d2_s3201 / C0_M / 0 | 54431 | 48 | 47341 | 333213 | 47647 / 1–48 | 1.420·completion / 1.475·search | 0.000 / accepted | [F30_4ae59e3cac6bc5b59217](runs/F30_4ae59e3cac6bc5b59217/result.json) |
| lake_h2_d2_s3201 / C1_M / 0 | 9614 | 48 | 7434 | 51940 | 15356 / 1–48 | 1.383·completion / 1.437·search | 0.000 / accepted | [F30_17a4c190f5aaa301e793](runs/F30_17a4c190f5aaa301e793/result.json) |
| lake_h2_d2_s3201 / C1_M / 1 | 10560 | 48 | 8370 | 58540 | 15376 / 12–48 | — | 100.641 / no_strict_J_improvement | [F30_17a4c190f5aaa301e793](runs/F30_17a4c190f5aaa301e793/result.json) |
| lake_h2_d2_s3201 / C1_M / 2 | 11215 | 48 | 8983 | 62810 | 15694 / 22–48 | — | 191.649 / no_strict_J_improvement | [F30_17a4c190f5aaa301e793](runs/F30_17a4c190f5aaa301e793/result.json) |
| lake_h2_d2_s3201 / C1_M / 3 | 12884 | 48 | 11044 | 77432 | 12744 / 31–48 | — | 281.070 / no_strict_J_improvement | [F30_17a4c190f5aaa301e793](runs/F30_17a4c190f5aaa301e793/result.json) |
| lake_h2_d2_s3201 / C1_M / 4 | 14895 | 48 | 13805 | 97464 | 6720 / 42–48 | — | 375.907 / no_strict_J_improvement | [F30_17a4c190f5aaa301e793](runs/F30_17a4c190f5aaa301e793/result.json) |
| hudson_h2_d1_s4101 / C0 / 0 | 18705 | 59 | 10091 | 72417 | 58516 / 1–59 | 25.081·search / 26.215·search | 0.000 / accepted | [F30_d0424f9f71624167360c](runs/F30_d0424f9f71624167360c/result.json) |
| hudson_h2_d1_s4101 / C1 / 0 | 1517 | 19 | 0 | 0 | 10616 / 1–20 | — | 0.000 / no_strict_J_improvement | [F30_43a9e6328e7a23b77e6e](runs/F30_43a9e6328e7a23b77e6e/result.json) |
| hudson_h2_d1_s4101 / C1 / 1 | 2985 | 49 | 0 | 0 | 20888 / 14–51 | — | 561.385 / no_strict_J_improvement | [F30_43a9e6328e7a23b77e6e](runs/F30_43a9e6328e7a23b77e6e/result.json) |
| hudson_h2_d1_s4101 / C1 / 2 | 4789 | 59 | 1841 | 13199 | 20320 / 26–59 | 4.926·completion / 5.060·search | 1116.986 / accepted | [F30_43a9e6328e7a23b77e6e](runs/F30_43a9e6328e7a23b77e6e/result.json) |
| hudson_h2_d1_s4101 / C1 / 3 | 13757 | 59 | 12347 | 88732 | 7561 / 39–59 | — | 1710.922 / no_strict_J_improvement | [F30_43a9e6328e7a23b77e6e](runs/F30_43a9e6328e7a23b77e6e/result.json) |
| hudson_h2_d1_s4101 / C1 / 4 | 15913 | 59 | 15222 | 109286 | 2100 / 50–59 | — | 2231.448 / no_strict_J_improvement | [F30_43a9e6328e7a23b77e6e](runs/F30_43a9e6328e7a23b77e6e/result.json) |
| hudson_h2_d1_s4101 / C0_M / 0 | 34020 | 59 | 26455 | 190236 | 47872 / 1–59 | 19.018·search / 20.132·search | 0.000 / accepted | [F30_712a396f350e00081925](runs/F30_712a396f350e00081925/result.json) |
| hudson_h2_d1_s4101 / C1_M / 0 | 1539 | 22 | 0 | 0 | 10745 / 1–23 | — | 0.000 / no_strict_J_improvement | [F30_de22123389e38fcf3d56](runs/F30_de22123389e38fcf3d56/result.json) |
| hudson_h2_d1_s4101 / C1_M / 1 | 2939 | 49 | 0 | 0 | 20566 / 14–51 | — | 561.399 / no_strict_J_improvement | [F30_de22123389e38fcf3d56](runs/F30_de22123389e38fcf3d56/result.json) |
| hudson_h2_d1_s4101 / C1_M / 2 | 5121 | 59 | 2162 | 15525 | 20312 / 26–59 | 4.837·completion / 4.966·search | 1117.000 / accepted | [F30_de22123389e38fcf3d56](runs/F30_de22123389e38fcf3d56/result.json) |
| hudson_h2_d1_s4101 / C1_M / 3 | 13014 | 59 | 11647 | 83539 | 7376 / 39–59 | — | 1710.935 / no_strict_J_improvement | [F30_de22123389e38fcf3d56](runs/F30_de22123389e38fcf3d56/result.json) |
| hudson_h2_d1_s4101 / C1_M / 4 | 15463 | 59 | 14776 | 105819 | 2096 / 50–59 | — | 2231.460 / no_strict_J_improvement | [F30_de22123389e38fcf3d56](runs/F30_de22123389e38fcf3d56/result.json) |
| hudson_h2_d2_s4201 / C0 / 0 | 99558 | 59 | 96361 | 682772 | 323 / 1–59 | 0.149·search / 0.660·search | 0.000 / accepted | [F30_d362368fa80b3ca35a9f](runs/F30_d362368fa80b3ca35a9f/result.json) |
| hudson_h2_d2_s4201 / C1 / 0 | 17908 | 59 | 17278 | 119818 | 332 / 1–59 | 0.153·search / 0.710·search | 0.000 / accepted | [F30_345be821a234e73f4a38](runs/F30_345be821a234e73f4a38/result.json) |
| hudson_h2_d2_s4201 / C1 / 1 | 17958 | 59 | 17338 | 120203 | 253 / 14–59 | — | 564.646 / no_strict_J_improvement | [F30_345be821a234e73f4a38](runs/F30_345be821a234e73f4a38/result.json) |
| hudson_h2_d2_s4201 / C1 / 2 | 18643 | 59 | 18011 | 124831 | 191 / 26–59 | — | 1142.714 / no_strict_J_improvement | [F30_345be821a234e73f4a38](runs/F30_345be821a234e73f4a38/result.json) |
| hudson_h2_d2_s4201 / C1 / 3 | 18115 | 59 | 17510 | 121336 | 106 / 39–59 | — | 1701.604 / no_strict_J_improvement | [F30_345be821a234e73f4a38](runs/F30_345be821a234e73f4a38/result.json) |
| hudson_h2_d2_s4201 / C1 / 4 | 19114 | 59 | 18492 | 128179 | 37 / 51–59 | 0.012·completion / 0.012·completion | 2260.494 / accepted | [F30_345be821a234e73f4a38](runs/F30_345be821a234e73f4a38/result.json) |
| hudson_h2_d2_s4201 / C0_M / 0 | 93001 | 59 | 89750 | 631736 | 334 / 1–59 | 0.149·search / 0.632·search | 0.000 / accepted | [F30_3d937ebe8de5f861e408](runs/F30_3d937ebe8de5f861e408/result.json) |
| hudson_h2_d2_s4201 / C1_M / 0 | 17627 | 59 | 16895 | 114952 | 332 / 1–59 | 0.153·search / 0.649·search | 0.000 / accepted | [F30_f034a0beb06a6efce3cc](runs/F30_f034a0beb06a6efce3cc/result.json) |
| hudson_h2_d2_s4201 / C1_M / 1 | 17865 | 59 | 17130 | 116599 | 254 / 14–59 | — | 564.657 / no_strict_J_improvement | [F30_f034a0beb06a6efce3cc](runs/F30_f034a0beb06a6efce3cc/result.json) |
| hudson_h2_d2_s4201 / C1_M / 2 | 18201 | 59 | 17462 | 118846 | 193 / 26–59 | — | 1142.727 / no_strict_J_improvement | [F30_f034a0beb06a6efce3cc](runs/F30_f034a0beb06a6efce3cc/result.json) |
| hudson_h2_d2_s4201 / C1_M / 3 | 18213 | 59 | 17487 | 118999 | 100 / 39–58 | — | 1701.616 / no_strict_J_improvement | [F30_f034a0beb06a6efce3cc](runs/F30_f034a0beb06a6efce3cc/result.json) |
| hudson_h2_d2_s4201 / C1_M / 4 | 18355 | 59 | 17631 | 119997 | 41 / 51–59 | 0.011·completion / 0.011·completion | 2260.508 / accepted | [F30_f034a0beb06a6efce3cc](runs/F30_f034a0beb06a6efce3cc/result.json) |

F30 表使用各实例每方法的中位路线代表。内层记录与原模型审计后的外层接纳是两个时刻。终端生成数按事件计，OPEN 按实际堆中元素计。[所有内层候选](F30/incumbent_history.csv) · [所有阶段和时刻](F30/phases.csv)

- C0_M_vs_C0 有 0 例严格改善、0 例退化。Lake 两例的 J 相对变化为 lake_h2_d1_s3101 +0.0000%、lake_h2_d2_s3201 +0.0000%。
- C1_M_vs_C1 有 0 例严格改善、0 例退化。Lake 两例的 J 相对变化为 lake_h2_d1_s3101 +0.0000%、lake_h2_d2_s3201 +0.0000%。
- C1_M_vs_C0_M 有 1 例严格改善、1 例退化。Lake 两例的 J 相对变化为 lake_h2_d1_s3101 +0.0000%、lake_h2_d2_s3201 +0.0000%。
- C1_M_vs_C0 有 1 例严格改善、1 例退化。Lake 两例的 J 相对变化为 lake_h2_d1_s3101 +0.0000%、lake_h2_d2_s3201 +0.0000%。
- 邻近权重、终端集中、覆盖率高、提前找到 incumbent 或少展开本身都不能推出最优。索引开销、重新入队、按展开次数触发补全和可接替时刻会共同改变固定预算下的路线。

## 5. 阶段执行与资源

| 阶段 / 方法 | 实例×重复 | 算法秒中位 / 最大 | CPU 秒中位 | 进程秒中位 | RSS 最大 MiB | 独立审计秒中位 | 最大返回越界秒 | 在线接纳 | 停止原因 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D0 / D0 | 4 | 29.837 / 29.863 | 29.414 | 31.677 | 480.133 | 0.011 | 0.000000 | 0 | max_seconds×4 |
| F30 / C0 | 12 | 29.829 / 29.887 | 29.562 | 31.244 | 429.172 | 0.011 | 0.000000 | 0 | max_seconds×12 |
| F30 / C0_M | 12 | 29.834 / 29.887 | 29.656 | 31.198 | 504.590 | 0.011 | 0.000000 | 0 | max_seconds×12 |
| F30 / C1 | 12 | 28.842 / 28.906 | 28.625 | 30.290 | 200.246 | 0.030 | 0.000000 | 6 | max_seconds×60 |
| F30 / C1_M | 12 | 28.900 / 28.980 | 28.695 | 30.339 | 278.777 | 0.031 | 0.000000 | 6 | max_seconds×60 |

历史共同路线来自冻结 S30，复制、原模型重放和索引工作均计入本轮各方法。进程额外记入加载和独立审计。内层 incumbent 日志用于描述搜索时刻。

### 路线来源与接纳

| 阶段 / 方法 | 完成运行 | 最终已执行路径来源 | 内层 incumbent 更新来源 | 阶段决定 / 次数 |
| --- | --- | --- | --- | --- |
| D0 / D0 | 4 | C0_stage_0×4 | initial_route×4, search×37, completion×1 | accepted×4 |
| F30 / C0 | 12 | C0_stage_0×12 | initial_route×12, search×111, completion×3 | accepted×12 |
| F30 / C0_M | 12 | C0_stage_0×12 | initial_route×12, search×111, completion×3 | accepted×12 |
| F30 / C1 | 12 | C1_stage_0×6, C1_stage_2×3, C1_stage_4×3 | initial_route×60, completion×9, search×87 | accepted×15, no_strict_J_improvement×45 |
| F30 / C1_M | 12 | C1_stage_0×6, C1_stage_4×3, C1_stage_2×3 | initial_route×60, completion×9, search×87 | accepted×15, no_strict_J_improvement×45 |

`common_seed` 来自共同初始路线。阶段来源表示最后一次接纳。内层 incumbent 来源按事件计。

### F30 合并工作量

| 方法 | 非终止 child | 可合并 | 实际丢弃 | 代表更新 | 陈旧跳过 | 容量拒绝 | 键 payload 峰值 MiB | 查找秒合计 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C0_M | 1192304 | 14929 | 14929 | 12105 | 18 | 968674 | 62.750 | 7.634 |
| C1_M | 1273516 | 34006 | 34006 | 19327 | 102 | 256663 | 62.750 | 8.688 |

Hudson 4101 在 D0 影子轨迹中记录 5,566 次可合并机会，F30 的 C0_M 三次运行实际丢弃数中位数为 25。Hudson 4201 中，C0_M 和 C1_M 的对应中位数分别为 4,846 和 10,006。影子诊断保留原搜索状态，启用合并会改变搜索队列和预算内展开序列，因此 D0 机会数不能直接作为 F30 的预计去重数。

## 6. 结论与适用边界

本固定配置未达到滚动候选的双门槛，结束本轮。
通用状态合并、滚动内部的合并、净滚动，以及相对原 C0 的整体改善按四个配对单列。
局部严格支配适用于冻结模型的未来状态。实际墙钟结果取决于索引、堆顺序和重新展开。实验依据四个已见案例，暂未建立新日期泛化、同质量加速或全局及 ε 最优证书。

证据链接

- D0。[REPORT.md](D0/REPORT.md) · [summary.json](D0/summary.json) · [comparison.csv](D0/comparison.csv) · [instance_comparison.csv](D0/instance_comparison.csv) · [merge_diagnostics.csv](D0/merge_diagnostics.csv) · [phases.csv](D0/phases.csv) · [survival.csv](D0/survival.csv) · [incumbent_history.csv](D0/incumbent_history.csv)
- F30。[REPORT.md](F30/REPORT.md) · [summary.json](F30/summary.json) · [comparison.csv](F30/comparison.csv) · [instance_comparison.csv](F30/instance_comparison.csv) · [merge_diagnostics.csv](F30/merge_diagnostics.csv) · [phases.csv](F30/phases.csv) · [survival.csv](F30/survival.csv) · [incumbent_history.csv](F30/incumbent_history.csv)
- [原始运行目录](runs)
- [诊断图](figures)
- [报告汇总脚本](reproduce/rolling_merge_analysis.py) · [绘图脚本](reproduce/rolling_merge_figures.py) · [命令与日志](commands)
