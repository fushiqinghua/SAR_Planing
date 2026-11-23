# STDC 修复：验证与同预算对照

本轮 STDC 修复未改善真实场景返回 J；重复计算问题得到针对性处理，弱下界导致的有限预算路径质量问题仍未解决。

## 修复范围与对照

- 原实现 reference 从 Git 提交 `4a01dee2275ce3b732f619e0192fd1a417a5766e` 冻结 search.py 与 stdc_heuristic.py 后加载复跑；不将新实现伪装成旧基线。
- 本轮只处理等价几何计算、完整状态启发式缓存、严格状态支配。原 STDC 下界公式未增强，规划目标、forcing、粒子、初始 PT 和预算均未改变。
- 两个新增搜索选项默认关闭。paper_reuse/mass_reuse 也使用相同复用机制，以区分通用工程优化与 STDC 特有收益。

| variant | 启发式 | 原冻结搜索 | 完整状态支配 | h 缓存条目上限 |
|---|---|---|---|---:|
| paper_reference | paper_greedy | True | False | 0 |
| mass_reference | mass_lb | True | False | 0 |
| stdc_reference | stdc_lb | True | False | 0 |
| stdc_geometry | stdc_lb | False | False | 0 |
| stdc_cache | stdc_lb | False | False | 4096 |
| stdc_reuse | stdc_lb | False | True | 4096 |
| paper_reuse | paper_greedy | False | True | 4096 |
| mass_reuse | mass_lb | False | True | 4096 |

## 强制门槛与数据

| 阶段 | 状态 | 测试数 / 说明 |
|---|---|---|
| new_tests | passed | {'tests': 93, 'errors': 0, 'failures': 0, 'skipped': 0} |
| full_tests | passed | {'tests': 356, 'errors': 0, 'failures': 0, 'skipped': 0} |
| random_audit | passed | 见阶段命令、stdout/stderr、JSON 与源码指纹 |
| small_search | passed | 见阶段命令、stdout/stderr、JSON 与源码指纹 |
| lake_smoke | passed | 见阶段命令、stdout/stderr、JSON 与源码指纹 |
| comparison | passed | 见阶段命令、stdout/stderr、JSON 与源码指纹 |

- 合成小图：160 个场景、18024 个前缀，超出 1e-10 的可采纳性违规数为 0；最大正差 8.88e-16。
- 35 组小图：历史搜索 490 次，修复选项搜索 630 次；共 1120 条路径独立评分与 Oracle 检查。
- 真实 Lake Ontario：粒子及原始风流指纹门禁通过；17×17、500 粒子、T=49、q=.78、seed=41，t=0 不探测。未重新运行 Leeway。
- 8 variants × 3 ε × 3 次独立进程 = 72 次；统一 PT 初始解及 5000 expansions / 20000 OPEN / 30 s，方法次序按重复轮转。
- geometry/cache 与原 STDC 的路径、J、状态、节点计数须完全一致，驱动器已强制检查。支配会改变被扩展的完整状态集合，按 Oracle 和独立回放验证。
- depth_stats 为 trace 观测最深生成/完整候选，含 dominance_prune；最后预算边界的节点可能在回调前退出，不能将这些观测计数当成所有内部节点的绝对精确总数。

## 完整 ε 对照：三次重复的中位数

