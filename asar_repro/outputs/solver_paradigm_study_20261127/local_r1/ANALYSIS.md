# 完整路线求解实验分析

本地 `local_r1` 批次完成了 193 项冻结任务。A 的 18 个完整诊断实例均取得数值闭合，9 个 tiny 的 count 与独立 DFS 的 J 差为 0。B5 和 B30 中，ILS 与 CEM 在 Lake Ontario、Hudson 的全部种子均未达到预设 J 目标，也未产生严格优于历史参考的路线。C300 的筛选结果为 `not_triggered`。

[阶段与指标汇总](REPORT.md) · [逐次指标](comparison.csv) · [结构化判定](summary.json)

## 执行身份

- 冻结源码提交 `a349daffc0c3b3768643e84e4d740c1003a5f73b`，冻结时间 `2026-11-27T09:47:27.415320+00:00`。
- [冻结协议](protocol.json) SHA-256 `d3e335977f93c3d9640fb286c2f02cc953a352aef8b827d2cbba30333342c6a5`。
- 配置 SHA-256 `d85d881375e1969b212136f48543da6ef4e9274508015b98b976e6be4e3fbf7f`。
- 解释器 `c:\users\35448\.conda\envs\maritime-sar\python.exe`，Python `3.11.18`。
- Windows-10-10.0.26200-SP0，32 个逻辑 CPU。
- numpy 2.4.6，scipy 1.17.1，pytest 9.2.0，psutil 7.2.2，内嵌 HiGHS `1.12.0`。
- 数值库线程环境 `OMP_NUM_THREADS=1`，`OPENBLAS_NUM_THREADS=1`，`MKL_NUM_THREADS=1`，`NUMEXPR_NUM_THREADS=1`，`VECLIB_MAXIMUM_THREADS=1`。
- P0 的 67 项用例及 6 个子测通过，失败、错误和跳过均为 0。[原始记录](validation/20261127T094721638490Z/result.json) · [pytest 日志](validation/20261127T094721638490Z/stdout.log)

| 档案 | 粒子 SHA-256 | Metadata SHA-256 | PT J / 历史参考 J |
|---|---|---|---|
| Lake Ontario | `8b30a87e543f1b33c39e70e1d0054e1750ec046ba2e0b627dd311d9945749456` | `1e96ecea2547ca918dd068b7f86a3d4b680cdc89ad6814b1132ca80cdc5e89fc` | 20.477608336 / 17.264874448 |
| Hudson | `6ed4ca52ecccc9369adae67f7da75477057317599869389224b6ffb488babfb6` | `89046a2d5b74371b26b558df66bc6646ba54f58f91e0cc0389e5b8bc2ff47bac` | 25.293460991 / 20.386109349 |

## 阶段与证据状态

| 阶段 | 状态 | 有效 / 计划 | 异常或待记录 |
|---|---|---:|---:|
| A | `complete` | 117 / 117 | 0 |
| B5 | `complete` | 38 / 38 | 0 |
| B30 | `complete` | 38 / 38 | 0 |
| C300 | `not_triggered` | 0 / 0 | 0 |


## A　小中规模最优差距

A 门槛 **通过**。 J 越低越好。数值下界只适用于对应的完整诊断实例。区间上端 U 取该题所有有效重放路线的最小 J。

