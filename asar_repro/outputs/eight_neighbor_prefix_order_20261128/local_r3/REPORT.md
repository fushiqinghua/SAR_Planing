# 早中段前缀取点顺序实验

四个已见开发实例共 24 次有效运行。判定为 `prefix_order_development_screen_not_passed`。
两组共用冻结初始路线、历史真实 forcing 的粒子档案、原目标和独立物理重放。合并关闭，每次使用 30 秒预算。早中段前缀取点顺序是本轮候选差异。
每实例每方法按 (J, 重复序号) 取中位代表运行。Pd 来自同一条代表路径。

[冻结协议](<protocol.json>) · [toy/Oracle](validation/toy-pytest.xml) · [全量测试](validation/full-pytest.xml) · [等展开数诊断](<equal-work.json>)

## J 与 Pd

| 实例 | C0 J | 候选 J | J 改善 | C0 Pd | 候选 Pd | ΔPd 百分点 | 代表运行 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| lake_h2_d1_s3101 | 14.307066617 | 14.281396295 | +0.1794% | 94.9103% | 94.7451% | -0.1652 | [C0](runs/P30_b81d1d2dfd5333eaa0b1/result.json) · [候选](runs/P30_c921d9d7c0ac97008bbc/result.json) |
| lake_h2_d2_s3201 | 14.058508572 | 13.873903333 | +1.3131% | 93.0400% | 93.5703% | +0.5303 | [C0](runs/P30_58e480aa40e0577d912d/result.json) · [候选](runs/P30_04980f8317f8af1b3773/result.json) |
| hudson_h2_d1_s4101 | 28.449668928 | 28.724588352 | -0.9663% | 81.1898% | 81.4235% | +0.2337 | [C0](runs/P30_54ced2b376e56406c764/result.json) · [候选](runs/P30_ad1ae7462addcb63e2dc/result.json) |
| hudson_h2_d2_s4201 | 58.739707200 | 58.522087200 | +0.3705% | 8.5808% | 9.0948% | +0.5140 | [C0](runs/P30_f6cb2ac7961b0054ba68/result.json) · [候选](runs/P30_f48351230d105a15d4bc/result.json) |

采用门槛要求至少 3/4 例相对 J 改善 0.1%，Lake 和 Hudson 各至少一例。任一例 J 相对退化不得超过 1e-8，终点 Pd 降幅不得超过 0.5 个百分点。
J 改善达标 3/4，Lake 2/2，Hudson 1/2。J 护栏未通过，Pd 护栏通过。

## Hudson 历史可行路线

| 实例 | 历史最好 J | 本轮候选 J | 相对改善 | 突破历史最好 | 改善达 0.1% |
| --- | ---: | ---: | ---: | --- | --- |
| hudson_h2_d1_s4101 | 28.448979882 | 28.724588352 | -0.9688% | 否 | 否 |
| hudson_h2_d2_s4201 | 58.677655392 | 58.522087200 | +0.2651% | 是 | 是 |

历史路线只作事后参照。4201 的历史值来自上轮滚动组。两组求解均使用本轮冻结的共同初始路线。

## 搜索行为与资源

表内计时、内存与工作量按三次运行分别取中位数。首探测使用 J 中位代表路线。
关闭合并后，展开树中的每条合法航点前缀对应一次展开。早段取 4×tick<K，中段取 K≤4×tick<3K。尾两 tick 单列。

| 实例 | 方法 | 墙钟秒 | 扩展数 | RSS MiB | 尾两 tick 占比 | 早段唯一前缀 | 中段唯一前缀 | 首探测 tick | 找到最佳解秒 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| lake_h2_d1_s3101 | C0 | 29.815 | 65995 | 271.6 | 92.0% | 181 | 1090 | 2 | 1.136 |
| lake_h2_d1_s3101 | C0_PREFIX | 29.889 | 28192 | 510.1 | 61.9% | 3649 | 4124 | 2 | 2.849 |
| lake_h2_d2_s3201 | C0 | 29.862 | 59857 | 380.4 | 87.3% | 134 | 1261 | 1 | 1.394 |
| lake_h2_d2_s3201 | C0_PREFIX | 29.900 | 27692 | 507.3 | 60.8% | 3560 | 4235 | 1 | 19.715 |
| hudson_h2_d1_s4101 | C0 | 29.851 | 9308 | 395.5 | 11.2% | 4675 | 3331 | 2 | 29.403 |
| hudson_h2_d1_s4101 | C0_PREFIX | 29.850 | 8012 | 383.6 | 0.0% | 4845 | 3057 | 2 | 0.004 |
| hudson_h2_d2_s4201 | C0 | 29.756 | 87049 | 91.0 | 96.8% | 13 | 26 | 29 | 0.666 |
| hudson_h2_d2_s4201 | C0_PREFIX | 29.863 | 36505 | 432.6 | 72.8% | 4574 | 4584 | 29 | 4.367 |