| ε | variant | J↓ | Pd↑ | 扩展 | 秒〔min–max〕 | 峰值 MiB | completed/budget | incumbent 来源 | 条件认证 |
|---|---|---:|---:|---:|---:|---:|---|---|---|
| 1.10 | paper_reference | 17.359684022 | 0.897769 | 107 | 0.1353〔0.1273–0.1400〕 | 70.02 | 3/0 | search:3 | 0/3 |
| 1.10 | mass_reference | 20.477608336 | 0.881063 | 5000 | 0.3680〔0.3484–0.3798〕 | 152.25 | 0/3 | initial_path:3 | 0/3 |
| 1.10 | stdc_reference | 20.477608336 | 0.881063 | 5000 | 10.3829〔9.2209–11.3199〕 | 157.95 | 0/3 | initial_path:3 | 0/3 |
| 1.10 | stdc_geometry | 20.477608336 | 0.881063 | 5000 | 7.2134〔6.3545–7.4905〕 | 161.17 | 0/3 | initial_path:3 | 0/3 |
| 1.10 | stdc_cache | 20.477608336 | 0.881063 | 5000 | 5.0720〔4.4321–5.1376〕 | 189.25 | 0/3 | initial_path:3 | 0/3 |
| 1.10 | stdc_reuse | 20.477608336 | 0.881063 | 5000 | 6.9368〔6.3797–7.4779〕 | 249.08 | 0/3 | initial_path:3 | 0/3 |
| 1.10 | paper_reuse | 17.359684022 | 0.897769 | 107 | 0.1342〔0.1283–0.1447〕 | 71.59 | 3/0 | search:3 | 0/3 |
| 1.10 | mass_reuse | 20.477608336 | 0.881063 | 5000 | 0.4433〔0.4341–0.4443〕 | 222.00 | 0/3 | initial_path:3 | 0/3 |
| 1.04 | paper_reference | 17.293894155 | 0.897370 | 1222 | 0.9602〔0.9388–0.9990〕 | 88.98 | 3/0 | search:3 | 0/3 |
| 1.04 | mass_reference | 20.477608336 | 0.881063 | 5000 | 0.3588〔0.3367–0.3742〕 | 152.23 | 0/3 | initial_path:3 | 0/3 |
| 1.04 | stdc_reference | 20.477608336 | 0.881063 | 5000 | 9.2554〔8.9765–9.3001〕 | 158.11 | 0/3 | initial_path:3 | 0/3 |
| 1.04 | stdc_geometry | 20.477608336 | 0.881063 | 5000 | 6.6647〔6.5730–6.6651〕 | 161.76 | 0/3 | initial_path:3 | 0/3 |
| 1.04 | stdc_cache | 20.477608336 | 0.881063 | 5000 | 4.2199〔4.1964–4.3467〕 | 188.63 | 0/3 | initial_path:3 | 0/3 |
| 1.04 | stdc_reuse | 20.477608336 | 0.881063 | 5000 | 6.7446〔6.5671–6.7835〕 | 249.42 | 0/3 | initial_path:3 | 0/3 |
| 1.04 | paper_reuse | 17.293894155 | 0.897370 | 1216 | 0.9938〔0.9740–1.0006〕 | 109.64 | 3/0 | search:3 | 0/3 |
| 1.04 | mass_reuse | 20.477608336 | 0.881063 | 5000 | 0.4370〔0.4238–0.4505〕 | 221.95 | 0/3 | initial_path:3 | 0/3 |
| 1.00 | paper_reference | 20.477608336 | 0.881063 | 5000 | 5.3199〔4.5233–7.8238〕 | 155.54 | 0/3 | initial_path:3 | 0/3 |
| 1.00 | mass_reference | 20.477608336 | 0.881063 | 5000 | 0.3660〔0.3385–0.6012〕 | 152.22 | 0/3 | initial_path:3 | 0/3 |
| 1.00 | stdc_reference | 20.477608336 | 0.881063 | 5000 | 9.1519〔9.0598–11.9739〕 | 158.20 | 0/3 | initial_path:3 | 0/3 |
| 1.00 | stdc_geometry | 20.477608336 | 0.881063 | 5000 | 6.4894〔6.4344–7.7041〕 | 162.06 | 0/3 | initial_path:3 | 0/3 |
| 1.00 | stdc_cache | 20.477608336 | 0.881063 | 5000 | 4.2079〔4.1948–5.1007〕 | 188.96 | 0/3 | initial_path:3 | 0/3 |
| 1.00 | stdc_reuse | 20.477608336 | 0.881063 | 5000 | 6.6287〔6.5689–8.6693〕 | 249.61 | 0/3 | initial_path:3 | 0/3 |
| 1.00 | paper_reuse | 20.477608336 | 0.881063 | 5000 | 5.1535〔4.6181–5.9163〕 | 239.18 | 0/3 | initial_path:3 | 0/3 |
| 1.00 | mass_reuse | 20.477608336 | 0.881063 | 5000 | 0.4561〔0.4197–0.5389〕 | 221.96 | 0/3 | initial_path:3 | 0/3 |

