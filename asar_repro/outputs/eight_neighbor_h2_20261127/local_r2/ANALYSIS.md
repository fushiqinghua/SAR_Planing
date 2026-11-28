# H2 新日期 forcing 核验与八邻接对照

**状态 `new_date_J_transfer_signal`。** 已核验候选日期 6/6，已保存粒子档案 12/12，正式任务 S30 12/12、H30 144/144。

## 1. 方法与评价身份

- 方法于 2026-11-27T16:34:42.456Z 冻结。确认批提交为 `972082c62868a00f4e6f43e42ceb46df42ab49ed`，采用证据为 `completion_development_screen_passed`。原始方法、评价及历史证据已核验。 [方法锁](method_lock.json)
- 主目标为共同观测时钟上的累计未发现质量 J。终点 Pd 取自同一条路线。采用 `completion_J`，排序权重 1.04，OPEN 上限 100000，每 128 次展开触发补全，最多 32 次。
- 两种邻接共用固定地速 20 m/s、q=0.78、同一粒子档案与初始航线。主覆盖为 heading_square，axis_square 用于敏感性分析。默认单进程串行、数学库单线程、2 GiB RSS 上限。
- 预注册协议规定六个日期块、每日期两个粒子 seed、每个搜索条件三次计时重复。 [H2 预注册](../../../docs/eight_neighbor_confirmation/H2_PREREGISTRATION.md)

## 2. 日期、forcing 与资格判定

- 回传同时存档 150 份已按 SHA-256 核对的请求收据、GRIB 索引和提供方目录。原始风流二进制在本地保存。 [取数证据索引](acquisition_receipts/index.json)

- 当前通过资格的日期 6/6。状态 `six_dates_qualified`。 尚待处理 无。 [资格审计](availability_audit.json) · [历史快照](availability_snapshots)

| 区块 | LKP 日期 | 登记 | Seeds | CST UTC | 已核验原生窗口 | 资格状态 | 选择 | 依据或阻断 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lake_h2_d1 | 2025-08-12 | 主 | 3101, 3102 | 2025-08-12T15:45:00.000Z | 2025-08-12T14:45:00Z – 2025-08-12T15:53:00Z | eligible | 已选入 |  | [来源清单＋哈希](sources/lake_h2_d1/qualification/20261127T170121824428Z/source_manifest.json) |
| lake_h2_d2 | 2025-09-09 | 主 | 3201, 3202 | 2025-09-09T15:45:00.000Z | 2025-09-09T14:45:00Z – 2025-09-09T15:53:00Z | eligible | 已选入 |  | [来源清单＋哈希](sources/lake_h2_d2/qualification/20261127T170123068228Z/source_manifest.json) |
| lake_h2_d3 | 2025-09-23 | 主 | 3301, 3302 | 2025-09-23T15:45:00.000Z | 2025-09-23T14:45:00Z – 2025-09-23T15:53:00Z | eligible | 已选入 |  | [来源清单＋哈希](sources/lake_h2_d3/qualification/20261127T170124281411Z/source_manifest.json) |
| lake_h2_alt1 | 2025-08-05 | 候补 | 3401, 3402 | 2025-08-05T15:45:00.000Z | — | not_run | — |  |  |
| lake_h2_alt2 | 2025-09-16 | 候补 | 3501, 3502 | 2025-09-16T15:45:00.000Z | — | not_run | — |  |  |
| lake_h2_alt3 | 2025-09-30 | 候补 | 3601, 3602 | 2025-09-30T15:45:00.000Z | — | not_run | — |  |  |
| hudson_h2_d1 | 2025-08-15 | 主 | 4101, 4102 | 2025-08-16T00:00:00.000Z | 2025-08-15T00:00:00Z – 2025-08-16T00:48:00Z | eligible | 已选入 |  | [来源清单＋哈希](sources/hudson_h2_d1/qualification/20261127T170125483538Z/source_manifest.json) |
| hudson_h2_d2 | 2025-09-12 | 主 | 4201, 4202 | 2025-09-13T00:00:00.000Z | 2025-09-12T00:00:00Z – 2025-09-13T00:48:00Z | eligible | 已选入 |  | [来源清单＋哈希](sources/hudson_h2_d2/qualification/20261127T170128872089Z/source_manifest.json) |
| hudson_h2_d3 | 2025-09-26 | 主 | 4301, 4302 | 2025-09-27T00:00:00.000Z | 2025-09-26T00:00:00Z – 2025-09-27T00:48:00Z | eligible | 已选入 |  | [来源清单＋哈希](sources/hudson_h2_d3/qualification/20261127T170132269081Z/source_manifest.json) |
| hudson_h2_alt1 | 2025-08-08 | 候补 | 4401, 4402 | 2025-08-09T00:00:00.000Z | — | not_run | — |  |  |
| hudson_h2_alt2 | 2025-09-19 | 候补 | 4501, 4502 | 2025-09-20T00:00:00.000Z | — | not_run | — |  |  |
| hudson_h2_alt3 | 2025-10-03 | 候补 | 4601, 4602 | 2025-10-04T00:00:00.000Z | — | not_run | — |  |  |

