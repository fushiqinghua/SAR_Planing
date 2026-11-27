# 物理搜索证据补强：本地自动汇总

状态：`complete`。输入是已经看过的开发/诊断实例。

完整路线候选：`completion_development_screen_passed`。

发现概率护栏：`feasible_without_required_joint_graph_gain`。

## 同预算四／八邻接对照

| 方法 | 实例 | 覆盖 | J4 | J8 | J改善 | ΔPd（百分点） |
|---|---|---|---:|---:|---:|---:|
| diagnostic_cached | lake_window_early | heading_square | 17.15195558 | 16.74421494 | 2.3772% | +0.8151 |
| diagnostic_cached | lake_window_late | heading_square | 17.27609666 | 16.87184857 | 2.3399% | -0.8261 |
| diagnostic_cached | hudson_window_early | heading_square | 26.34469104 | 22.79016416 | 13.4924% | +7.0503 |
| diagnostic_cached | hudson_window_late | heading_square | 20.33737579 | 19.81579037 | 2.5647% | +0.4725 |
| diagnostic_cached | lake_window_late | axis_square | 17.27609666 | 17.17606014 | 0.5790% | -0.5767 |
| diagnostic_cached | hudson_window_early | axis_square | 26.34469104 | 22.84042595 | 13.3016% | +6.2258 |
| completion_J | lake_window_early | heading_square | 17.15195558 | 16.74421494 | 2.3772% | +0.8151 |
| completion_J | lake_window_late | heading_square | 17.27609666 | 16.87184857 | 2.3399% | -0.8261 |
| completion_J | hudson_window_early | heading_square | 23.13390365 | 22.79016416 | 1.4859% | +2.0647 |
| completion_J | hudson_window_late | heading_square | 20.33737579 | 19.81579037 | 2.5647% | +0.4725 |
| completion_J | lake_window_late | axis_square | 17.27609666 | 17.17606014 | 0.5790% | -0.5767 |
| completion_J | hudson_window_early | axis_square | 23.13390365 | 22.84042595 | 1.2686% | +1.2401 |

## 使用边界

D5/D30/G30/R120 各自从固定共同参考重启；R120 只作质量诊断。
三次运行是计时重复，不能当作独立天气样本。H2 尚未启用。

完整判定、到达目标时刻、护栏代价和较强四邻接参考见 summary.json；逐次记录见 comparison.csv 与 runs/。
按 RESULTS_TEMPLATE.md 补充首个完整路线、深度/tick 分布和负结果的解释；不得将未到达目标填成5秒后计算加速比。
