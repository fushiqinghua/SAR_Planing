# P2/H3 同前缀搜索诊断

本批使用冻结的 H3 目标、物理评分器、历史 forcing 和 S30 初始路线。55 次原始记录包括 45 次同前缀等展开量试验、8 次 Hudson 延长预算试验及 2 次 4601 容量试验。143 项 toy/Oracle 和专项测试均通过。

## 4501 的等展开量对照

三组各运行三次，每次有效展开 32,768 个状态。九次都交付同一路线，J 为 55.655905440，终点 Pd 为 19.1407008%。

| 模式 | OPEN 峰值中位数 | 峰值 RSS 中位数 |
|---|---:|---:|
| 单堆全局 | 1,974 | 104.14 MiB |
| 三堆全局 | 1,974 | 104.51 MiB |
| 三堆原配额 | 44,033 | 352.75 MiB |

从三堆原配额切换到三堆全局取点后，OPEN 峰值中位数下降 **95.5%**，峰值 RSS 中位数下降 **70.4%**，J、Pd 和路线均相同。

## 4601 的 120 秒高容量诊断

原 100,000 OPEN 上限下，延长预算的 C0 和 Lazy 均触及容量上限，主搜索生成终点数均为零。随后以 200,000 OPEN 上限运行两次独立的 C0 容量诊断。

- 首次高容量试验找到更优内层候选。外层在 120.041204 秒收到结果，超过 120 秒期限，因此按规则**退回 S30**。内层候选另有双重物理重放。
- 将交付预留由 0.25 秒调至 2 秒后，在相同 120 秒总预算下复跑。外层实际耗时 **118.221 秒**，按时交付了与首次内层候选相同的路线。J 为 **55.191382368**，终点 Pd 为 **22.7242704%**。

与冻结的 30 秒 C0 对照值相比，按时交付路线的 J 改善 **2.2561%**，Pd 增加 **6.0876 个百分点**。该收益属于 **120 秒、200,000 OPEN 上限的高容量诊断**。原 30 秒 C0 的对照记录仍由 H3 协议固定。

## 原始证据

- [最终报告](results/local_r1/analysis_final/REPORT.md) · [汇总 JSON](results/local_r1/analysis_final/summary.json) · [RSS 曲线](results/local_r1/analysis_final/hudson_rss.png)
- [等展开量 CSV](results/local_r1/analysis_final/fixed_work.csv) · [延长预算 CSV](results/local_r1/analysis_final/extended.csv) · [两次容量诊断 CSV](results/local_r1/analysis_final/capacity_4601.csv)
- [45 次等展开量和 8 次延长预算的原始记录](results/local_r1/runs) · [首次高容量试验及回退](results/local_r1/capacity_4601) · [复跑及首次候选的独立重放](results/local_r1/capacity_4601_delivery)
- [冻结协议](results/local_r1/protocol.json) · [测试日志](results/local_r1/validation) · [命令与交付复核](results/local_r1/commands)

## 离线核验和复跑

归档保留原测试、结果、时钟和 SHA-256。脚本位于 H3 冻结源码扫描目录之外，保留了源码与相邻结果目录的原有结构。原始命令中的绝对路径记录实验机上的位置。从原始输入重跑需要原 H3 归档保存的 forcing、粒子数组和其余本地源资料，以及协议登记的运行环境。源资料的指纹见 [H3 资格和输入清单](../second_innovation_h3_20261128/)。

在原实验环境中，从 `asar_repro` 项目根目录设置项目导入路径并核验已发布归档。

```powershell
$diag = (Resolve-Path '.\outputs\p2_h3_frontier_diagnostic').Path
$env:PYTHONPATH = (Join-Path $PWD.Path 'scripts') + ';' + (Join-Path $PWD.Path 'src')
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:ASAR_OFFLINE = '1'
python (Join-Path $diag 'run_diagnostic.py') freeze
```

要重新求解，在独立目录复制六份 Python 文件，按测试日志中的参数重新生成该目录的 `results/local_r1/validation`。依次执行 `run_diagnostic.py freeze`、`run_diagnostic.py fixed` 和 `run_diagnostic.py extended`。容量试验的两个入口会检查触发它们的原始结果。报告生成入口为 `report_diagnostic.py`。