| 区块 | 场 | 原始有效时刻 | 首帧 UTC | 末帧 UTC | 场维度 | 分量基准 | 湿样本冰未知 | 湿样本冰非零 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lake_h2_d1 | wind | 5 | 2025-08-12T13:00:00+00:00 | 2025-08-12T17:00:00+00:00 | [5, 1059, 1799, 2] | grid_relative | — | — |
| lake_h2_d1 | current | 5 | 2025-08-12T13:00:00+00:00 | 2025-08-12T17:00:00+00:00 | [5, 64453, 3] | geographic_east_north | — | — |
| lake_h2_d2 | wind | 5 | 2025-09-09T13:00:00+00:00 | 2025-09-09T17:00:00+00:00 | [5, 1059, 1799, 2] | grid_relative | — | — |
| lake_h2_d2 | current | 5 | 2025-09-09T13:00:00+00:00 | 2025-09-09T17:00:00+00:00 | [5, 64453, 3] | geographic_east_north | — | — |
| lake_h2_d3 | wind | 5 | 2025-09-23T13:00:00+00:00 | 2025-09-23T17:00:00+00:00 | [5, 1059, 1799, 2] | grid_relative | — | — |
| lake_h2_d3 | current | 5 | 2025-09-23T13:00:00+00:00 | 2025-09-23T17:00:00+00:00 | [5, 64453, 3] | geographic_east_north | — | — |
| hudson_h2_d1 | wind | 11 | 2025-08-14T21:00:00+00:00 | 2025-08-16T03:00:00+00:00 | [11, 16, 30, 2] | geographic_east_north | — | — |
| hudson_h2_d1 | current | 31 | 2025-08-14T21:00:00+00:00 | 2025-08-16T03:00:00+00:00 | [31, 63, 45, 2] | geographic_east_north | 0 | 0 |
| hudson_h2_d2 | wind | 11 | 2025-09-11T21:00:00+00:00 | 2025-09-13T03:00:00+00:00 | [11, 16, 30, 2] | geographic_east_north | — | — |
| hudson_h2_d2 | current | 31 | 2025-09-11T21:00:00+00:00 | 2025-09-13T03:00:00+00:00 | [31, 63, 45, 2] | geographic_east_north | 0 | 0 |
| hudson_h2_d3 | wind | 11 | 2025-09-25T21:00:00+00:00 | 2025-09-27T03:00:00+00:00 | [11, 16, 30, 2] | geographic_east_north | — | — |
| hudson_h2_d3 | current | 31 | 2025-09-25T21:00:00+00:00 | 2025-09-27T03:00:00+00:00 | [31, 63, 45, 2] | geographic_east_north | 0 | 0 |

- Lake 使用 13–17Z 的 HRRR 10 m f00 风和同日 18Z LOOFS nowcast 的原生顶层流。Hudson 使用前日 18Z GFS 的 11 帧 0.25° 风和 ESPC-D-V02 原生网格的 31 帧小时表层流。Hudson 区块需要成对有限的湿样本及已知为零的 sic。
- 这是历史环境重建。LOOFS 的 nowcast cycle 晚于任务开始。HYCOM 年度归档的 UTC 有效时刻与逐帧可发布时间是不同证据。当前结论不支持实时预报条件下的性能。

