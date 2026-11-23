# Baseline v1.1 最终验证报告

**B7 状态：passed。**

复跑基准 Git commit：624d2176c206b8f7df852975708f0ae510626820；v1.0 标签：abd1b472798fbf3d318e83d09caf9b69cc459122。
B7 仅新增验证、归档、报告与实验协议文件；数值核心与已验收实验不修改。新增验证脚本通过源码指纹及 ZIP 成员清单记录，Git bundle 保存复跑时 HEAD。

| 强制门槛 | 状态 | 证据/失败原因 |
|---|---|---|
| frozen_integrity | passed | {'v1_commit': 'abd1b472798fbf3d318e83d09caf9b69cc459122', 'v1_files': 180, 'git_blobs_verified': True, 'original_worktree_present': True, 'original_worktree_verified': True, 'intentional_v1_1_changes': ['asar_repro/src/asar_repro/planner_adapter.py'], 'frozen_file_count': 426, 'real_files': 10} |
| full_pytest | passed | {'passed': 234, 'pytest_s': 21.86, 'command': ['C:\\Users\\35448\\.conda\\envs\\maritime-sar\\python.exe', '-m', 'pytest', '-q'], 'exit_code': 0} |
| dynamic_counterexample | passed | {'h': 2.617080177088715, 'oracle_J': 2.541733337874664, 'overestimate': 0.07534683921405083, 'paper_certified': False} |
| real_forcing | passed | {'status': 'passed', 'files': 10, 'exact_fields_samples_controls': True} |
| constant_regression | passed | {'arrays': 18, 'exact_equal': True} |
| real_particle_reintegration | passed | {'stage': 'B3', 'status': 'passed', 'mode': 'independent_replay', 'config_hash': 'b7f8f7261148f6e9cf9a4cb68a0ab3e751f729a666c9b977f9e5646ccfec7ca8', 'archive_sha256': '8b30a87e543f1b33c39e70e1d0054e1750ec046ba2e0b627dd311d9945749456', 'native': {'first_utc': '2025-08-26T14:45:00Z', 'last_utc': '2025-08-26T15:53:00Z', 'frames': 137}, 'search': {'first_utc': '2025-08-26T15:45:00Z', 'last_utc': '2025-08-26T15:52:33.74Z', 'frames': 50}, 'compared_npz_arrays': 21, 'exact_replay': True, 'forcing_terminal_events': 0, 'archive_integration_seconds': 6.837059700046666, 'runtime_seconds': 8.622577699949034} |
| all_path_replay | passed | {'old_normalized_records': 527, 'old_marine_paths': 436, 'old_marine_max_error': 8.526512829121202e-14, 'additional_record_groups': {'b5/scan_runs.json': 38, 'b5/pilot_runs.json': 6, 'lake_ontario_real/runs.json': 7, 'outputs\\baseline_v1.1\\b6_failed_attempt_01\\b6_workers\\paper_greedy_1.1.json': 1}, 'toy_rows': 72, 'max_real_replay_error': 2.7755575615628914e-17} |
| performance_evidence | passed | {'main_scan_runs': 36, 'stop_distribution': {'completed': 10, 'max_expansions': 26}, 'probe_stops': {'max_open': 2}, 'peak_process_MiB_range': [66.90625, 152.66015625], 'certified_runs': 0} |
| b6_offline_rerun | passed | {'runs': 7, 'exact_paths_scores_counters_status': True, 'timing_remeasured_separately': True} |
| old_outputs_unchanged | passed | {'files': 426, 'all_unchanged': True} |
| offline_archive | passed | {'path': 'outputs\\baseline_v1.1\\b7_final\\baseline_v1_1_offline.zip', 'sha256': '54af40879e64cce8650086f57c8fad2ab441e992dd53864b1cd3eee5669ad5c4', 'bytes': 287452681, 'verified_entries': 485, 'git_bundle_sha256': '67192eb11afd8c0f74d1518007828f53df63ea461fb91fbde352ec735972d581', 'raw_forcing_included': True, 'reports': 'final report and validation_summary are sidecars generated after ZIP verification'} |
| restored_entrypoint | passed | {'exit_code': 0, 'all_mandatory_gates_passed': True, 'pytest': {'passed': 234, 'pytest_s': 23.26, 'command': ['C:\\Users\\35448\\.conda\\envs\\maritime-sar\\python.exe', '-m', 'pytest', '-q'], 'exit_code': 0}, 'protocol_identical': True, 'protocol_sha256': 'bc18ddcb922231168aef34d8805bd3f7388a2b3ed9c27e9522368141fa469ff7', 'source_identical_to_tested_archive': True, 'archive_sha256': '54af40879e64cce8650086f57c8fad2ab441e992dd53864b1cd3eee5669ad5c4', 'wall_s': 127.53409810003359, 'summary': 'restored_validation_summary.json', 'log': 'restored_replay.json'} |