| 实例 | 网格 / T | 独立 DFS J* | count 状态 | count L / J | paper / zero / mass / ILS / CEM J | U | 区间宽度/U | paper 相对 J* 差距 | 门槛 |
|---|---|---:|---|---:|---|---:|---:|---:|---|
| `medium_order_0` | 7×7 / 12 | — | `optimal_numeric` | 9.56281200 / 9.56281200 | 9.58262194 / 9.56281200 / 9.56281200 / 9.56281200 / 9.58262194 | 9.56281200 | 0.000% | 0.207% | 通过 |
| `medium_order_1` | 7×7 / 14 | — | `optimal_numeric` | 10.01255576 / 10.01255576 | 10.01255576 / 10.01255576 / 10.01255576 / 10.01255576 / 10.87841970 | 10.01255576 | 0.000% | 0.000% | 通过 |
| `medium_order_2` | 7×7 / 16 | — | `optimal_numeric` | 11.97972718 / 11.97972718 | 11.97972718 / 11.97972718 / 11.97972718 / 11.97972718 / 12.68498752 | 11.97972718 | 0.000% | 0.000% | 通过 |
| `medium_repeat_0` | 7×7 / 12 | — | `optimal_numeric` | 3.49300800 / 3.49300800 | 3.49300800 / 3.49300800 / 3.49300800 / 3.49300800 / 3.49300800 | 3.49300800 | 0.000% | 0.000% | 通过 |
| `medium_repeat_1` | 7×7 / 14 | — | `optimal_numeric` | 3.34183664 / 3.34183664 | 3.34183664 / 3.34183664 / 3.34183664 / 3.34183664 / 3.34183664 | 3.34183664 | 0.000% | 0.000% | 通过 |
| `medium_repeat_2` | 7×7 / 16 | — | `optimal_numeric` | 3.61922224 / 3.61922224 | 3.61922224 / 3.61922224 / 3.61922224 / 3.61922224 / 3.61922224 | 3.61922224 | 0.000% | 0.000% | 通过 |
| `medium_transfer_0` | 7×7 / 12 | — | `optimal_numeric` | 8.13626314 / 8.13626314 | 8.13626314 / 8.13626314 / 8.13626314 / 8.13626314 / 8.13626314 | 8.13626314 | 0.000% | 0.000% | 通过 |
| `medium_transfer_1` | 7×7 / 14 | — | `optimal_numeric` | 8.59621928 / 8.59621928 | 8.59621928 / 8.59621928 / 8.59621928 / 8.59621928 / 8.59621928 | 8.59621928 | 0.000% | 0.000% | 通过 |
| `medium_transfer_2` | 7×7 / 16 | — | `optimal_numeric` | 8.77252000 / 8.77252000 | 8.77252000 / 8.77252000 / 8.77252000 / 8.77252000 / 9.83937280 | 8.77252000 | 0.000% | 0.000% | 通过 |
| `tiny_order_0` | 4×4 / 4 | 3.25541200 | `optimal_numeric` | 3.25541200 / 3.25541200 | 3.25541200 / 3.25541200 / 3.25541200 / 3.25541200 / 3.25541200 | 3.25541200 | 0.000% | 0.000% | 通过 |
| `tiny_order_1` | 4×4 / 5 | 3.90020000 | `optimal_numeric` | 3.90020000 / 3.90020000 | 3.90020000 / 3.90020000 / 3.90020000 / 3.90020000 / 3.90020000 | 3.90020000 | 0.000% | 0.000% | 通过 |
| `tiny_order_2` | 4×4 / 6 | 4.65060000 | `optimal_numeric` | 4.65060000 / 4.65060000 | 4.65060000 / 4.65060000 / 4.65060000 / 4.65060000 / 4.65060000 | 4.65060000 | 0.000% | 0.000% | 通过 |
| `tiny_repeat_0` | 4×4 / 4 | 1.78480000 | `optimal_numeric` | 1.78480000 / 1.78480000 | 1.78480000 / 1.78480000 / 1.78480000 / 1.78480000 / 1.78480000 | 1.78480000 | 0.000% | 0.000% | 通过 |
| `tiny_repeat_1` | 4×4 / 5 | 1.90932800 | `optimal_numeric` | 1.90932800 / 1.90932800 | 1.90932800 / 1.90932800 / 1.90932800 / 1.90932800 / 1.90932800 | 1.90932800 | 0.000% | 0.000% | 通过 |
| `tiny_repeat_2` | 4×4 / 6 | 2.05944000 | `optimal_numeric` | 2.05944000 / 2.05944000 | 2.05944000 / 2.05944000 / 2.05944000 / 2.05944000 / 2.05944000 | 2.05944000 | 0.000% | 0.000% | 通过 |
| `tiny_transfer_0` | 4×4 / 4 | 3.06400000 | `optimal_numeric` | 3.06400000 / 3.06400000 | 3.06400000 / 3.06400000 / 3.06400000 / 3.06400000 / 3.06400000 | 3.06400000 | 0.000% | 0.000% | 通过 |
| `tiny_transfer_1` | 4×4 / 5 | 3.74420000 | `optimal_numeric` | 3.74420000 / 3.74420000 | 3.74420000 / 3.74420000 / 3.74420000 / 3.74420000 / 3.74420000 | 3.74420000 | 0.000% | 0.000% | 通过 |
| `tiny_transfer_2` | 4×4 / 6 | 3.97200000 | `optimal_numeric` | 3.97200000 / 3.97200000 | 3.97200000 / 3.97200000 / 3.97200000 / 3.97200000 / 3.97200000 | 3.97200000 | 0.000% | 0.000% | 通过 |

有效实例中比 paper 严格降低 J 的次数 anytime_zero 1，anytime_mass 1，ils 1，cem 0。
出现改善的实例 anytime_zero `medium_order_0`，anytime_mass `medium_order_0`，ils `medium_order_0`。
达到 DFS 已知值或完整域数值闭合值的次数 paper_baseline 17，anytime_zero 18，anytime_mass 18，ils 18，cem 14。
区间宽度表示尚未排除的空间。A 每法每例仅运行一次。

## B5　真实历史档案对照

各方法在同一冻结 PT 上开始，完整重放计入方法预算。达到时间只表示首次在预算内完成原评分的时刻。有删失值的分组只报告达到者中位数并标星，比较范围为本机本批。

| 档案 | 方法 | 有效 / 计划 | J 中位数 [最小, 最大] | Pd 中位数 | 达到数 / 有效 | 达到时间中位数 s | 方法 / 进程中位耗时 s | 峰值 RSS 中位 MiB |
|---|---|---:|---|---:|---:|---:|---:|---:|
| Hudson | `anytime_mass` | 3 / 3 | 20.386109349 [20.386109349, 20.386109349] | 0.908583112 | 3 / 3 | 1.242699 | 5.0277 / 6.0768 | 290.96 |
| Hudson | `anytime_zero` | 3 / 3 | 20.386109349 [20.386109349, 20.386109349] | 0.908583112 | 3 / 3 | 1.219299 | 5.0320 / 6.0760 | 303.63 |
| Hudson | `cem` | 5 / 5 | 25.228826722 [24.158311104, 25.293460991] | 0.797953035 | 0 / 5 | — | 5.0001 / 6.1771 | 78.98 |
| Hudson | `ils` | 5 / 5 | 21.828685669 [21.586602917, 21.996635913] | 0.879476831 | 0 / 5 | — | 5.0001 / 6.1809 | 79.18 |
| Hudson | `paper_baseline` | 3 / 3 | 20.390881327 [20.390881327, 20.390881327] | 0.906729745 | 3 / 3 | 1.287945 | 1.2879 / 2.4347 | 145.33 |
| Lake Ontario | `anytime_mass` | 3 / 3 | 17.264874448 [17.264874448, 17.264874448] | 0.897364416 | 3 / 3 | 2.291747 | 5.0198 / 6.1744 | 183.44 |
| Lake Ontario | `anytime_zero` | 3 / 3 | 17.264874448 [17.264874448, 17.264874448] | 0.897364416 | 3 / 3 | 2.180636 | 5.0205 / 6.1751 | 196.40 |
| Lake Ontario | `cem` | 5 / 5 | 19.829489240 [19.576468495, 20.060912575] | 0.798456766 | 0 / 5 | — | 5.0004 / 6.0784 | 77.45 |
| Lake Ontario | `ils` | 5 / 5 | 18.055910936 [17.991382847, 18.127802500] | 0.883112219 | 0 / 5 | — | 5.0002 / 6.1820 | 78.27 |
| Lake Ontario | `paper_baseline` | 3 / 3 | 17.293894155 [17.293894155, 17.293894155] | 0.897370419 | 0 / 3 | — | 0.9203 / 2.0320 | 95.19 |