## 3. 软件验证与失败记录

| 验证尝试 | 状态 | 退出码 | 总数及分类 | 命令 | JUnit | 错误日志 |
| --- | --- | --- | --- | --- | --- | --- |
| 20261127T164144808308Z | failed | 1 | {'total': 392, 'passed': 391, 'failed': 1, 'error': 0, 'skipped': 0} | [命令与结果](validation/20261127T164144808308Z/result.json) | [JUnit](validation/20261127T164144808308Z/pytest.xml) | [stderr](validation/20261127T164144808308Z/stderr.log) |
| 20261127T164222429843Z | failed | 1 | {'total': 392, 'passed': 351, 'failed': 0, 'error': 41, 'skipped': 0} | [命令与结果](validation/20261127T164222429843Z/result.json) | [JUnit](validation/20261127T164222429843Z/pytest.xml) | [stderr](validation/20261127T164222429843Z/stderr.log) |
| 20261127T164243542132Z | failed | 1 | {'total': 392, 'passed': 383, 'failed': 9, 'error': 0, 'skipped': 0} | [命令与结果](validation/20261127T164243542132Z/result.json) | [JUnit](validation/20261127T164243542132Z/pytest.xml) | [stderr](validation/20261127T164243542132Z/stderr.log) |
| 20261127T164448520775Z | passed | 0 | {'total': 392, 'passed': 392, 'failed': 0, 'error': 0, 'skipped': 0} | [命令与结果](validation/20261127T164448520775Z/result.json) | [JUnit](validation/20261127T164448520775Z/pytest.xml) | [stderr](validation/20261127T164448520775Z/stderr.log) |

| 全量尝试 | 通过 | 失败 | 错误 | 跳过 | 总计 | 证据 |
| --- | --- | --- | --- | --- | --- | --- |
| full_pytest.xml | 0 | 0 | 13 | 0 | 13 | [全量 JUnit](full_pytest.xml) |
| full_pytest_r2.xml | 1663 | 4 | 0 | 0 | 1667 | [全量 JUnit](full_pytest_r2.xml) |
| full_pytest_r3.xml | 1667 | 0 | 0 | 0 | 1667 | [全量 JUnit](full_pytest_r3.xml) |

- 绑定当前代码、环境的配置内测试通过数 392。命令、标准输出及错误日志见 [执行日志](commands)。

## 4. 日期锁与粒子档案

- 日期锁绑定六个通过资格的区块。 [日期锁](date_lock.json)
- 粒子锁绑定 12 份档案与 84 项文件。 记录的 OpenDrift 运行次数为 12。 [粒子锁](inputs_lock.json)

