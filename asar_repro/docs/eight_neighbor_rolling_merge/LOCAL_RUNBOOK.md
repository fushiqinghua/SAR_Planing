# 本地执行：精确状态等价合并诊断与验证

状态：`prepared_not_run`。交付者没有执行项目模块、测试、诊断搜索、正式实验、评分重放或 OpenDrift。以下步骤由用户本地执行，上一步通过后再进行下一步。

## 1. 获取更新并保留旧证据

在仓库根目录执行：

```bash
git fetch origin
git switch eight-neighbor-rolling-pilot-20261128
git pull --ff-only
cd asar_repro
```

继续使用先前完成 H2 和 rolling pilot 的 Python 环境。已有输入和结果目录保持原身份：

```text
outputs/eight_neighbor_h2_20261127/local_r2/
outputs/eight_neighbor_rolling_20261128/local_r1/
```

本轮输入仍来自相同四个 H2 粒子档案和 S30 共同路线。不要以新生成粒子替换缺失档案，也不需要为本轮重新生成风流和 OpenDrift。

新增配置与输出：

```text
configs/eight_neighbor_rolling_merge.json
outputs/eight_neighbor_rolling_merge_20261128/local_r1/
```

新协议增加了源码文件，因此旧 runner 的全源码 inventory 会变化。需要复核旧冻结协议时，应在旧提交 `6084c7d6528a863709466e1dfbb0930459d95414` 的独立检出中操作；不要修改旧锁文件使其适配新树。

## 2. 查看计划与预检

以下命令在 `asar_repro` 目录逐条执行；默认配置和输出就是上面列出的路径。

```bash
python scripts/run_eight_neighbor_rolling_merge.py plan
python scripts/run_eight_neighbor_rolling_merge.py preflight
```

计划应显示 D0 四项，条件性 F30 四十八项，最大名义算法预算 1,560 s（26 min）。实际过程另含读取、测试、进程启动和外部审计耗时。

预检核验继承源码、参考清单、历史协议、粒子档案与共同路线。缺失或 hash 不一致时保留原因，恢复原始相同字节文件。Windows 换行转换导致受保护文本指纹不一致时，使用 `core.autocrlf=false` 的干净检出恢复仓库字节，不重新计算参考指纹迁就差异。

## 3. 软件验证与协议冻结

```bash
python scripts/run_eight_neighbor_rolling_merge.py validate
python scripts/run_eight_neighbor_rolling_merge.py freeze
```

验证登记八个测试文件：`test_physical_model.py`、`test_physical_search.py`、`test_physical_accel.py`、`test_physical_refinement.py`、`test_physical_rolling.py`、`test_eight_neighbor_rolling_runner.py`、`test_physical_state_merge.py` 和 `test_eight_neighbor_rolling_merge_runner.py`，均位于 `tests/`。以实际 JUnit 和退出码为准；交付时没有预填通过数量。

冻结一次绑定代码、配置、输入、环境和 D0/F30 的全部任务清单。D0 之后不临时改变 F30 实例、对照、重复数、预算或容量。修改实现需要新版本和新输出目录，重新验证、冻结。

## 4. 先执行 D0

```bash
python scripts/run_eight_neighbor_rolling_merge.py run --stage D0
python scripts/run_eight_neighbor_rolling_merge.py analyze --stage D0
```

`run` 完成阶段后会自动分析；显式 `analyze` 用于独立检查和重新生成同一份派生汇总，不新增搜索任务。

重点阅读：

```text
D0/summary.json
D0/REPORT.md
D0/merge_diagnostics.csv
D0_gate.json
```

原始任务在输出根目录 `runs/` 下。只有四项有效，且至少一个实例的 `mergeable_children >= 100` 且 `mergeable_children / nonterminal_children >= 0.05`，才可继续。

分母是主搜索原 J 剪枝后、guide 前呈交索引的非终止 child，不含 root、终端或 greedy 补全内部候选。分子不包含更低 J 的代表替换。不要用终端生成次数或 hash 命中次数代替这个门槛。

**D0 未通过时本轮在此结束。** 保留诊断，不修改容量或改用近似相等后继续原协议。F30 入口会核对 D0 判定及其原始证据，不应绕过该检查。

## 5. D0 通过后执行 F30

```bash
python scripts/run_eight_neighbor_rolling_merge.py run --stage F30
python scripts/run_eight_neighbor_rolling_merge.py analyze --stage F30
```

F30 为四实例 × C0/C1/C0_M/C1_M × 三次重复，共 48 项。每项新进程、相同总 30 s 上限；共同初始化重新来自冻结 S30，不能沿用 D0 已付费得到的路线或缓存。

C1/C1_M 的在线计算映射到原虚拟任务时间轴，执行期间按旧路线飞向承诺锚点。程序无需按真实飞行时长等待。所有新索引开销与原评分接纳仍在任务预算内。

## 6. 中断、失败与复核

再次执行同阶段 `run` 时，已完成任务只有在证据一致时才可复用；失败、部分写入和身份不一致的记录不应被自动覆盖。保留错误原始记录。需要修复后重新实验时，使用新的输出目录，按完整流程重新准备，并记录与旧目录的关系。

不要删除慢运行或未改善运行后重新汇总。旧 pilot 中 Hudson 4101 的一个 C0 计时重复没有改善，是有效结果；本轮采用同样保留原则。

`key_build_s` 是 `lookup_s` 的组成部分；总开销图表不能将它们相加。64 MiB payload 也不能直接写成整进程内存上限。资源报告应使用实际进程 RSS。

各阶段生成的 `incumbent_history.csv` 是内层候选诊断，不能直接当作已经完成外层审计、可以在线接替的时刻，也不提供同质量 time-to-target 加速证明。

## 7. 回传材料

把整个新输出目录及人工 `ANALYSIS.md` 提交到当前分支，至少保留：

- 冻结协议、任务表、全部验证尝试、命令和环境记录；
- D0 原始结果、阶段报告和 `D0_gate.json`，无论是否通过；
- 若运行 F30，完整 48 项记录、四个配对比较、合并诊断与资源指标；
- 失败、迟到、容量停止登记和其他异常证据；
- 根据 [RESULTS_TEMPLATE.md](RESULTS_TEMPLATE.md) 填写的人工解释。

原 H2 粒子档案无需再次复制到新输出目录；保存其身份引用即可。判定先看有效性，再看 D0，再看四个 F30 配对，最后解释机制，不只上传最好一项结果。