逐次路线、耗时超额与峰值见 [comparison.csv](comparison.csv)。

| 方法 | Lake / Hudson 相对廉价对照 J 收益 | Lake / Hudson 对 zero 与 mass 的时间比 | Q | T | 状态 |
|---|---:|---|---|---|---|
| `ils` | -4.582% / -7.076% | 删失 / 删失 | 未通过 | 未通过 | `screen_not_passed` |
| `cem` | -14.855% / -23.755% | 删失 / 删失 | 未通过 | 未通过 | `screen_not_passed` |

| 档案 / 方法 | seed / 重复序号 | J / Pd | 达到时间 s | 方法耗时 s | 方法停止状态 | 原始记录 |
|---|---|---:|---:|---:|---|---|
| Hudson / `anytime_mass` | 0 / 0 | 20.386109349 / 0.908583112 | 1.250379 | 5.0267 | `budget_exceeded` / `max_seconds` | [B5_41a5b76eec7277cab0f9](runs/B5_41a5b76eec7277cab0f9/result.json) |
| Hudson / `anytime_mass` | 0 / 1 | 20.386109349 / 0.908583112 | 1.225990 | 5.0368 | `budget_exceeded` / `max_seconds` | [B5_11ad735f651733b7abc9](runs/B5_11ad735f651733b7abc9/result.json) |
| Hudson / `anytime_mass` | 0 / 2 | 20.386109349 / 0.908583112 | 1.242699 | 5.0277 | `budget_exceeded` / `max_seconds` | [B5_3a1b4f5f7ca5412606bd](runs/B5_3a1b4f5f7ca5412606bd/result.json) |
| Hudson / `anytime_zero` | 0 / 0 | 20.386109349 / 0.908583112 | 1.200239 | 5.0360 | `budget_exceeded` / `max_seconds` | [B5_1866feb9a9ab3403ae40](runs/B5_1866feb9a9ab3403ae40/result.json) |
| Hudson / `anytime_zero` | 0 / 1 | 20.386109349 / 0.908583112 | 1.301554 | 5.0320 | `budget_exceeded` / `max_seconds` | [B5_24b77281aa0264293ce7](runs/B5_24b77281aa0264293ce7/result.json) |
| Hudson / `anytime_zero` | 0 / 2 | 20.386109349 / 0.908583112 | 1.219299 | 5.0310 | `budget_exceeded` / `max_seconds` | [B5_16975cdcd0fa69fe56c5](runs/B5_16975cdcd0fa69fe56c5/result.json) |
| Hudson / `cem` | 20261127 / 0 | 24.158311104 / 0.772638048 | 删失 5.0000 | 5.0001 | `budget_exceeded` / `max_seconds` | [B5_95a77fab2a67f92e3335](runs/B5_95a77fab2a67f92e3335/result.json) |
| Hudson / `cem` | 20261128 / 1 | 25.228826722 / 0.768107591 | 删失 5.0000 | 5.0001 | `budget_exceeded` / `max_seconds` | [B5_f054f78d5cf005a22a9a](runs/B5_f054f78d5cf005a22a9a/result.json) |
| Hudson / `cem` | 20261129 / 2 | 24.523058511 / 0.833635106 | 删失 5.0000 | 5.0002 | `budget_exceeded` / `max_seconds` | [B5_d10392fee765385faf1c](runs/B5_d10392fee765385faf1c/result.json) |
| Hudson / `cem` | 20261130 / 3 | 25.293460991 / 0.817636947 | 删失 5.0000 | 5.0001 | `budget_exceeded` / `max_seconds` | [B5_064ca2d9b5ddceee03cc](runs/B5_064ca2d9b5ddceee03cc/result.json) |
| Hudson / `cem` | 20261201 / 4 | 25.259533778 / 0.797953035 | 删失 5.0000 | 5.0001 | `budget_exceeded` / `max_seconds` | [B5_ab792801a946628cf7b3](runs/B5_ab792801a946628cf7b3/result.json) |
| Hudson / `ils` | 20261127 / 0 | 21.586602917 / 0.887081778 | 删失 5.0000 | 5.0001 | `budget_exceeded` / `max_seconds` | [B5_1369545a74c186977c69](runs/B5_1369545a74c186977c69/result.json) |
| Hudson / `ils` | 20261128 / 1 | 21.996635913 / 0.858242462 | 删失 5.0000 | 5.0001 | `budget_exceeded` / `max_seconds` | [B5_d4b7059b652b29a756ba](runs/B5_d4b7059b652b29a756ba/result.json) |
| Hudson / `ils` | 20261129 / 2 | 21.735944210 / 0.880379670 | 删失 5.0000 | 5.0001 | `budget_exceeded` / `max_seconds` | [B5_afbeab33a5a4cfc47b58](runs/B5_afbeab33a5a4cfc47b58/result.json) |
| Hudson / `ils` | 20261130 / 3 | 21.933783508 / 0.879476831 | 删失 5.0000 | 5.0002 | `budget_exceeded` / `max_seconds` | [B5_5e189684473fdc9db99e](runs/B5_5e189684473fdc9db99e/result.json) |
| Hudson / `ils` | 20261201 / 4 | 21.828685669 / 0.875855979 | 删失 5.0000 | 5.0001 | `budget_exceeded` / `max_seconds` | [B5_530659e6f12b1aa2203a](runs/B5_530659e6f12b1aa2203a/result.json) |
| Hudson / `paper_baseline` | 0 / 0 | 20.390881327 / 0.906729745 | 1.281085 | 1.2811 | `completed` | [B5_5dcf092b15e91519458c](runs/B5_5dcf092b15e91519458c/result.json) |
| Hudson / `paper_baseline` | 0 / 1 | 20.390881327 / 0.906729745 | 1.287945 | 1.2879 | `completed` | [B5_81948e498a241ec0c17c](runs/B5_81948e498a241ec0c17c/result.json) |
| Hudson / `paper_baseline` | 0 / 2 | 20.390881327 / 0.906729745 | 1.321019 | 1.3210 | `completed` | [B5_0fbdaf2a17483b3929a9](runs/B5_0fbdaf2a17483b3929a9/result.json) |
| Lake Ontario / `anytime_mass` | 0 / 0 | 17.264874448 / 0.897364416 | 2.285305 | 5.0172 | `budget_exceeded` / `max_seconds` | [B5_9bb699c413e5685959d1](runs/B5_9bb699c413e5685959d1/result.json) |
| Lake Ontario / `anytime_mass` | 0 / 1 | 17.264874448 / 0.897364416 | 2.322264 | 5.0198 | `budget_exceeded` / `max_seconds` | [B5_969e9eea464527d7bd31](runs/B5_969e9eea464527d7bd31/result.json) |
| Lake Ontario / `anytime_mass` | 0 / 2 | 17.264874448 / 0.897364416 | 2.291747 | 5.0198 | `budget_exceeded` / `max_seconds` | [B5_8e070851c546ac0e5aa3](runs/B5_8e070851c546ac0e5aa3/result.json) |
| Lake Ontario / `anytime_zero` | 0 / 0 | 17.264874448 / 0.897364416 | 2.208163 | 5.0205 | `budget_exceeded` / `max_seconds` | [B5_6a0ab3e553be384c5508](runs/B5_6a0ab3e553be384c5508/result.json) |
| Lake Ontario / `anytime_zero` | 0 / 1 | 17.264874448 / 0.897364416 | 2.174596 | 5.0203 | `budget_exceeded` / `max_seconds` | [B5_909d3d8009b28bacbe72](runs/B5_909d3d8009b28bacbe72/result.json) |
| Lake Ontario / `anytime_zero` | 0 / 2 | 17.264874448 / 0.897364416 | 2.180636 | 5.0216 | `budget_exceeded` / `max_seconds` | [B5_da3bed9638963f191d43](runs/B5_da3bed9638963f191d43/result.json) |
| Lake Ontario / `cem` | 20261127 / 0 | 19.576468495 / 0.798763930 | 删失 5.0000 | 5.0003 | `budget_exceeded` / `max_seconds` | [B5_bde383e33ce758fa46b3](runs/B5_bde383e33ce758fa46b3/result.json) |
| Lake Ontario / `cem` | 20261128 / 1 | 20.060912575 / 0.825913184 | 删失 5.0000 | 5.0005 | `budget_exceeded` / `max_seconds` | [B5_3532372e1b9914b9ae53](runs/B5_3532372e1b9914b9ae53/result.json) |
| Lake Ontario / `cem` | 20261129 / 2 | 19.829489240 / 0.783417552 | 删失 5.0000 | 5.0002 | `budget_exceeded` / `max_seconds` | [B5_a78c775204383c5e49a0](runs/B5_a78c775204383c5e49a0/result.json) |
| Lake Ontario / `cem` | 20261130 / 3 | 19.675779928 / 0.798456766 | 删失 5.0000 | 5.0004 | `budget_exceeded` / `max_seconds` | [B5_53c3a216f774c1f0596b](runs/B5_53c3a216f774c1f0596b/result.json) |
| Lake Ontario / `cem` | 20261201 / 4 | 19.865744150 / 0.774055248 | 删失 5.0000 | 5.0005 | `budget_exceeded` / `max_seconds` | [B5_3e6921ff9e6dbd968d68](runs/B5_3e6921ff9e6dbd968d68/result.json) |
| Lake Ontario / `ils` | 20261127 / 0 | 18.055910936 / 0.883112219 | 删失 5.0000 | 5.0001 | `budget_exceeded` / `max_seconds` | [B5_b445369f465c45b61731](runs/B5_b445369f465c45b61731/result.json) |
| Lake Ontario / `ils` | 20261128 / 1 | 18.127802500 / 0.881468902 | 删失 5.0000 | 5.0002 | `budget_exceeded` / `max_seconds` | [B5_ec8892547493f85df304](runs/B5_ec8892547493f85df304/result.json) |
| Lake Ontario / `ils` | 20261129 / 2 | 18.065613375 / 0.864607040 | 删失 5.0000 | 5.0002 | `budget_exceeded` / `max_seconds` | [B5_f650ce1cd3c7b6846fcf](runs/B5_f650ce1cd3c7b6846fcf/result.json) |
| Lake Ontario / `ils` | 20261130 / 3 | 17.991382847 / 0.884826446 | 删失 5.0000 | 5.0001 | `budget_exceeded` / `max_seconds` | [B5_da0cbb11c022839d6be4](runs/B5_da0cbb11c022839d6be4/result.json) |
| Lake Ontario / `ils` | 20261201 / 4 | 18.026884495 / 0.894897760 | 删失 5.0000 | 5.0002 | `budget_exceeded` / `max_seconds` | [B5_ed0b82d158a93a065fbf](runs/B5_ed0b82d158a93a065fbf/result.json) |
| Lake Ontario / `paper_baseline` | 0 / 0 | 17.293894155 / 0.897370419 | 删失 0.9203 | 0.9203 | `completed` | [B5_004b58ae49ffe2f6143b](runs/B5_004b58ae49ffe2f6143b/result.json) |
| Lake Ontario / `paper_baseline` | 0 / 1 | 17.293894155 / 0.897370419 | 删失 0.9253 | 0.9253 | `completed` | [B5_652b2df732b8c72a8518](runs/B5_652b2df732b8c72a8518/result.json) |
| Lake Ontario / `paper_baseline` | 0 / 2 | 17.293894155 / 0.897370419 | 删失 0.9197 | 0.9197 | `completed` | [B5_6b13e43ea05a7e86cfdf](runs/B5_6b13e43ea05a7e86cfdf/result.json) |