搜索停止原因 C0 max_seconds ×12，C0_PREFIX max_seconds ×12。
预算内返回的路线均按原评分器独立重放。该排序实验不产生全局或 ε 界。四例与重复的用途是开发筛选及计时复核。

[逐次指标](comparison.csv) · [实例对照](instance_comparison.csv) · [剩余质量曲线](survival.csv) · [incumbent 记录](incumbent_history.csv) · [判定 JSON](gate.json) · [逐次原始记录与 stdout/stderr](runs)

## Hudson 路线与搜索机制核对

- **4101**。候选三次中两次未生成任何主搜索终止候选，保留 S30 共同行程。原 C0 三次均展开到第 59 个观测 tick，最终最好路线均在内层 29.3 秒之后出现。候选的 guide 时间中位数约 24.86 秒，原 C0 约 24.37 秒。这个时窗中的劣化与终止候选来不及出现一致。候选代表路线的终点 Pd 高 0.2337 个百分点，但前 20 个 tick 的累计 Pd 总和比原 C0 低 0.30751，导致 J 退化。
- **4201**。候选三次均得到 J=58.522087200 和 Pd=9.094800%。比上轮滚动路线的 J 低 0.2651%。首次正探测仍在 tick 29，累计 Pd 从 tick 40 开始与原 C0 分开。J 降幅 0.217620 中，约 0.112799 来自 tick 40–51，其余 0.104821 来自 tick 52–60。较早分支带来了新的全程合法路线，主搜索终端数中位数从 596,180 降为 179,065，进程峰值 RSS 中位数从 91.0 升至 432.6 MiB。

## 等展开数与独立核验

每个实例的 off、shadow、exact 各运行一次，均由 4,096 次展开上限停止。四例 off/shadow 的弹堆、在手解和归档序列去除时间字段后完全一致。exact 在 Hudson 4101 的第 5 次、Hudson 4201 的第 204 次弹堆首次与 off 分开，固定展开量返回的 J/Pd 均持平。单次诊断的耗时仅描述记录中的工作量。[等展开数门槛与原始记录索引](equal-work.json)

本地复核覆盖 24 份原始文件指纹、路径合法性、冻结粒子和 S30、原评分与独立物理重放、同路 J/Pd 中位值。17 项 toy/Oracle 通过。最终全量测试 1,793 项及 29 项子测试通过。第一次全量测试的默认临时目录拒绝创建硬链接，第二次验证的临时目录父级缺失。第三次使用已建立且可创建硬链接的临时目录复跑原测试，两次早期尝试均保留。[第一次测试日志](../local_r1/validation/full-pytest.stdout.log) · [第二次测试日志](../local_r2/validation/full-pytest.stdout.log) · [原始结果复核](independent_postrun_verification.log) · [J/Pd 与展开图](prefix_order_comparison.png)

## 归档校验与复跑

归档保留 `local_r3` 正式运行时的 Python 源码字节，以及 `local_r1`、`local_r2` 的两次验证失败证据。正式批次的冻结指纹见 [协议](protocol.json)，全部路径分组、随机种子与执行参数见 [任务表](tasks.json) 和 [命令日志](commands)。

从头复跑时，在独立目录检出基准提交 `d605b97280b80dc8bed66ab1bab5c061ecbfc517`，把归档提交里的以下五个文件以未暂存文件放入各自位置。这样可沿用原 Git 基准检查和冻结源码指纹。

- `asar_repro/src/asar_repro/physical_prefix_order.py`
- `asar_repro/tests/test_physical_prefix_order.py`
- `asar_repro/scripts/run_eight_neighbor_prefix_order.py`
- `asar_repro/scripts/run_prefix_order_equal_work.py`
- `asar_repro/scripts/analyze_eight_neighbor_prefix_order.py`

核验原 H2 粒子档案与 S30 初始路线后，使用独立的 `local_rN` 归档目录依序执行命令日志中的准备、验证、等展开数诊断、正式对照和汇总。已归档的结果可以直接核验与重绘。[定稿校验脚本](reproduce/verify_runs.py) · [图表脚本](reproduce/plot_comparison.py)