| 粒子实例 | Seed | LKP UTC | CST UTC | 漂移次数 | 初始质量 | 最大质量误差 | 粒子 SHA-256 | 清单 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hudson_h2_d1_s4101 | 4101 | 2025-08-15T00:00:00.000Z | 2025-08-16T00:00:00.000Z | 1 | — | 4.440892098500626e-16 | d24d13520e32b5c09a071ceebc8cb83430e89cf9c9d770de1499c0fd8cee8408 | [粒子清单](inputs/hudson_h2_d1_s4101/manifest.json) |
| hudson_h2_d1_s4102 | 4102 | 2025-08-15T00:00:00.000Z | 2025-08-16T00:00:00.000Z | 1 | — | 4.440892098500626e-16 | f42034f70e42b5697859f4956ee8a14fbe7f662994b0a18864101dede25cc35f | [粒子清单](inputs/hudson_h2_d1_s4102/manifest.json) |
| hudson_h2_d2_s4201 | 4201 | 2025-09-12T00:00:00.000Z | 2025-09-13T00:00:00.000Z | 1 | — | 6.661338147750939e-16 | 0794cb7f9912e11cbdc37da2b6666a6cfe6e8d4e94c896bd4afc63411cd9d3ba | [粒子清单](inputs/hudson_h2_d2_s4201/manifest.json) |
| hudson_h2_d2_s4202 | 4202 | 2025-09-12T00:00:00.000Z | 2025-09-13T00:00:00.000Z | 1 | — | 6.661338147750939e-16 | 47e20e3db2bb59b282faff9befd37858795c1c64c4ae382e680dd8e218f4fed7 | [粒子清单](inputs/hudson_h2_d2_s4202/manifest.json) |
| hudson_h2_d3_s4301 | 4301 | 2025-09-26T00:00:00.000Z | 2025-09-27T00:00:00.000Z | 1 | — | 4.440892098500626e-16 | f3fc8fabe533c8df32ef48fe80fa4f2ba5118c55ba664a8342e24d8defbd4e13 | [粒子清单](inputs/hudson_h2_d3_s4301/manifest.json) |
| hudson_h2_d3_s4302 | 4302 | 2025-09-26T00:00:00.000Z | 2025-09-27T00:00:00.000Z | 1 | — | 4.440892098500626e-16 | 09eb46bf5d99c05b4d51a09f82100338084b9496ee9d4f5e86c8f1d652fd419f | [粒子清单](inputs/hudson_h2_d3_s4302/manifest.json) |
| lake_h2_d1_s3101 | 3101 | 2025-08-12T14:45:00.000Z | 2025-08-12T15:45:00.000Z | 1 | — | 6.661338147750939e-16 | c8dd0df61e761c2efd4491a6474ae29019a5bbcbdf8ba3f028513e687c3e8c96 | [粒子清单](inputs/lake_h2_d1_s3101/manifest.json) |
| lake_h2_d1_s3102 | 3102 | 2025-08-12T14:45:00.000Z | 2025-08-12T15:45:00.000Z | 1 | — | 6.661338147750939e-16 | 1e8326f22d37ccbe95f013013c56c62071040cfb77a34e8d3bf70d0a1dd6db1c | [粒子清单](inputs/lake_h2_d1_s3102/manifest.json) |
| lake_h2_d2_s3201 | 3201 | 2025-09-09T14:45:00.000Z | 2025-09-09T15:45:00.000Z | 1 | — | 6.661338147750939e-16 | aea9a401651df72d03bbacdcbdf5f6f4f234286bfc3a322719150622d596d885 | [粒子清单](inputs/lake_h2_d2_s3201/manifest.json) |
| lake_h2_d2_s3202 | 3202 | 2025-09-09T14:45:00.000Z | 2025-09-09T15:45:00.000Z | 1 | — | 6.661338147750939e-16 | e55779dff21703f7038706e2abfdf2c37283581502874abc990a725300f35549 | [粒子清单](inputs/lake_h2_d2_s3202/manifest.json) |
| lake_h2_d3_s3301 | 3301 | 2025-09-23T14:45:00.000Z | 2025-09-23T15:45:00.000Z | 1 | — | 6.661338147750939e-16 | 7a817a1496a1ad3faf3b46384d6d525067fe45e81338ad3dbf53cedac5083885 | [粒子清单](inputs/lake_h2_d3_s3301/manifest.json) |
| lake_h2_d3_s3302 | 3302 | 2025-09-23T14:45:00.000Z | 2025-09-23T15:45:00.000Z | 1 | — | 6.661338147750939e-16 | 4970ac0ec1b5319579817c59db3dbb32b991ba9a9f069d43140283ac41f87dc6 | [粒子清单](inputs/lake_h2_d3_s3302/manifest.json) |

## 5. 正式对照、计费与判定

- 已登记 S30 与 H30。状态 `new_date_J_transfer_signal`。 [协议](protocol.json) · [共同初始化锁](s30_lock.json) · [逐次 CSV](comparison.csv) · [完整剩余质量曲线](survival.csv)

| 阶段 | 计划 | 核验通过 | 缺失 | 错误 | 算法墙钟 s | CPU s | 进程墙钟 s | 峰值 MiB | 最大超时返回 s | 停止原因 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S30 | 12 | 12 | 0 | 0 | 12.9482 | 12.9844 | 29.9646 | 254.1992 | 0.0000 | {'None': 12} |
| H30 | 144 | 144 | 0 | 0 | 4275.5359 | 4253.5938 | 4473.8112 | 694.4492 | 0.1810 | {'max_seconds': 133, 'max_open': 11} |