本轮环境：{'python': '3.11.18', 'platform': 'Windows-10-10.0.26200-SP0', 'numpy': '2.4.6', 'scipy': '1.17.1', 'pyproj': '3.7.2', 'opendrift': '1.14.12'}。实际解释器：C:\Users\35448\.conda\envs\maritime-sar\python.exe。完整已安装包版本单列保存；未安装或升级 OpenDrift。

## 已复现：数学实现与可验证事实

Eq.(1)、(5)–(7)、t=0 无探测、四邻接路径、独立 DFS Oracle、路径专属未探测权重与无路径连续性约束的 Algorithm 2 保持原行为。搜索/启发式/评分器字节与 v1.0 一致；v1.1 对原版 180 文件的唯一变更为 planner_adapter.py 的报告字段与计时扩展。旧 v1.0 Git 对象可恢复，原工作树是否存在及逐文件核验结果单列。
独立真实积分比较全部 21 个 NPZ 字段；恒定环境 run_constant 按原配置重新积分后与旧归档逐字段比较。正常/中止、PT/search/no-path、条件认证以及原动态反例均有回归测试。
3×3、T=4、q=.78 反例：paper_greedy 根值 2.6170801771，大于 Oracle 2.5417333379。另一个动态 ε=1 的例子返回次优路径。paper_greedy 本地保持未认证；mass_lb/zero 仅在模型前提成立且搜索完成时可记条件性离散界。浮点实例验证不是所有场景的形式证明或实海安全保证。

## 近似复现：一组完整历史风流与 Leeway

已完成 Lake Ontario 的本地 HRRR 风 + LOOFS 流配对。事件日期 2025-08-26，缓存有效 UTC 为 13–17 时；事故 14:45，CST 15:45，搜索结束 15:52:33.740，原生轨迹到 15:53。500 粒子，seed=41，PIW-2，137 原生帧与 50 规划帧，T=49、q=.78。
HRRR：5 个各自循环的 f00 分析，10 m UGRD/VGRD，m/s；获取方式为官方 S3 对原始 GRIB2 的逐字节消息范围提取，非完整全变量文件。原生 Lambert 双线性插值后旋转为东/北分量。
LOOFS：5 个原始 FVCOM netCDF，18 UTC nowcast 循环提供回算有效时次；u/v，m/s，最浅 sigma≈−0.025，含点原生三角面内常值；时间线性插值，最大间隔 3600 s。
流场节点经纬度范围：[-79.80072021484375, -76.05899047851562, 43.180450439453125, 44.22895431518555]。搜索格心范围：[-76.51454365262846, -76.47745634737153, 44.20166472002214, 44.22833374483131]。风场原生投影范围与投影参数详见 forcing_audit.json 的 fields.wind.archive_extent。
reader 为本地 historical_reader.py，通过 OpenDrift 四个实际环境分量查询验证非 fallback。全水域岸线策略 historical_real_forcing_allwater；FVCOM 湿干/域外仍有显式状态，保留 land/outside/inactive/unknown 质量。289 格心中流场覆盖 221、域外 68；本次实际粒子云保持有效覆盖。缺测不会替换成虚构常量。