budget_exceeded 均为 uncertified；具体 max_expansions/max_open/max_seconds 逐行保留于 metrics.csv。paper_greedy 的 completed 也不具有动态 ε 认证。

## 配对差异与归因

| ε | variant / 对照 | ΔJ | 时间倍数 | Δ峰值 MiB | J 改善次数 |
|---|---|---:|---:|---:|---|
| 1.10 | stdc_geometry / stdc_reference | +0.000000000 | 0.689× | +3.21 | 0/3 |
| 1.10 | stdc_cache / stdc_geometry | +0.000000000 | 0.697× | +27.91 | 0/3 |
| 1.10 | stdc_reuse / stdc_cache | +0.000000000 | 1.439× | +59.76 | 0/3 |
| 1.10 | stdc_reuse / stdc_reference | +0.000000000 | 0.668× | +91.13 | 0/3 |
| 1.10 | stdc_reuse / paper_reference | +3.117924314 | 50.123× | +179.05 | 0/3 |
| 1.10 | stdc_reuse / paper_reuse | +3.117924314 | 51.679× | +177.48 | 0/3 |
| 1.10 | stdc_reuse / mass_reuse | +0.000000000 | 15.647× | +27.13 | 0/3 |
| 1.04 | stdc_geometry / stdc_reference | +0.000000000 | 0.720× | +3.70 | 0/3 |
| 1.04 | stdc_cache / stdc_geometry | +0.000000000 | 0.638× | +26.87 | 0/3 |
| 1.04 | stdc_reuse / stdc_cache | +0.000000000 | 1.565× | +60.69 | 0/3 |
| 1.04 | stdc_reuse / stdc_reference | +0.000000000 | 0.733× | +91.26 | 0/3 |
| 1.04 | stdc_reuse / paper_reference | +3.183714181 | 6.839× | +160.34 | 0/3 |
| 1.04 | stdc_reuse / paper_reuse | +3.183714181 | 6.826× | +139.69 | 0/3 |
| 1.04 | stdc_reuse / mass_reuse | +0.000000000 | 15.435× | +27.47 | 0/3 |
| 1.00 | stdc_geometry / stdc_reference | +0.000000000 | 0.709× | +3.84 | 0/3 |
| 1.00 | stdc_cache / stdc_geometry | +0.000000000 | 0.652× | +26.89 | 0/3 |
| 1.00 | stdc_reuse / stdc_cache | +0.000000000 | 1.580× | +60.61 | 0/3 |
| 1.00 | stdc_reuse / stdc_reference | +0.000000000 | 0.724× | +91.39 | 0/3 |
| 1.00 | stdc_reuse / paper_reference | +0.000000000 | 1.246× | +93.97 | 0/3 |
| 1.00 | stdc_reuse / paper_reuse | +0.000000000 | 1.422× | +10.42 | 0/3 |
| 1.00 | stdc_reuse / mass_reuse | +0.000000000 | 15.653× | +27.71 | 0/3 |