| S30 实例 | Axis J | Axis Pd | Heading J | Heading Pd | 首个新完整重放 s | 最终来源 | 原始结果 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hudson_h2_d3_s4301 | 33.8731 | 0.727163 | 33.8731 | 0.727163 | 1.2170 | original_paper_greedy | [S30_bc1c0113e91dba383fe1](runs/S30_bc1c0113e91dba383fe1/result.json) |
| hudson_h2_d2_s4202 | 59.7967 | 0.014383 | 59.7967 | 0.014383 | — | parallel_track | [S30_e98fa1a5181f18f41eb1](runs/S30_e98fa1a5181f18f41eb1/result.json) |
| lake_h2_d1_s3102 | 14.6185 | 0.937545 | 14.6185 | 0.937545 | 0.3100 | original_paper_greedy | [S30_fefe2c0eee2a3da835dc](runs/S30_fefe2c0eee2a3da835dc/result.json) |
| lake_h2_d1_s3101 | 14.4551 | 0.946332 | 14.4551 | 0.946332 | 1.5993 | original_paper_greedy | [S30_c983c5070477cfa0a589](runs/S30_c983c5070477cfa0a589/result.json) |
| hudson_h2_d1_s4102 | 29.0615 | 0.802739 | 29.0615 | 0.802739 | 1.5913 | original_paper_greedy | [S30_d4d9055dee6f700e9405](runs/S30_d4d9055dee6f700e9405/result.json) |
| lake_h2_d3_s3301 | 8.2427 | 0.994645 | 8.2427 | 0.994645 | 1.5180 | original_paper_greedy | [S30_bb6fd01172cbc2119e5a](runs/S30_bb6fd01172cbc2119e5a/result.json) |
| lake_h2_d3_s3302 | 8.6013 | 0.994571 | 8.6013 | 0.994571 | 0.1281 | original_paper_greedy | [S30_f07806680aec5a9915e8](runs/S30_f07806680aec5a9915e8/result.json) |
| lake_h2_d2_s3201 | 14.1248 | 0.926848 | 14.1248 | 0.926848 | 0.6097 | original_paper_greedy | [S30_f17285250aaae2b25feb](runs/S30_f17285250aaae2b25feb/result.json) |
| hudson_h2_d3_s4302 | 34.7297 | 0.702512 | 34.7297 | 0.702512 | 1.3347 | original_paper_greedy | [S30_dc27368a254eb768839c](runs/S30_dc27368a254eb768839c/result.json) |
| hudson_h2_d1_s4101 | 28.7246 | 0.814235 | 28.7246 | 0.814235 | 4.3953 | original_paper_greedy | [S30_c625e062f23f9f81fd97](runs/S30_c625e062f23f9f81fd97/result.json) |
| lake_h2_d2_s3202 | 14.2267 | 0.913722 | 14.2267 | 0.913722 | 0.1978 | original_paper_greedy | [S30_5caff86fe3fdb4548ab6](runs/S30_5caff86fe3fdb4548ab6/result.json) |
| hudson_h2_d2_s4201 | 59.8364 | 0.013166 | 59.8364 | 0.013166 | — | parallel_track | [S30_bc42ee04ee0113b82cab](runs/S30_bc42ee04ee0113b82cab/result.json) |

S30 的首个新候选时间取已返回并完成离散和物理桥接重放的路线。两个物理覆盖共用同一条经验证的路线。H30 的计时计入共同路线复制、补全、评分和归档。

