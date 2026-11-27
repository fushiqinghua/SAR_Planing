# 等价加速与 H1 预留实例结果模板

**本文件尚未填写，本批所有新执行状态 `not_run`。** 上一批 120 项测试和 96 项运行的成绩不能填入本批验证栏。

执行时先把本模板复制到本批输出目录的 `ANALYSIS.md` 后填写。仓库内本文件属于冻结源码清单；不要直接修改原件后继续 resume 或 summarize。

## 1. 执行身份

- 代码提交／批次版本：待填。
- 输出目录、协议与配置哈希：待填。
- Python、依赖、操作系统、CPU／逻辑核、内存、线程设置：待填；未知写 unknown。
- 新验证日志、JUnit、实际通过／失败／错误／跳过数量：待填。
- 相对交付是否修复源码：待填，注明重新验证及冻结身份。
- 原四邻／八邻源码保护是否通过：待填。

## 2. P0 配对前缀审计

| 开发档案 | 覆盖 | 邻接 | 完成前缀展开数 | 转移数／引导数 | 时间／概率／位置／引导是否一致 | 停止原因 | 证据 |
|---|---|---:|---:|---|---|---|---|
| Lake | heading_square | 4 | 待填 | 待填 | not_run | — | — |
| Lake | heading_square | 8 | 待填 | 待填 | not_run | — | — |
| Lake | axis_square | 4 | 待填 | 待填 | not_run | — | — |
| Lake | axis_square | 8 | 待填 | 待填 | not_run | — | — |
| Hudson | heading_square | 4 | 待填 | 待填 | not_run | — | — |
| Hudson | heading_square | 8 | 待填 | 待填 | not_run | — | — |
| Hudson | axis_square | 4 | 待填 | 待填 | not_run | — | — |
| Hudson | axis_square | 8 | 待填 | 待填 | not_run | — | — |

审计是共同工作量下的正确性证据，不把其双算耗时当作正式加速比。若达到审计截止而未完成规定范围，说明未完成原因，不填通过。

## 3. 阶段完整性

| 阶段 | 计划任务 | 有效 | 失败／缺失／阻断 | 状态 |
|---|---:|---:|---:|---|
| D5 | 48 | 待填 | 待填 | not_run |
| S30 | 4 | 待填 | 待填 | not_run |
| H30 | 48 | 待填 | 待填 | not_run |

单列 P0 与四例漂移准备状态。每个失败链接到原始记录和 stdout/stderr；保留原目录，不以删除后重跑隐藏失败。

## 4. D5 同机质量保护

各行原／加速分别有三次计时重复。写中位数及观察范围，范围不是置信区间。

| 场景 | 覆盖 | 邻接 | 原 J 中位数[范围] | 加速 J 中位数[范围] | 原／加速 Pd 中位数 | 有效数 | 质量保护 |
|---|---|---:|---|---|---|---|---|
| Lake | heading_square | 4 | 待填 | 待填 | 待填 | — | not_run |
| Lake | heading_square | 8 | 待填 | 待填 | 待填 | — | not_run |
| Lake | axis_square | 4 | 待填 | 待填 | 待填 | — | not_run |
| Lake | axis_square | 8 | 待填 | 待填 | 待填 | — | not_run |
| Hudson | heading_square | 4 | 待填 | 待填 | 待填 | — | not_run |
| Hudson | heading_square | 8 | 待填 | 待填 | 待填 | — | not_run |
| Hudson | axis_square | 4 | 待填 | 待填 | 待填 | — | not_run |
| Hudson | axis_square | 8 | 待填 | 待填 | 待填 | — | not_run |

J/Pd 的分组中位数可能来自不同运行。讨论实际航迹时引用具体 run ID 及同次的两个指标。

## 5. D5 达到目标与后端选择

| 目标组（8邻） | J_target | 原命中/3 | 加速命中/3 | 原目标时间中位数 | 加速目标时间中位数 | 可比较的时间减少 | 判定 |
|---|---:|---:|---:|---:|---:|---|---|
| Lake / heading | 16.752262696441605 | 待填 | 待填 | — | — | — | not_run |
| Lake / axis | 16.7169314627584 | 待填 | 待填 | — | — | — | not_run |
| Hudson / heading | 20.317725021888 | 待填 | 待填 | — | — | — | not_run |

未命中的单次时间填 `not_reached`，不能填5秒后计算加速比。时间比较门槛仅使用双方均3/3命中的组；其余组报告命中数和删失状态。

- 八组质量保护是否全部通过：待填。
- 三个目标组命中数是否均不退化：待填。
- 命中数严格增加的目标组：待填。
- 双方3/3且时间中位数至少缩短10%的组：待填。
- 最终 selected backend：待填。
- selection 文件、哈希、锁定时刻：待填。
- 四例漂移准备是否都在 selection 锁定后开始：待填。

未采用加速候选时，区分“正确完整但性能未达条件”与“证据无效”。后者不能直接生成选择并进入 H1。

## 6. 计算成本诊断

