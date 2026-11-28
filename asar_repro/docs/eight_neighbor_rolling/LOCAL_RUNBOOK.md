# 本地执行说明

交付状态：`prepared_not_run`。这些命令由用户在本地执行。交付者仅做静态阅读与检查，没有执行项目模块、测试、搜索、路线重放或 OpenDrift。

## 1. 获取分支并使用原环境

在本地仓库根目录执行：

```bash
git fetch origin
git switch eight-neighbor-rolling-pilot-20261128
cd asar_repro
```

继续使用此前成功运行 H2 的 Python 环境和依赖。本轮不要求重新下载风流场、重新生成粒子或重新安装环境。

输入来源固定为：

```text
outputs/eight_neighbor_h2_20261127/local_r2/
```

必须保留其中的冻结配置、方法/日期/粒子/初始路线锁，以及本轮四例对应的完整粒子档案、质量账本和 S30 参考记录。`preflight` 会指出缺失或不一致的文件。应恢复原有相同 hash 文件，不能用新生成的一份粒子样本代替。

本轮配置和输出位置：

```text
configs/eight_neighbor_rolling.json
outputs/eight_neighbor_rolling_20261128/local_r1/
```

以下所有命令都在 `asar_repro` 目录执行，Windows PowerShell 和常见 shell 均可逐行运行。

## 2. 查看任务和核对历史来源

```bash
python scripts/run_eight_neighbor_rolling.py plan --config configs/eight_neighbor_rolling.json --out outputs/eight_neighbor_rolling_20261128/local_r1
python scripts/run_eight_neighbor_rolling.py preflight --config configs/eight_neighbor_rolling.json --out outputs/eight_neighbor_rolling_20261128/local_r1
```

应看到四个固定实例、C0/C1、三次重复和 24 个 R30 任务。正式算法预算合计为 720 s；本地测试、读取、进程启动与审计另需时间。

`preflight` 会检查代码身份、冻结来源、粒子档案、时钟和共同路线，并对已存路线作必要语义重放。它不生成新的漂移或运行新的路线优化。

若不通过，先保留输出中的原因。此时不应跳过检查继续正式任务，也不应修改锁文件使其与当前数据“匹配”。恢复正确来源或修复实现后，使用新的输出目录重新准备。

Windows 环境若因 Git 自动转换 CRLF/LF 导致受保护源码字节指纹不同，应在 `core.autocrlf=false` 的干净工作树中检出仓库版本，再按原指纹核验。不要重新计算参考指纹来迁就本地换行或其他改动；二者会掩盖真正的代码变化。

## 3. 运行本地软件验证

```bash
python scripts/run_eight_neighbor_rolling.py validate --config configs/eight_neighbor_rolling.json --out outputs/eight_neighbor_rolling_20261128/local_r1
```

配置内验证覆盖：

- `tests/test_physical_model.py`
- `tests/test_physical_search.py`
- `tests/test_physical_accel.py`
- `tests/test_physical_refinement.py`
- `tests/test_physical_rolling.py`
- `tests/test_eight_neighbor_rolling_runner.py`

每次尝试保存命令、环境、标准输出、错误输出和测试报告。出现失败时保留原尝试，不只上传最后一次通过的报告。交付时没有预填测试通过数量。

这里的测试包含小型语义验证，和正式 R30 测量是不同阶段。测试通过也不等于 C1 指标会改善。

## 4. 冻结协议

```bash
python scripts/run_eight_neighbor_rolling.py freeze --config configs/eight_neighbor_rolling.json --out outputs/eight_neighbor_rolling_20261128/local_r1
```

冻结时绑定配置、相关代码、来源证据、环境、成功验证结果和确定的任务顺序。此后如果修改这些内容，须另起版本/输出目录并重新验证、冻结；不能沿用旧协议解释新结果。

正式配置只登记一套滚动日程，不在本轮自行修改触发比例、预算、实例或重复数。

## 5. 执行唯一正式阶段 R30

```bash
python scripts/run_eight_neighbor_rolling.py run --config configs/eight_neighbor_rolling.json --out outputs/eight_neighbor_rolling_20261128/local_r1
```

无需另加阶段参数。runner 按已冻结顺序串行创建任务进程，记录单线程设置、RSS、算法/进程耗时、停止原因和完整路线。

两组的 30 s 是总可接纳计算预算。C1 使用 5 个固定槽，不能把每次重规划改成 30 s。程序中的物理执行时间轴通过路线与计算延迟推进，不会按任务飞行时长等待。

### 中断和恢复

再次执行 `run` 时，已经完成且验证一致的任务会被核对；失败、部分写入或身份不一致的任务不会被悄悄覆盖。保留这些文件并依据错误信息处理。

若需要重新执行一个失败的实验版本，使用新的输出目录，重新走 preflight、validate、freeze、run。不要删除失败任务后让汇总看起来像一次完整无失败运行。恢复方式和跨目录关系应写入人工分析。

## 6. 生成汇总

```bash
python scripts/run_eight_neighbor_rolling.py analyze --config configs/eight_neighbor_rolling.json --out outputs/eight_neighbor_rolling_20261128/local_r1
```

主要交付文件包括：

| 文件 | 用途 |
| --- | --- |
| `protocol.json` 及任务清单 | 冻结定义与可复现任务身份 |
| `runs/` | 完整路线、阶段账本、资源信息和原始记录 |
| `comparison.csv` | 每次 C0/C1 结果 |
| `instance_comparison.csv` | 每个实例的配对中位数、J 改善和同路线 Pd |
| `survival.csv` | 原观测轴上的剩余质量和累计发现概率 |
| `phases.csv` | C1 触发、锚点、准备完成、接纳和计算支出 |
| `summary.json` | 完整性、各条件与总体判定 |
| `REPORT.md` | 自动可读报告 |

自动分析不会覆盖人工 `ANALYSIS.md`。将 [RESULTS_TEMPLATE.md](RESULTS_TEMPLATE.md) 的结构用于人工说明；如有缺失或失败，保留并解释。

## 7. 推送供复核

将本轮完整输出与人工 `ANALYSIS.md` 提交到这个新分支，包括失败尝试和原始任务证据。不要只提交几张图或一张最好结果表。

本轮不需要把原 H2 大体积来源再次复制到新目录；保留相对来源、冻结身份和 hash 引用即可。新代码与结果一起推送后，可以直接按固定提交复核。

人工分析应先写“有效性是否通过”，再写“J 和 Pd 是否达到预声明门槛”，最后讨论机制。若未通过，不先追加更多参数组合；按 [DECISIONS.md](DECISIONS.md) 决定是否结束本配置。