| 实例 | 覆盖 | 四邻接 J | 八邻接 J | J 改善 | 四邻接 Pd | 八邻接 Pd | ΔPd 百分点 | 墙钟中位 4 / 8 s | RSS 中位 4 / 8 MiB | 成对路径 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| hudson_h2_d1_s4101 | axis_square | 28.550297 | 28.344988 | +0.7191% | 0.812736 | 0.817508 | 0.4772 | 30.0995 / 30.0480 | 473.0625 / 282.9688 | [4 邻接](runs/H30_5146c09f704d4307a3b3/result.json) · [8 邻接](runs/H30_19b85a2ae0b49fb732ef/result.json) |
| hudson_h2_d1_s4101 | heading_square | 28.550297 | 28.448980 | +0.3549% | 0.812736 | 0.812461 | -0.0276 | 30.0966 / 30.0865 | 456.1875 / 420.4258 | [4 邻接](runs/H30_b2c7cff50a8d80b50fdb/result.json) · [8 邻接](runs/H30_2bc6e6a9b458c4e692a0/result.json) |
| hudson_h2_d1_s4102 | axis_square | 29.061472 | 28.837023 | +0.7723% | 0.803201 | 0.810548 | 0.7347 | 30.0578 / 30.0282 | 305.8086 / 217.4805 | [4 邻接](runs/H30_cf984feffb69bcb738a8/result.json) · [8 邻接](runs/H30_9e4e56be5fe40b5b6a0c/result.json) |
| hudson_h2_d1_s4102 | heading_square | 29.061472 | 28.671687 | +1.3412% | 0.803201 | 0.809022 | 0.5821 | 30.0571 / 30.0731 | 298.7266 / 367.8633 | [4 邻接](runs/H30_e70306a5e3e66062976a/result.json) · [8 邻接](runs/H30_8b9f8e49a645d02d589b/result.json) |
| hudson_h2_d2_s4201 | axis_square | 59.106182 | 58.679914 | +0.7212% | 0.074350 | 0.086260 | 1.1910 | 30.0015 / 30.0017 | 110.1875 / 109.9492 | [4 邻接](runs/H30_3daa95eac0a15bfbdd77/result.json) · [8 邻接](runs/H30_87a6c3c4b2403bd3d5d1/result.json) |
| hudson_h2_d2_s4201 | heading_square | 59.106182 | 58.739707 | +0.6200% | 0.074350 | 0.085808 | 1.1459 | 30.0015 / 30.0017 | 110.1875 / 110.9414 | [4 邻接](runs/H30_ed4293299b291ff50679/result.json) · [8 邻接](runs/H30_51d57a459c98c415159c/result.json) |
| hudson_h2_d2_s4202 | axis_square | 59.408448 | 59.004459 | +0.6800% | 0.056503 | 0.072530 | 1.6027 | 30.0016 / 30.0016 | 111.4570 / 109.9922 | [4 邻接](runs/H30_5e98cab3e29042fc443c/result.json) · [8 邻接](runs/H30_a85f51a6574518a62bc6/result.json) |
| hudson_h2_d2_s4202 | heading_square | 59.413424 | 58.964390 | +0.7558% | 0.054488 | 0.070627 | 1.6139 | 30.0016 / 30.0017 | 111.5039 / 109.7305 | [4 邻接](runs/H30_57f679e21952e5519caf/result.json) · [8 邻接](runs/H30_e751970d05cf9a2aed9b/result.json) |
| hudson_h2_d3_s4301 | axis_square | 33.873134 | 33.873134 | +0.0000% | 0.727163 | 0.727163 | 0.0000 | 30.0574 / 30.0111 | 311.7188 / 147.3125 | [4 邻接](runs/H30_5953ce9e3ee0d1227a26/result.json) · [8 邻接](runs/H30_9abcbd4c9ca6f76fb7cf/result.json) |
| hudson_h2_d3_s4301 | heading_square | 33.873134 | 33.563737 | +0.9134% | 0.727163 | 0.726429 | -0.0734 | 30.0565 / 30.0151 | 302.9961 / 163.0234 | [4 邻接](runs/H30_364a4511982ed45be0cf/result.json) · [8 邻接](runs/H30_4d98a7c78b517630ae3b/result.json) |
| hudson_h2_d3_s4302 | axis_square | 34.719377 | 34.164202 | +1.5990% | 0.707256 | 0.718930 | 1.1674 | 30.0933 / 30.0478 | 467.2969 / 289.3594 | [4 邻接](runs/H30_2d4089d5f7f00bc8c646/result.json) · [8 邻接](runs/H30_bba6a0c033e0a977234b/result.json) |
| hudson_h2_d3_s4302 | heading_square | 34.719377 | 33.942881 | +2.2365% | 0.707256 | 0.717257 | 1.0001 | 30.0915 / 30.0223 | 450.8633 / 193.6875 | [4 邻接](runs/H30_807a07045766503a947a/result.json) · [8 邻接](runs/H30_b4cc69dc5f5636347f1d/result.json) |
| lake_h2_d1_s3101 | axis_square | 14.455101 | 14.313046 | +0.9827% | 0.946332 | 0.947762 | 0.1430 | 29.0079 / 30.1023 | 691.9609 / 426.6445 | [4 邻接](runs/H30_f9cd00e133635c255081/result.json) · [8 邻接](runs/H30_97044e61312190610a48/result.json) |
| lake_h2_d1_s3101 | heading_square | 14.455101 | 14.307067 | +1.0241% | 0.946332 | 0.949103 | 0.2772 | 30.1474 / 30.0562 | 632.6016 / 312.8672 | [4 邻接](runs/H30_57136e4bad84652b5abe/result.json) · [8 邻接](runs/H30_e6c5b03ef7de21f7f318/result.json) |
| lake_h2_d1_s3102 | axis_square | 14.567154 | 14.495933 | +0.4889% | 0.943172 | 0.948596 | 0.5424 | 30.1715 / 30.0466 | 661.9922 / 263.1211 | [4 邻接](runs/H30_c4dfce40eac77ec6bdc5/result.json) · [8 邻接](runs/H30_0a547c5665da0c772820/result.json) |
| lake_h2_d1_s3102 | heading_square | 14.567154 | 14.503859 | +0.4345% | 0.943172 | 0.943985 | 0.0813 | 30.1587 / 30.0527 | 628.9805 / 276.6016 | [4 邻接](runs/H30_424a87c07e90ff5e17af/result.json) · [8 邻接](runs/H30_2ed21202e96e1c61a3fc/result.json) |
| lake_h2_d2_s3201 | axis_square | 14.124790 | 13.966798 | +1.1185% | 0.926848 | 0.933810 | 0.6962 | 30.1601 / 30.1223 | 622.5625 / 527.6250 | [4 邻接](runs/H30_51fc7f301a0a00d9bc1d/result.json) · [8 邻接](runs/H30_cc094d04a185a8f769c5/result.json) |
| lake_h2_d2_s3201 | heading_square | 14.124790 | 14.058509 | +0.4693% | 0.926848 | 0.930400 | 0.3552 | 30.1480 / 30.1032 | 581.9180 / 456.6641 | [4 邻接](runs/H30_a7e333b842c7f96e1a2e/result.json) · [8 邻接](runs/H30_c18c9b381aa38ad1e43a/result.json) |
| lake_h2_d2_s3202 | axis_square | 14.221205 | 14.130629 | +0.6369% | 0.914796 | 0.915272 | 0.0476 | 30.0719 / 30.0441 | 368.3359 / 245.8594 | [4 邻接](runs/H30_eae037706178b8771201/result.json) · [8 邻接](runs/H30_b054a8de12139e95f494/result.json) |
| lake_h2_d2_s3202 | heading_square | 14.221205 | 14.121651 | +0.7000% | 0.914796 | 0.915602 | 0.0806 | 30.0703 / 30.0388 | 347.1406 / 240.1211 | [4 邻接](runs/H30_7171510f78eb8f72682b/result.json) · [8 邻接](runs/H30_fa2f8cac4b9514b7b669/result.json) |
| lake_h2_d3_s3301 | axis_square | 8.242713 | 7.513989 | +8.8408% | 0.994645 | 0.996282 | 0.1637 | 21.8258 / 30.1248 | 676.6484 / 487.2266 | [4 邻接](runs/H30_e180b1a28190e6001fd4/result.json) · [8 邻接](runs/H30_0203374f41aa8f2dab93/result.json) |
| lake_h2_d3_s3301 | heading_square | 8.242713 | 7.278931 | +11.6925% | 0.994645 | 0.997441 | 0.2796 | 21.6344 / 30.1441 | 677.7852 / 569.4414 | [4 邻接](runs/H30_a30d6b89254642791230/result.json) · [8 邻接](runs/H30_0f375ab14bf85cd1305c/result.json) |
| lake_h2_d3_s3302 | axis_square | 8.601277 | 7.558165 | +12.1274% | 0.994571 | 0.996567 | 0.1996 | 29.7214 / 30.1156 | 686.9766 / 474.9688 | [4 邻接](runs/H30_260d966fe73896b1772c/result.json) · [8 邻接](runs/H30_224c9c9816824726d033/result.json) |
| lake_h2_d3_s3302 | heading_square | 8.601277 | 7.446095 | +13.4304% | 0.994571 | 0.995819 | 0.1248 | 30.1639 / 30.1069 | 652.1406 / 452.1602 | [4 邻接](runs/H30_85cc020406716b25494e/result.json) · [8 邻接](runs/H30_e5410329f08f79e83ecb/result.json) |