| 运行组／后端 | 预处理 | 引导 | 转移 | 完整重放 | 展开／生成／终点候选 | 缓存条目／命中 | 算法wall／CPU | 进程wall | 采样RSS |
|---|---:|---:|---:|---:|---|---|---|---:|---:|
| 待填 | — | — | — | — | — | — | — | — | — |

根据原始日志实际提供的字段填写，未记录的细分项写 unknown，不从剩余时间猜测。缓存构建成本在预算内；缓存 ndarray 字节计数不含全部 Python 对象及进程开销，采样 RSS 也不是精确内存高水位。记录是否因 max_open 提前停止，避免将不同完成工作量的总 wall 当作纯加速比。

## 7. H1 输入来源与准备

数据层级固定：`same_forcing_shifted_window_new_seed`。四例共用已有forcing，不能称为四个独立海况。

| 实例 | LKP/CST偏移 | seed | forcing哈希／覆盖 | 原生积分末时刻 | 档案／metadata哈希 | ID/帧/格号核验 | 状态 |
|---|---|---:|---|---|---|---|---|
| lake_window_early | −1h | 1041 | 待填 | 待填 | 待填 | 待填 | not_run |
| lake_window_late | +1h | 1042 | 待填 | 待填 | 待填 | 待填 | not_run |
| hudson_window_early | −2h | 2041 | 待填 | 待填 | 待填 | 待填 | not_run |
| hudson_window_late | +2h | 2042 | 待填 | 待填 | 待填 | 待填 | not_run |

说明实际 OpenDrift 及reader版本、生成耗时、特殊状态质量。缺输入或生成失败要保留原例身份，不替换为另一个有利实例。时间平移与seed同时改变，不能分别归因。

## 8. S30 共同初始化

| 实例 | PT/原paper生成记录 | 总预算／实际耗时 | 原离散 J/Pd | axis J/Pd | heading J/Pd | 路线哈希 | 桥接／合法性 |
|---|---|---|---|---|---|---|---|
| lake_window_early | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | not_run |
| lake_window_late | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | not_run |
| hudson_window_early | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | not_run |
| hudson_window_late | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 | not_run |

原离散分数取 S30 结果 `bridge.discrete_J`／`bridge.discrete_pd_final`，axis 分数取 `bridge.physical_J`／`bridge.physical_pd_final`；逐次 PT／paper 接受记录中的 `bridge` 也保留。heading 分数取同次 `physical_replays.heading_square`，不由 axis 分数推算。

H30的初始化复制与重放仍需计时。S30的共同路线生成成本单列，不计入任一H30后端的算法时间，但不能从端到端成本中消失。

## 9. H30 逐实例结果

每个单元使用该实例、该覆盖的三次重复，分别报告四／八邻接。最终选择的同一后端用于全部行。

| 实例 | 覆盖 | J4中位数[范围] | J8中位数[范围] | G | Pd4/Pd8中位数 | 有效数 | 结果 |
|---|---|---|---|---:|---|---|---|
| lake_window_early | heading | 待填 | 待填 | — | 待填 | — | not_run |
| lake_window_early | axis | 待填 | 待填 | — | 待填 | — | not_run |
| lake_window_late | heading | 待填 | 待填 | — | 待填 | — | not_run |
| lake_window_late | axis | 待填 | 待填 | — | 待填 | — | not_run |
| hudson_window_early | heading | 待填 | 待填 | — | 待填 | — | not_run |
| hudson_window_early | axis | 待填 | 待填 | — | 待填 | — | not_run |
| hudson_window_late | heading | 待填 | 待填 | — | 待填 | — | not_run |
| hudson_window_late | axis | 待填 | 待填 | — | 待填 | — | not_run |

## 10. H1 预声明判定

- 全部四例主覆盖不退化：待填。
- 主覆盖改善≥0.5%的实例集合 W：待填。
- 是否至少2/4主赢家：待填。
- W中至少一例axis仍正改善：待填。
- 全部axis退化≤0.5%：待填。
- Lake 主赢家数量 0/1/2：待填。
- Hudson 主赢家数量 0/1/2：待填。
- 有限迁移状态：待填，使用 `within_forcing_transfer_signal`、`within_forcing_scene_specific_signal`、`within_forcing_sensor_sensitive`、`within_forcing_screen_not_passed` 或 `incomplete_or_invalid`。
- 若为 `within_forcing_scene_specific_signal`，具体场景：待填。

若后来做固定路线跨覆盖重放，放在单独的事后分析小节，不能修改上述正式判定。对旧批 B5 的状态也不作追认。

## 11. 结论与后续

分别填写：

1. **直接事实：**哪些逐次结果、计时和路径支持开发效率或H1收益。
2. **机制解释：**是否改善早期探测、改变重访分布；是否增加晚段补偿或Pd权衡。标明推断。
3. **失败与负结果：**保留全部例子和后端，不只展示赢家。
4. **适用范围：**同forcing预留任务、未标定覆盖、有限预算；没有独立天气或真实飞行验证。
5. **下一步：**按判定结束本轮开发、保留场景限定信号，或另行设计需要新forcing的H2。

将填写后的分析保存为本批输出目录的 `ANALYSIS.md`，与验证、审计、D5、selection、输入准备、S30、冻结H1和H30的全部记录一起提交。