| 角色 | 有效 UTC | 本地文件 | SHA-256 |
|---|---|---|---|
| wind | 2025-08-26T13:00:00+00:00 | data/raw/historical/ASAR_B1_LakeOntario_20250826/raw/hrrr/hrrr.20250826.t13z.f00.10m_uv.grib2 | d23da8d2684adeb56f7b205d84135aecce0a7fbacbe50d94eca933831a524419 |
| wind | 2025-08-26T14:00:00+00:00 | data/raw/historical/ASAR_B1_LakeOntario_20250826/raw/hrrr/hrrr.20250826.t14z.f00.10m_uv.grib2 | e93eb9ebf9995368d535885e97c8442e50630b25e247e6efb938bb02b3ec06e4 |
| wind | 2025-08-26T15:00:00+00:00 | data/raw/historical/ASAR_B1_LakeOntario_20250826/raw/hrrr/hrrr.20250826.t15z.f00.10m_uv.grib2 | 644b9d28c24f01aeebc7fb75bcb7cb1468aece6068de5d4c37667e63d424130c |
| wind | 2025-08-26T16:00:00+00:00 | data/raw/historical/ASAR_B1_LakeOntario_20250826/raw/hrrr/hrrr.20250826.t16z.f00.10m_uv.grib2 | 46256f2a7357568baa37e1193120521f3cda5706549e69023d5f274621108654 |
| wind | 2025-08-26T17:00:00+00:00 | data/raw/historical/ASAR_B1_LakeOntario_20250826/raw/hrrr/hrrr.20250826.t17z.f00.10m_uv.grib2 | 71beb93fd7c77e25ce6f3a1d75d10198e703b7b436640c0909cf0d51c61cf447 |
| current | 2025-08-26T13:00:00+00:00 | data/raw/historical/ASAR_B1_LakeOntario_20250826/raw/loofs/loofs.t18z.20250826.fields.n001.nc | 7269134c0240c7f00eeca6e9e6bc39dc40ae49032004f8561c239510fcd7090f |
| current | 2025-08-26T14:00:00+00:00 | data/raw/historical/ASAR_B1_LakeOntario_20250826/raw/loofs/loofs.t18z.20250826.fields.n002.nc | 5092a254127774814da296dcc0edb302ca3320c5a8e2bd6f951d09ea25e75484 |
| current | 2025-08-26T15:00:00+00:00 | data/raw/historical/ASAR_B1_LakeOntario_20250826/raw/loofs/loofs.t18z.20250826.fields.n003.nc | ec3918e3251852e1646373b0aaa3e29f75232333879dfabcf37a547a3ffef4f3 |
| current | 2025-08-26T16:00:00+00:00 | data/raw/historical/ASAR_B1_LakeOntario_20250826/raw/loofs/loofs.t18z.20250826.fields.n004.nc | e16e82ce3149104f6f8d8e2d7ece55de11d1c7a7b1f36c2a9fd20b4714bac8c4 |
| current | 2025-08-26T17:00:00+00:00 | data/raw/historical/ASAR_B1_LakeOntario_20250826/raw/loofs/loofs.t18z.20250826.fields.n005.nc | aa575cf91f8ecb84e003389204cae11846fc9a22ac754b2817a4ccb367ee0682 |

逐文件官方 URL、获取范围/循环与读取元数据在原始来源清单、B3 metadata 和 B7 real_forcing_files.json 中保留。

## 相同真实输入的基线结果

| 方法 | ε | J | Pd(T) | 状态 | 来源 | 秒（求解/构造） |
|---|---:|---:|---:|---|---|---:|
| ParallelTrack | None | 20.4776083360 | 0.88106304 | completed | ParallelTrack | 0.001035 |
| ASAR_paper | 1.1 | 17.3596840221 | 0.89776904 | completed | search | 0.112852 |
| ASAR_paper | 1.04 | 17.2938941546 | 0.89737042 | completed | search | 0.899117 |
| ASAR_paper | 1.0 | 20.4776083360 | 0.88106304 | max_expansions | ParallelTrack | 4.627384 |
| ASAR_mass_lb | 1.1 | 20.4776083360 | 0.88106304 | max_expansions | ParallelTrack | 0.303682 |
| ASAR_mass_lb | 1.04 | 20.4776083360 | 0.88106304 | max_expansions | ParallelTrack | 0.320443 |
| ASAR_mass_lb | 1.0 | 20.4776083360 | 0.88106304 | max_expansions | ParallelTrack | 0.306231 |