## B30　真实历史档案对照

各方法在同一冻结 PT 上开始，完整重放计入方法预算。达到时间只表示首次在预算内完成原评分的时刻。有删失值的分组只报告达到者中位数并标星，比较范围为本机本批。

| 档案 | 方法 | 有效 / 计划 | J 中位数 [最小, 最大] | Pd 中位数 | 达到数 / 有效 | 达到时间中位数 s | 方法 / 进程中位耗时 s | 峰值 RSS 中位 MiB |
|---|---|---:|---|---:|---:|---:|---:|---:|
| Hudson | `anytime_mass` | 3 / 3 | 20.386109349 [20.386109349, 20.386109349] | 0.908583112 | 3 / 3 | 1.388236 | 30.1841 / 31.2321 | 912.05 |
| Hudson | `anytime_zero` | 3 / 3 | 20.386109349 [20.386109349, 20.386109349] | 0.908583112 | 3 / 3 | 1.376185 | 30.2118 / 31.3255 | 1036.70 |
| Hudson | `cem` | 5 / 5 | 24.523058511 [23.881382096, 24.930410278] | 0.798702438 | 0 / 5 | — | 30.0011 / 31.1151 | 82.95 |
| Hudson | `ils` | 5 / 5 | 21.598303318 [21.471890403, 21.743414767] | 0.886573544 | 0 / 5 | — | 30.0004 / 31.1279 | 81.40 |
| Hudson | `paper_baseline` | 3 / 3 | 20.390881327 [20.390881327, 20.390881327] | 0.906729745 | 3 / 3 | 1.261319 | 1.2613 / 2.3344 | 144.37 |
| Lake Ontario | `anytime_mass` | 3 / 3 | 17.264874448 [17.264874448, 17.264874448] | 0.897364416 | 3 / 3 | 2.398000 | 30.1347 / 31.2322 | 740.02 |
| Lake Ontario | `anytime_zero` | 3 / 3 | 17.264874448 [17.264874448, 17.264874448] | 0.897364416 | 3 / 3 | 2.281054 | 30.1535 / 31.2270 | 783.61 |
| Lake Ontario | `cem` | 5 / 5 | 19.254034113 [18.752099716, 19.531614522] | 0.813272921 | 0 / 5 | — | 30.0010 / 31.1142 | 81.31 |
| Lake Ontario | `ils` | 5 / 5 | 17.897983707 [17.733276154, 17.966405845] | 0.876357132 | 0 / 5 | — | 30.0006 / 31.1225 | 83.22 |
| Lake Ontario | `paper_baseline` | 3 / 3 | 17.293894155 [17.293894155, 17.293894155] | 0.897370419 | 0 / 3 | — | 0.9056 / 2.0311 | 95.02 |