- geometry / reference 衡量保持数值与搜索顺序的几何加速；cache / geometry 衡量完整 belief 的 h 复用；reuse / cache 衡量严格支配的新增影响。
- 只有对 paper_reference 的 J/Pd/时间差能回答相对原 baseline A^SAR 的本场景表现；对 paper_reuse 的差异进一步控制通用搜索优化。改善旧 STDC 的耗时不等于超过 paper baseline。
- 本轮没有新增更紧的下界。若完整候选仍为零或 J 仍等于初始 PT，不将计算加速解释成路径质量瓶颈已修复。

## 正确性前提与内存代价

- 支配键包括 depth、vertex、belief dtype/shape/完整字节；运动、传感器和时域在单次搜索内固定。相同完整状态的任意合法后缀具有相同未来 belief 和新增代价，因此仅保留较小 g 不损失更优完成路径。更小 g 重新入队，较大 g 的旧堆项过期跳过。
- 未按 (depth,vertex) 合并、未用哈希碰撞身份或浮点容差近似合并；路径历史必须仅通过当前完整 belief、位置、深度影响未来。若以后加入转向、燃油或历史约束，必须扩展状态键。
- h 的 LRU 上限为 4096 条；几何缓存额外浮点数组上限为 16 MiB，可达整数数组另计。完整状态支配表保留遇到的状态，并不由 OPEN 条目数直接限制，可能增加内存。
- metrics 的字节计数只覆盖相应键载荷/数组；可能共享引用，不宜直接相加当作进程增量。峰值 MiB 为独立工作进程 peak working set，包含输入校验、预处理和回放，不是纯搜索堆。
- 预算中止无 ε 认证。可采纳模式仅在离散模型前提成立且搜索完成时具有条件性 ε 界；本地有限测试不是全输入形式化浮点证明。
- 真实历史环境归档沿用 allwater 假设与本地 PT，不声称复现原作者私有 forcing 或手工 PT。三次重复不是三个独立场景。

## 文件与复跑

- metrics.csv：72 条运行；aggregate.json/CSV：24 组汇总及配对解释；paired_differences.csv：逐重复差值。
- repair_performance.png：ε=1.10 的耗时、扩展、J、内存；repair_paths_survival.png：独立回放的路径和剩余质量。
- 各阶段目录保留命令、seed、stderr、JUnit、JSON 和 git diff；comparison 每个子目录保留完整路径和来源。
- 初始化新目录后，按 new_tests → full_tests → random_audit → small_search → lake_smoke → comparison 顺序运行 scripts/run_stdc_repair.py。
- 报告命令：`python scripts/report_stdc_repair.py --run-dir <本轮目录>`；拒绝覆盖已有 report 目录。
- 本轮没有实施新下界或第二个创新点；没有修改 baseline-v1.1、B7 原始结果和评价器。


## 本轮交付补充记录

- 首次尝试 ../repair_20261123 在 pytest 临时目录 fixture 创建阶段遇到 WinError 3，保留为 blocked；该用例未进入断言。创建按 run 隔离的临时父目录后，本轮从新测试重新执行全部阶段，356 项全量测试无失败、错误或跳过。未跳过任何历史测试。
- 完整源码文件清单见 ../code_files.json。审计 allowlist 只追加本轮授权的 search.py 精确 SHA；历史 B4/B6 仍按原冻结提交核验，另增加“篡改 search.py 必须被拒绝”的负例。
- 实测工程选择见 selected_settings.json：本场景使用 heuristic_cache_size=4096, exact_dominance=False，可获得更低耗时/内存；严格状态支配仍为可选实验功能，不默认开启。此选择不能改善本次 J。
- 离线复跑入口：../replay.ps1（自动使用新目录）；完整命令与实际执行信息见 ../execution_records.json 和各阶段 stage.json。
- baseline 654 个文件及研究目录中 1106 个旧数据/结果/受保护源码均再次核验不变，见 ../final_preservation.json。
- 本轮未推送 GitHub；未修改原仿真程序或新增下界模式。全部真实预算中止均保持 uncertified。

配对表中的时间倍数是逐重复时间比的中位数；它不一定等于两组耗时中位数的比值。