每个搜索条件先取 3 次的 J 中位数，再从同一次运行取 Pd。完整轨迹与资源波动见 [Seed 汇总](seed_comparison.csv)，[观测时刻剩余质量](survival.csv)。

| 地区 | 区块 | Seeds | 两 Seed 改善中位 | 判定值 | 通过改善门槛 | 退化 |
| --- | --- | --- | --- | --- | --- | --- |
| arctic_ocean | hudson_h2_d1 | 4101, 4102 | +0.8481% | +0.8481% | True | False |
| arctic_ocean | hudson_h2_d2 | 4201, 4202 | +0.6879% | +0.6879% | True | False |
| arctic_ocean | hudson_h2_d3 | 4301, 4302 | +1.5749% | +1.5749% | True | False |
| lake_ontario | lake_h2_d1 | 3101, 3102 | +0.7293% | +0.7293% | True | False |
| lake_ontario | lake_h2_d2 | 3201, 3202 | +0.5846% | +0.5846% | True | False |
| lake_ontario | lake_h2_d3 | 3301, 3302 | +12.5614% | +12.5614% | True | False |

日期尺度的判定只使用主覆盖。Axis、终点 Pd 及生存曲线保留用于解释覆盖敏感性和目标权衡。 [日期判定 CSV](date_comparison.csv) · [结构化汇总](summary.json)