逐次路线、耗时超额与峰值见 [comparison.csv](comparison.csv)。

| 方法 | Lake / Hudson 相对廉价对照 J 收益 | Lake / Hudson 对 zero 与 mass 的时间比 | Q | T | 状态 |
|---|---:|---|---|---|---|
| `ils` | -3.667% / -5.946% | 删失 / 删失 | 未通过 | 未通过 | `screen_not_passed` |
| `cem` | -11.521% / -20.293% | 删失 / 删失 | 未通过 | 未通过 | `screen_not_passed` |

| 档案 / 方法 | seed / 重复序号 | J / Pd | 达到时间 s | 方法耗时 s | 方法停止状态 | 原始记录 |
|---|---|---:|---:|---:|---|---|
| Hudson / `anytime_mass` | 0 / 0 | 20.386109349 / 0.908583112 | 1.388236 | 30.1841 | `budget_exceeded` / `max_seconds` | [B30_837343dc709ab5c24a40](runs/B30_837343dc709ab5c24a40/result.json) |
| Hudson / `anytime_mass` | 0 / 1 | 20.386109349 / 0.908583112 | 1.372341 | 30.1774 | `budget_exceeded` / `max_seconds` | [B30_337d3b9c1a37ada8bb6f](runs/B30_337d3b9c1a37ada8bb6f/result.json) |
| Hudson / `anytime_mass` | 0 / 2 | 20.386109349 / 0.908583112 | 1.398418 | 30.2389 | `budget_exceeded` / `max_seconds` | [B30_b2503f03d2a304dedef0](runs/B30_b2503f03d2a304dedef0/result.json) |
| Hudson / `anytime_zero` | 0 / 0 | 20.386109349 / 0.908583112 | 1.376185 | 30.2115 | `budget_exceeded` / `max_seconds` | [B30_715f5ff7b003f9b561a2](runs/B30_715f5ff7b003f9b561a2/result.json) |
| Hudson / `anytime_zero` | 0 / 1 | 20.386109349 / 0.908583112 | 1.426979 | 30.2526 | `budget_exceeded` / `max_seconds` | [B30_d84a6874436042139c9c](runs/B30_d84a6874436042139c9c/result.json) |
| Hudson / `anytime_zero` | 0 / 2 | 20.386109349 / 0.908583112 | 1.368572 | 30.2118 | `budget_exceeded` / `max_seconds` | [B30_98a645ccfc38dde624d2](runs/B30_98a645ccfc38dde624d2/result.json) |
| Hudson / `cem` | 20261127 / 0 | 24.047742600 / 0.798702438 | 删失 30.0000 | 30.0008 | `budget_exceeded` / `max_seconds` | [B30_c7227715aef1c760550f](runs/B30_c7227715aef1c760550f/result.json) |
| Hudson / `cem` | 20261128 / 1 | 24.930410278 / 0.797448800 | 删失 30.0000 | 30.0008 | `budget_exceeded` / `max_seconds` | [B30_74478311767cd98e6960](runs/B30_74478311767cd98e6960/result.json) |
| Hudson / `cem` | 20261129 / 2 | 24.523058511 / 0.833635106 | 删失 30.0000 | 30.0011 | `budget_exceeded` / `max_seconds` | [B30_4ea883476e11aa3db50d](runs/B30_4ea883476e11aa3db50d/result.json) |
| Hudson / `cem` | 20261130 / 3 | 23.881382096 / 0.801190032 | 删失 30.0000 | 30.0011 | `budget_exceeded` / `max_seconds` | [B30_ec1f6d2cadfc4c93c1de](runs/B30_ec1f6d2cadfc4c93c1de/result.json) |
| Hudson / `cem` | 20261201 / 4 | 24.700466046 / 0.792183980 | 删失 30.0000 | 30.0012 | `budget_exceeded` / `max_seconds` | [B30_0f6e1d0392debbcb2903](runs/B30_0f6e1d0392debbcb2903/result.json) |
| Hudson / `ils` | 20261127 / 0 | 21.562081326 / 0.890062079 | 删失 30.0000 | 30.0005 | `budget_exceeded` / `max_seconds` | [B30_97e7d8fb47c73ed8b173](runs/B30_97e7d8fb47c73ed8b173/result.json) |
| Hudson / `ils` | 20261128 / 1 | 21.598303318 / 0.875387194 | 删失 30.0000 | 30.0004 | `budget_exceeded` / `max_seconds` | [B30_83de10abe69bdac34150](runs/B30_83de10abe69bdac34150/result.json) |
| Hudson / `ils` | 20261129 / 2 | 21.471890403 / 0.874166430 | 删失 30.0000 | 30.0007 | `budget_exceeded` / `max_seconds` | [B30_03800b758f45dd0a1e48](runs/B30_03800b758f45dd0a1e48/result.json) |
| Hudson / `ils` | 20261130 / 3 | 21.612219864 / 0.894152207 | 删失 30.0000 | 30.0004 | `budget_exceeded` / `max_seconds` | [B30_e71e4378901de06a5040](runs/B30_e71e4378901de06a5040/result.json) |
| Hudson / `ils` | 20261201 / 4 | 21.743414767 / 0.886573544 | 删失 30.0000 | 30.0003 | `budget_exceeded` / `max_seconds` | [B30_26cfcf353a99e407d998](runs/B30_26cfcf353a99e407d998/result.json) |
| Hudson / `paper_baseline` | 0 / 0 | 20.390881327 / 0.906729745 | 1.261319 | 1.2613 | `completed` | [B30_2593a156cc255570a3ef](runs/B30_2593a156cc255570a3ef/result.json) |
| Hudson / `paper_baseline` | 0 / 1 | 20.390881327 / 0.906729745 | 1.242716 | 1.2427 | `completed` | [B30_57ac8a40b03802169ad3](runs/B30_57ac8a40b03802169ad3/result.json) |
| Hudson / `paper_baseline` | 0 / 2 | 20.390881327 / 0.906729745 | 1.425482 | 1.4255 | `completed` | [B30_721297f42fa892d21e1f](runs/B30_721297f42fa892d21e1f/result.json) |
| Lake Ontario / `anytime_mass` | 0 / 0 | 17.264874448 / 0.897364416 | 2.398682 | 30.1769 | `budget_exceeded` / `max_seconds` | [B30_a7a2323d0fce285c156e](runs/B30_a7a2323d0fce285c156e/result.json) |
| Lake Ontario / `anytime_mass` | 0 / 1 | 17.264874448 / 0.897364416 | 2.398000 | 30.1278 | `budget_exceeded` / `max_seconds` | [B30_51159178ecdc343f1f22](runs/B30_51159178ecdc343f1f22/result.json) |
| Lake Ontario / `anytime_mass` | 0 / 2 | 17.264874448 / 0.897364416 | 2.379568 | 30.1347 | `budget_exceeded` / `max_seconds` | [B30_9759e012e690c2a79704](runs/B30_9759e012e690c2a79704/result.json) |
| Lake Ontario / `anytime_zero` | 0 / 0 | 17.264874448 / 0.897364416 | 2.281054 | 30.1535 | `budget_exceeded` / `max_seconds` | [B30_922423c0c0f340d28505](runs/B30_922423c0c0f340d28505/result.json) |
| Lake Ontario / `anytime_zero` | 0 / 1 | 17.264874448 / 0.897364416 | 2.270512 | 30.1382 | `budget_exceeded` / `max_seconds` | [B30_20cd029679d2f19cacca](runs/B30_20cd029679d2f19cacca/result.json) |
| Lake Ontario / `anytime_zero` | 0 / 2 | 17.264874448 / 0.897364416 | 2.508337 | 30.2619 | `budget_exceeded` / `max_seconds` | [B30_8bcebe6f73a5397cff56](runs/B30_8bcebe6f73a5397cff56/result.json) |
| Lake Ontario / `cem` | 20261127 / 0 | 19.254034113 / 0.813272921 | 删失 30.0000 | 30.0010 | `budget_exceeded` / `max_seconds` | [B30_47c0f3845265ef434a2f](runs/B30_47c0f3845265ef434a2f/result.json) |
| Lake Ontario / `cem` | 20261128 / 1 | 19.324006867 / 0.805214692 | 删失 30.0000 | 30.0010 | `budget_exceeded` / `max_seconds` | [B30_b868c82c139983c82c53](runs/B30_b868c82c139983c82c53/result.json) |
| Lake Ontario / `cem` | 20261129 / 2 | 19.092252469 / 0.807815037 | 删失 30.0000 | 30.0009 | `budget_exceeded` / `max_seconds` | [B30_54aad0e383e1f015925e](runs/B30_54aad0e383e1f015925e/result.json) |
| Lake Ontario / `cem` | 20261130 / 3 | 19.531614522 / 0.830375616 | 删失 30.0000 | 30.0012 | `budget_exceeded` / `max_seconds` | [B30_195effe184ac6a2cbdb3](runs/B30_195effe184ac6a2cbdb3/result.json) |
| Lake Ontario / `cem` | 20261201 / 4 | 18.752099716 / 0.831273146 | 删失 30.0000 | 30.0009 | `budget_exceeded` / `max_seconds` | [B30_fa63aea05df5f9d2fa01](runs/B30_fa63aea05df5f9d2fa01/result.json) |
| Lake Ontario / `ils` | 20261127 / 0 | 17.733276154 / 0.876357132 | 删失 30.0000 | 30.0006 | `budget_exceeded` / `max_seconds` | [B30_4b87ec6b2f522b44f2d7](runs/B30_4b87ec6b2f522b44f2d7/result.json) |
| Lake Ontario / `ils` | 20261128 / 1 | 17.925079842 / 0.879304554 | 删失 30.0000 | 30.0008 | `budget_exceeded` / `max_seconds` | [B30_59aa3a2759e43328cb26](runs/B30_59aa3a2759e43328cb26/result.json) |
| Lake Ontario / `ils` | 20261129 / 2 | 17.897983707 / 0.872618560 | 删失 30.0000 | 30.0005 | `budget_exceeded` / `max_seconds` | [B30_90e0a9838a11126d4f65](runs/B30_90e0a9838a11126d4f65/result.json) |
| Lake Ontario / `ils` | 20261130 / 3 | 17.966405845 / 0.875930471 | 删失 30.0000 | 30.0006 | `budget_exceeded` / `max_seconds` | [B30_b15cc37dbb0c305a0279](runs/B30_b15cc37dbb0c305a0279/result.json) |
| Lake Ontario / `ils` | 20261201 / 4 | 17.745538226 / 0.876578158 | 删失 30.0000 | 30.0005 | `budget_exceeded` / `max_seconds` | [B30_93077020952bb74b1424](runs/B30_93077020952bb74b1424/result.json) |
| Lake Ontario / `paper_baseline` | 0 / 0 | 17.293894155 / 0.897370419 | 删失 0.9351 | 0.9351 | `completed` | [B30_d2dd2e14ca00a7eb7dec](runs/B30_d2dd2e14ca00a7eb7dec/result.json) |
| Lake Ontario / `paper_baseline` | 0 / 1 | 17.293894155 / 0.897370419 | 删失 0.8761 | 0.8761 | `completed` | [B30_3642900606bbab77f294](runs/B30_3642900606bbab77f294/result.json) |
| Lake Ontario / `paper_baseline` | 0 / 2 | 17.293894155 / 0.897370419 | 删失 0.9056 | 0.9056 | `completed` | [B30_c251da0e4fb5b465b68c](runs/B30_c251da0e4fb5b465b68c/result.json) |