上表保持原 B6 测量；B7 在独立目录再次运行，路径、J/Pd/M、节点计数、状态和来源相同，耗时另存。PT 不计搜索完成率；6 次搜索 2 完成、4 中止且保留 PT。本轮 B6 结果全部未获离散认证。
B0 冻结的旧 17/32 中止统计保持原数。B5 新真实输入 36 次扫描中 10 完成、26 因展开限制中止，另两个 OPEN=2400 探针中止；ε=1.04 从 600 上限的中止改善为 1222 次展开完成。新旧环境和预算不同，不能把两个完成率直接解释为算法改进。
J 是时间累积目标，Pd(T) 是末时刻指标；ε=1.04 的 J 更小而 Pd 略低。J_over_PT 的分母是本地 PT，不是最优值。原文 C++/M1 Pro 时间未改，本地 Python/Windows 不作跨机器加速比较。

## 未复现与已知局限

- 原作者精确模式循环、粒子、地图与人工 PT，以及原始完整真实实验未逐点复现。真实 forcing 不意味着已获得作者原数据。
- Bay of Fundy、Hudsons/Arctic 场景、Salish Sea 仍只有旧 constant_synthetic 验收结果。用户提供的其他 ZIP 尚未导入并完成变量、UTC/空间、reader 与质量审计；Salish 包还明确只有风场与核查记录。不能仅凭 ZIP 存在宣称完整真实风流可用。Lake 的旧 synthetic 证据也保留。
- 未实现岸线碰撞、海冰、飞行转弯/返航约束、在线滚动重规划及其他原系统集成。
- paper_greedy 的动态下界反例保留；mass_lb 与 ε=1 的大规模搜索在有限预算下未完成，不能补造证书。
- ACO_inspired 只保留旧合成对照，本轮不运行；没有 ACO_original 复现声明。
- Windows 单次计时与进程峰值受调度/导入影响；独立 cProfile/tracemalloc 诊断不混入原速统计。
- B6 首次调度的文件名后缀问题已修复且失败尝试保留，未纳入正式结果表。

## 移交、离线归档与冻结协议

本轮证据目录：outputs/baseline_v1.1/b7_final。validation_summary.json 为逐门槛权威状态；archive_checksum.json 给出 ZIP SHA-256 和逐条目复核数量。ZIP 包含缓存原始风流及 Git bundle，不包含 Conda 环境；最终报告和汇总为包旁侧文件。
方法与安装版本清单见 methods_and_environment.json。离线复跑与从 bundle 恢复步骤见 offline_replay.md。入口为现有 Python 解释器执行 scripts/replay_baseline_v1_1.py，无需改变 PowerShell 执行策略；失败必须输出 blocked 并非零退出。
下一阶段不可变主实验契约在 frozen_experiment_protocol.json，SHA 在 protocol_sha256.json。冻结真实粒子指纹、UTC/LKP/CSP/CST、T/q、ID/质量策略、统一评分器、同一初始 PT、5000/20000/30 秒限制与 ε 三档。后续随机方法预先冻结 seed 0–9、10 次；确定性计时建议三次并逐次保留。这些是未来协议，未冒充本轮已执行的创新实验。
扩展风流扰动、滚动重规划、其他场景须独立标记和单列；不得改变主实验输入后在同一主表宣称优越性。七项 baseline 绿灯条件已通过；这不要求四组真实场景全完成，也不要求 ε=1 大规模搜索全部结束。
本轮停止于 B7，不实施创新点。


## 离线恢复实测与交付索引

