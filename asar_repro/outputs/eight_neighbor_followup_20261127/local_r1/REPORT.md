# 八邻接后续实验：加速与同 forcing 预留实例

这是当前输出目录的记录汇总；新实例共享历史forcing，不能解释成独立天气泛化。

| 阶段 | 有效/计划 | 状态 |
|---|---:|---|
| P0 | 8/8 | complete |
| D5 | 48/48 | complete |
| S30 | 4/4 | complete |
| H30 | 48/48 | complete |

严格等价性审计：True
D5：acceleration_screen_passed
H30：within_forcing_transfer_signal

## 逐组指标

J/Pd中位数可能来自不同重复；缺失与失败不会计为零收益。

| 阶段 | 场景/实例 | 覆盖 | 邻接 | 后端 | n | J 中位数 [范围] | Pd 中位数 |
|---|---|---|---:|---|---:|---:|---:|
| D5 | arctic_ocean | axis_square | 4 | cached | 3/3 | 20.386109349 [20.386109349, 20.386109349] | 0.908583112 |
| D5 | arctic_ocean | axis_square | 4 | original | 3/3 | 20.386109349 [20.386109349, 20.386109349] | 0.908583112 |
| D5 | arctic_ocean | axis_square | 8 | cached | 3/3 | 20.386109349 [20.386109349, 20.386109349] | 0.908583112 |
| D5 | arctic_ocean | axis_square | 8 | original | 3/3 | 20.386109349 [20.386109349, 20.386109349] | 0.908583112 |
| D5 | arctic_ocean | heading_square | 4 | cached | 3/3 | 20.386109349 [20.386109349, 20.386109349] | 0.908583112 |
| D5 | arctic_ocean | heading_square | 4 | original | 3/3 | 20.386109349 [20.386109349, 20.386109349] | 0.908583112 |
| D5 | arctic_ocean | heading_square | 8 | cached | 3/3 | 20.317725022 [20.317725022, 20.317725022] | 0.910565427 |
| D5 | arctic_ocean | heading_square | 8 | original | 3/3 | 20.386109349 [20.386109349, 20.386109349] | 0.908583112 |
| D5 | lake_ontario | axis_square | 4 | cached | 3/3 | 17.264874448 [17.264874448, 17.264874448] | 0.897364416 |
| D5 | lake_ontario | axis_square | 4 | original | 3/3 | 17.264874448 [17.264874448, 17.264874448] | 0.897364416 |
| D5 | lake_ontario | axis_square | 8 | cached | 3/3 | 17.264874448 [17.264874448, 17.264874448] | 0.897364416 |
| D5 | lake_ontario | axis_square | 8 | original | 3/3 | 17.264874448 [17.264874448, 17.264874448] | 0.897364416 |
| D5 | lake_ontario | heading_square | 4 | cached | 3/3 | 17.264874448 [17.264874448, 17.264874448] | 0.897364416 |
| D5 | lake_ontario | heading_square | 4 | original | 3/3 | 17.264874448 [17.264874448, 17.264874448] | 0.897364416 |
| D5 | lake_ontario | heading_square | 8 | cached | 3/3 | 16.752262696 [16.752262696, 16.752262696] | 0.904678365 |
| D5 | lake_ontario | heading_square | 8 | original | 3/3 | 16.752262696 [16.752262696, 16.752262696] | 0.904678365 |
| H30 | hudson_window_early | axis_square | 4 | cached | 3/3 | 26.344691040 [26.344691040, 26.344691040] | 0.824859360 |
| H30 | hudson_window_early | axis_square | 8 | cached | 3/3 | 22.840425949 [22.840425949, 22.840425949] | 0.887116976 |
| H30 | hudson_window_early | heading_square | 4 | cached | 3/3 | 26.344691040 [26.344691040, 26.344691040] | 0.824859360 |
| H30 | hudson_window_early | heading_square | 8 | cached | 3/3 | 22.790164159 [22.790164159, 22.790164159] | 0.895362734 |
| H30 | hudson_window_late | axis_square | 4 | cached | 3/3 | 20.337375787 [20.337375787, 20.337375787] | 0.917093438 |
| H30 | hudson_window_late | axis_square | 8 | cached | 3/3 | 19.941886265 [19.941886265, 19.941886265] | 0.922347745 |
| H30 | hudson_window_late | heading_square | 4 | cached | 3/3 | 20.337375787 [20.337375787, 20.337375787] | 0.917093438 |
| H30 | hudson_window_late | heading_square | 8 | cached | 3/3 | 19.815790368 [19.815790368, 19.815790368] | 0.921818146 |
| H30 | lake_window_early | axis_square | 4 | cached | 3/3 | 17.151955583 [17.151955583, 17.151955583] | 0.909765081 |
| H30 | lake_window_early | axis_square | 8 | cached | 3/3 | 16.703731421 [16.703731421, 16.703731421] | 0.914320706 |
| H30 | lake_window_early | heading_square | 4 | cached | 3/3 | 17.151955583 [17.151955583, 17.151955583] | 0.909765081 |
| H30 | lake_window_early | heading_square | 8 | cached | 3/3 | 16.744214940 [16.744214940, 16.744214940] | 0.917916211 |
| H30 | lake_window_late | axis_square | 4 | cached | 3/3 | 17.276096664 [17.276096664, 17.276096664] | 0.906255942 |
| H30 | lake_window_late | axis_square | 8 | cached | 3/3 | 17.176060142 [17.176060142, 17.176060142] | 0.900488532 |
| H30 | lake_window_late | heading_square | 4 | cached | 3/3 | 17.276096664 [17.276096664, 17.276096664] | 0.906255942 |
| H30 | lake_window_late | heading_square | 8 | cached | 3/3 | 16.871848574 [16.871848574, 16.871848574] | 0.897995258 |

D5目标命中次数、删失与目标时间见summary.json；未达到不填成5秒后计算加速比。
共同初始化成本单列于S30；H30计时包括其路线复制与重新评分。
原始history、缓存计数、逐次观测及路线见各result.json。H2和300秒扩展未启用。