## 严格参考改善与机制

参考改善定义为历史参考 J 减预算内重放 J > 1e-8。表中的首次分歧针对同场景历史参考。路径见所链接的 result.json 中 result.path。

| 阶段 | 档案 / 方法 / seed | J 改善 / 相对改善 | Pd 变化 | 首分歧步 | 路线计分完成秒 | 运行 ID |
|---|---|---:|---:|---:|---:|---|
| — | 未记录严格参考改善 | — | — | — | — | — |

按方法和档案汇总机制观测。不同运行的独特路线数分别计算，以下中位数不跨 seed 去重。

| 阶段 / 档案 / 方法 | 独特路线中位数 | 重复率中位数 | 构造 / 评分中位秒 | 最终等于历史参考 | 最终等于 PT | 机制记录 |
|---|---:|---:|---:|---:|---:|---|
| B30 / Hudson / `cem` | 26277.0 | 0.000% | 19.0825 / 10.3410 | 0 / 5 | 0 / 5 | 逐次完整代数中位数 547，计分样本中位数 26276。每代 elite J 与分布收缩未记录。最终路线首次偏离参考中位步数 4。 |
| B30 / Hudson / `ils` | 10297.0 | 0.952% | 25.4490 / 4.2487 | 0 / 5 | 0 / 5 | 接受劣化 2193 次。与其后 best 有溯源关联 19 条。算子次数 {'root_restart': 6662, 'early_rebuild': 5342, 'reorder_waypoints': 5345}。预算内 best 来源 {'early_rebuild': 11, 'polish_suffix': 37, 'root_restart': 10, 'reorder_waypoints': 5}。最终路线首次偏离参考中位步数 7。 |
| B30 / Lake Ontario / `cem` | 32318.0 | 0.000% | 19.0763 / 10.2862 | 0 / 5 | 0 / 5 | 逐次完整代数中位数 673，计分样本中位数 32317。每代 elite J 与分布收缩未记录。最终路线首次偏离参考中位步数 4。 |
| B30 / Lake Ontario / `ils` | 15884.0 | 1.110% | 24.0296 / 5.5320 | 0 / 5 | 0 / 5 | 接受劣化 3431 次。与其后 best 有溯源关联 18 条。算子次数 {'root_restart': 10577, 'early_rebuild': 8476, 'reorder_waypoints': 8471}。预算内 best 来源 {'reorder_waypoints': 3, 'polish_suffix': 23, 'early_rebuild': 13, 'root_restart': 10}。最终路线首次偏离参考中位步数 1。 |
| B5 / Hudson / `cem` | 4315.0 | 0.000% | 3.1826 / 1.7228 | 0 / 5 | 1 / 5 | 逐次完整代数中位数 89，计分样本中位数 4314。每代 elite J 与分布收缩未记录。最终路线首次偏离参考中位步数 6。 |
| B5 / Hudson / `ils` | 1820.0 | 1.141% | 4.2250 / 0.7188 | 0 / 5 | 0 / 5 | 接受劣化 382 次。与其后 best 有溯源关联 10 条。算子次数 {'root_restart': 1154, 'early_rebuild': 934, 'reorder_waypoints': 931}。预算内 best 来源 {'polish_suffix': 27, 'early_rebuild': 10, 'root_restart': 6, 'reorder_waypoints': 2}。最终路线首次偏离参考中位步数 5。 |
| B5 / Lake Ontario / `cem` | 5297.0 | 0.000% | 3.1908 / 1.7038 | 0 / 5 | 0 / 5 | 逐次完整代数中位数 110，计分样本中位数 5296。每代 elite J 与分布收缩未记录。最终路线首次偏离参考中位步数 1。 |
| B5 / Lake Ontario / `ils` | 2855.0 | 1.003% | 3.9729 / 0.9507 | 0 / 5 | 0 / 5 | 接受劣化 589 次。与其后 best 有溯源关联 13 条。算子次数 {'root_restart': 1834, 'early_rebuild': 1481, 'reorder_waypoints': 1478}。预算内 best 来源 {'root_restart': 14, 'polish_suffix': 31, 'early_rebuild': 6, 'reorder_waypoints': 2}。最终路线首次偏离参考中位步数 1。 |

劣化谱系与算子来源用于溯源。因果归因需要独立消融。

## C300　延长门槛

筛选状态 `not_triggered`。 [冻结选择证据](C300_selection.json)

B30 未满足预声明的延长条件。

## 判定与适用范围

B5 的 ILS 与 CEM 均未达到预声明的质量或达到时间门槛。
B30 共观察到 ILS/CEM 严格参考改善 0 次。

两种新方法在 B30 的两个场景中都比各自 B5 的 J 中位数更低，仍与同批 anytime zero/mass 有差距。CEM 在 B30 每场景跑出数万条不同路线。ILS 的路线构造占算法时间的大部分，并观察到改变早期走向的候选。结果表明，当前采样与重构机制在这些预算下很少产生能逼近强对照的路线。更多预算能否稳定改变结果仍未知。

按预声明规则结束本批。当前证据支持保留 anytime zero/mass 作为这两个归档的比较基准。

本批使用真实历史 wind/current forcing 驱动的模拟粒子与冻结运动契约。真实完整域最优差距未知，count/DFS 数值标尺只覆盖 A。Fundy 方向仍未验证，其档案在本批主矩阵之外。独立档案验证状态为 `not_run`，优化器种子及同档案重复计时用于检查本批稳定性。