## 运行中断与恢复

原 H30 会话在第 49 项中断时已有 48 项有效结果。原目录及未完成任务完整保留。恢复目录按登记顺序保留全部 12 项 S30 和 48 项已完成的 H30，逐文件核对 SHA-256，从第 49 项继续。两段使用同一冻结协议、任务顺序、方法、初始路线、输入和单项预算。费用按逐次算法和进程记录汇总，恢复间隔单列为会话事件。 [恢复指纹](resume_provenance.json) · [原中断任务](../local_r1/runs/H30_5e98cab3e29042fc443c) · [恢复日志](commands/H30-resume.stdout.log)

## 日期差异与终点 Pd

- 六个主覆盖日期的 J 降幅中位数为 0.7887%。Lake 9 月 23 日的降幅为 12.5614%，另五个日期为 0.5847% 至 1.5749%。轴对齐覆盖的六个日期也全部改善。 [日期判定](date_comparison.csv) · [逐 seed 同路线分数](seed_comparison.csv)
- Lake 9 月 23 日两个 seed 的主覆盖代表路线中，前 16 个观测贡献了 J 差值的约 74.7% 和 83.1%，终点 Pd 分别提高 0.28 和 0.12 个百分点。较大的 J 差值主要来自本次观测序列早段。 [剩余质量曲线](survival.csv)
- Hudson 9 月 12 日两个 seed 在 CST 分别有 77.6% 和 79.2% 的原始粒子质量位于规划域外。主覆盖的八邻接终点 Pd 分别为 8.58% 和 7.06%，相对四邻接有所改善，绝对概率仍低。 [seed 4201 质量账本](inputs/hudson_h2_d2_s4201/mass_audit.json) · [seed 4202 质量账本](inputs/hudson_h2_d2_s4202/mass_audit.json)
- 主覆盖有两个 Hudson seed 的终点 Pd 分别下降 0.028 和 0.073 个百分点，轴对齐覆盖下未观察到 Pd 下降。主结论按 J 的日期门槛判定。 [逐 seed 同路线分数](seed_comparison.csv)

## 适用范围

日期是外推单位。两个粒子 seed 和三次计时重复嵌套在日期内。本协议的固定日期块不能代表任意未来海况，也不验证几何覆盖代理的实机性能。

现有 `completion_J` 在有限计算预算内提供可行路线和已观测的质量差异。本报告不提供全局最优或 ε 最优认证。