最终 ZIP 已从 Git bundle 恢复到独立新目录，再叠加归档文件，以同一现有 Python 解释器运行一键入口。11 项强制门槛全部通过，退出码 0；原工作区全量测试 234 passed / 21.86 s，恢复目录全量测试 234 passed / 23.26 s。恢复全流程用时 127.53 s。协议字节一致，5 份验证代码与归档字节一致。

首次候选归档的 PowerShell 脚本入口被本机执行策略阻止，该次交付状态保存为 blocked，证据保留在 outputs/baseline_v1.1/b7；未修改系统执行策略。最终入口改为 Python，随后重新生成 b7_final 归档，并实际恢复复跑通过。旧失败候选不构成最终验收通过证据。

本轮新增代码文件：

- scripts/validate_baseline_v1_1.py：指纹、测试、重积分、路径审计、性能证据、对照复跑与 ZIP 逐成员校验。
- scripts/report_baseline_v1_1.py：方法/环境、已知局限、冻结协议和报告自动生成。
- scripts/replay_baseline_v1_1.py：现有解释器的一键离线入口。
- scripts/offline_guard/sitecustomize.py：离线验证期间阻止 Python 出站 socket 连接。
- tests/test_b7_validation.py：门槛失败闭锁、NPZ 损坏、非零退出、blocked 报告及离线连接回归，共 5 项新增测试。

全量单测命令（入口会自动设置本项目所需 PYTHONPATH、DLL 路径与离线保护）：

    & 'C:\Users\35448\.conda\envs\maritime-sar\python.exe' -m pytest -q

在 asar_repro 目录一键离线复跑（输出到新的时间戳目录，不覆盖旧证据）：

    & 'C:\Users\35448\.conda\envs\maritime-sar\python.exe' scripts/replay_baseline_v1_1.py

若单独执行 pytest，先在当前 PowerShell 设置：

    $env:PYTHONPATH=(Resolve-Path 'src').Path
    $env:PATH='C:\Users\35448\.conda\envs\maritime-sar\Library\bin;'+$env:PATH

交付物索引均指向 outputs/baseline_v1.1/b7_final：

| 文件 | 内容 |
|---|---|
| validation_summary.json | 11 项强制门槛及额外恢复门槛 |
| restored_validation_summary.json、restored_replay.json | 从最终 ZIP 新目录恢复的实测证据 |
| frozen_inventory.json、v1_preservation.json | 426 份既有文件保持不变；原 v1.0 的 180 份文件与 Git blob、原工作树一致 |
| real_forcing_files.json、forcing_audit.json | 10 份真实风流的 SHA、来源、UTC、字段和 reader 核验 |
| methods_and_environment.json | 方法标签、解释器和完整安装版本清单 |
| frozen_experiment_protocol.json、protocol_sha256.json | 下一阶段冻结协议与指纹 |
| offline_replay.md | 一键复跑、Git bundle 恢复及环境要求 |
| b6_rerun/runs.json、b6_rerun/metrics.csv | 独立复跑的统一指标（原 B6 结果不覆盖） |
| b6_rerun/paths.png、b6_rerun/survival_curves.png、b6_rerun/runtime_expansions.png | 复跑路径、剩余质量和效率图 |
| baseline_v1_1_offline.zip、archive_checksum.json | 287452681 字节离线包，485 个 payload 条目逐一验证 |
| verification_code_sha256.json、delivery_sha256.json | 新验证代码及最终交付侧文件指纹 |

最终 ZIP SHA-256：54af40879e64cce8650086f57c8fad2ab441e992dd53864b1cd3eee5669ad5c4。
ZIP 已冻结，不因追加恢复日志而改写；最终报告、汇总与恢复证据作为包旁侧文件，由 delivery_sha256.json 统一核验。Git bundle 保存 B6 起始 HEAD 及旧版本历史，B7 新文件随 ZIP payload 交付。大型 ZIP/bundle 仅保存在本地，不纳入 Git。

本阶段没有新增规划算法、没有改变原海上搜救程序、没有新增 ε-最优声明；下一阶段实验仅冻结协议，尚未实施。
