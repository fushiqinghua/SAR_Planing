# 等价加速与 H1 预留实例结果

## 1. 执行身份

- 批次 eight-neighbor-followup-20261127。提交 212b8ee8fbcf1d4c952abfdb91ee6eaa1023582f。输出目录 E:\毕业设计\终稿研发\new\baseline\SAR_Planing-eight-neighbor-physical-study-20261127\asar_repro\outputs\eight_neighbor_followup_20261127\local_r1。
- 协议 SHA-256 0c14d65a32d62aac24881373621b4bb67cc4c3011a085ed49ac3bd10d2f14b3f。配置 SHA-256 1b540b529ba6e2de88accaee1d028efe9694dd3b81aabf448f633043d9f58583。
- Python 3.11.18 \| packaged by conda-forge \| (main, Oct 26 2026, 11:29:07) [MSC v.1944 64 bit (AMD64)]。解释器 c:\users\35448\.conda\envs\maritime-sar\python.exe。系统 Windows-10-10.0.26200-SP0。
- 处理器 unknown。逻辑核 32。总内存字节 16340455424。
- 依赖 numpy 2.4.6，scipy 1.17.1，pytest 9.2.0，psutil 7.2.2，pyproj 3.7.2，opendrift 1.14.12，xarray 2026.9.0，PyYAML 6.0.3，netCDF4 1.7.5，shapely 2.2.0，cfgrib not_installed，eccodes not_installed，numba not_installed。
- 线程设置 OMP_NUM_THREADS=1，OPENBLAS_NUM_THREADS=1，MKL_NUM_THREADS=1，NUMEXPR_NUM_THREADS=1，VECLIB_MAXIMUM_THREADS=1。
- 随机任务顺序 seed 20261128。基准保护提交 97dd989a488da8604b97fd287162e1b625310501。
- 原四邻、八邻源码的冻结保护证据 [protected_base_sources](protocol.json)。受保护清单条数 190。

- 预检状态 ready。[预检及 forcing 证据](preflight/20261127T135214086381Z/preflight.json)。
- 冻结前 forcing 盘点 ready。
- 本轮验证 passed，253 通过、0 失败、0 错误、0 跳过，总数 253。 [JUnit](validation/20261127T135215796890Z/pytest.xml) · [stdout](validation/20261127T135215796890Z/stdout.log) · [stderr](validation/20261127T135215796890Z/stderr.log)。
- 交付后本轮身份及已冻结源码 SHA-256 详见 [protocol.json](protocol.json)。本报告生成器位于仓库外，仅从保留的试验结果计算统计量。

- 本地已核验输入恢复过程见 [input_restore.json](input_restore.json)。

| 阶段 | 退出码 | 命令与日志 |
| --- | --- | --- |
| analysis | 未记录 | [命令](commands/analysis.command.json) · — · [stderr](commands/analysis.stderr.log) |
| audit | 0 | [命令](commands/audit.command.json) · [stdout](commands/audit.stdout.log) · [stderr](commands/audit.stderr.log) |
| D5 | 0 | [命令](commands/D5.command.json) · [stdout](commands/D5.stdout.log) · [stderr](commands/D5.stderr.log) |
| freeze-dev | 0 | [命令](commands/freeze-dev.command.json) · [stdout](commands/freeze-dev.stdout.log) · [stderr](commands/freeze-dev.stderr.log) |
| freeze-holdout | 0 | [命令](commands/freeze-holdout.command.json) · [stdout](commands/freeze-holdout.stdout.log) · [stderr](commands/freeze-holdout.stderr.log) |
| H30 | 0 | [命令](commands/H30.command.json) · [stdout](commands/H30.stdout.log) · [stderr](commands/H30.stderr.log) |
| plan | 0 | [命令](commands/plan.command.json) · [stdout](commands/plan.stdout.log) · [stderr](commands/plan.stderr.log) |
| preflight | 0 | [命令](commands/preflight.command.json) · [stdout](commands/preflight.stdout.log) · [stderr](commands/preflight.stderr.log) |
| prepare-inputs | 0 | [命令](commands/prepare-inputs.command.json) · [stdout](commands/prepare-inputs.stdout.log) · [stderr](commands/prepare-inputs.stderr.log) |
| S30 | 0 | [命令](commands/S30.command.json) · [stdout](commands/S30.stdout.log) · [stderr](commands/S30.stderr.log) |
| select-backend | 0 | [命令](commands/select-backend.command.json) · [stdout](commands/select-backend.stdout.log) · [stderr](commands/select-backend.stderr.log) |
| summarize | 0 | [命令](commands/summarize.command.json) · [stdout](commands/summarize.stdout.log) · [stderr](commands/summarize.stderr.log) |
| validate | 0 | [命令](commands/validate.command.json) · [stdout](commands/validate.stdout.log) · [stderr](commands/validate.stderr.log) |

## 2. P0 配对前缀审计

| 开发档案 | 覆盖 | 邻接 | 前缀展开 | 转移／引导 | 严格一致 | 停止原因 | 证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| lake_ontario | heading_square | 4 | 128 | 512 / 513 | True | fixed_work_complete | [P0_9f218f5715f1134432fd](runs/P0_9f218f5715f1134432fd/result.json) |
| lake_ontario | heading_square | 8 | 128 | 1024 / 1025 | True | fixed_work_complete | [P0_cbcfc7576764085552ae](runs/P0_cbcfc7576764085552ae/result.json) |
| lake_ontario | axis_square | 4 | 128 | 512 / 513 | True | fixed_work_complete | [P0_fc0deb0e490e9834fbed](runs/P0_fc0deb0e490e9834fbed/result.json) |
| lake_ontario | axis_square | 8 | 128 | 1024 / 1025 | True | fixed_work_complete | [P0_ff3688f80db828f93b40](runs/P0_ff3688f80db828f93b40/result.json) |
| arctic_ocean | heading_square | 4 | 128 | 512 / 513 | True | fixed_work_complete | [P0_b4c4a52bbd50268facb0](runs/P0_b4c4a52bbd50268facb0/result.json) |
| arctic_ocean | heading_square | 8 | 128 | 1024 / 1025 | True | fixed_work_complete | [P0_875a6554a9e5e6eb3136](runs/P0_875a6554a9e5e6eb3136/result.json) |
| arctic_ocean | axis_square | 4 | 128 | 512 / 513 | True | fixed_work_complete | [P0_07efe39131fea8ec1be8](runs/P0_07efe39131fea8ec1be8/result.json) |
| arctic_ocean | axis_square | 8 | 128 | 1024 / 1025 | True | fixed_work_complete | [P0_e887a214d821062474e2](runs/P0_e887a214d821062474e2/result.json) |

P0 的严格对照只覆盖共同展开的前缀，审计的双算时间不用于估计加速幅度。

## 3. 阶段完整性

| 阶段 | 计划任务 | 有效 | 失败或无效 | 缺失 | 状态 |
| --- | --- | --- | --- | --- | --- |
| P0 | 8 | 8 | 0 | 0 | complete |
| D5 | 48 | 48 | 0 | 0 | complete |
| S30 | 4 | 4 | 0 | 0 | complete |
| H30 | 48 | 48 | 0 | 0 | complete |

阶段汇总 [summary.json](summary.json) · [comparison.csv](comparison.csv)。各次运行的原始 J、Pd、停止原因和路径分别保存在链接的 result.json。

## 4. D5 同机质量保护

| 场景 | 覆盖 | 邻接 | 原 J 中位数 [范围] | 缓存 J 中位数 [范围] | 原／缓存 Pd 中位数 | 原／缓存有效数 | 质量保护 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| lake_ontario | heading_square | 4 | 17.264874448 [17.264874448, 17.264874448] | 17.264874448 [17.264874448, 17.264874448] | 0.897364416 / 0.897364416 | 3/3 · 3/3 | True |
| lake_ontario | heading_square | 8 | 16.752262696 [16.752262696, 16.752262696] | 16.752262696 [16.752262696, 16.752262696] | 0.904678365 / 0.904678365 | 3/3 · 3/3 | True |
| lake_ontario | axis_square | 4 | 17.264874448 [17.264874448, 17.264874448] | 17.264874448 [17.264874448, 17.264874448] | 0.897364416 / 0.897364416 | 3/3 · 3/3 | True |
| lake_ontario | axis_square | 8 | 17.264874448 [17.264874448, 17.264874448] | 17.264874448 [17.264874448, 17.264874448] | 0.897364416 / 0.897364416 | 3/3 · 3/3 | True |
| arctic_ocean | heading_square | 4 | 20.386109349 [20.386109349, 20.386109349] | 20.386109349 [20.386109349, 20.386109349] | 0.908583112 / 0.908583112 | 3/3 · 3/3 | True |
| arctic_ocean | heading_square | 8 | 20.386109349 [20.386109349, 20.386109349] | 20.317725022 [20.317725022, 20.317725022] | 0.908583112 / 0.910565427 | 3/3 · 3/3 | True |
| arctic_ocean | axis_square | 4 | 20.386109349 [20.386109349, 20.386109349] | 20.386109349 [20.386109349, 20.386109349] | 0.908583112 / 0.908583112 | 3/3 · 3/3 | True |
| arctic_ocean | axis_square | 8 | 20.386109349 [20.386109349, 20.386109349] | 20.386109349 [20.386109349, 20.386109349] | 0.908583112 / 0.908583112 | 3/3 · 3/3 | True |

重复范围为实测极值。J 与 Pd 的组中位数按各自指标计算。

## 5. D5 目标命中与选择锁定

| 场景／覆盖 | 目标 J | 原／缓存命中 | 原／缓存达标时间中位数 s | 时间减少 | 逐次达标记录 |
| --- | --- | --- | --- | --- | --- |
| lake_ontario / heading_square | 16.752262696441605 | 3/3（可核验 3） · 3/3（可核验 3） | 2.551975 / 2.119541 | 16.9451% | original [D5_787aca509575bc0f59f4](runs/D5_787aca509575bc0f59f4/result.json) 2.707 · original [D5_eb0962e2db252b46f6c9](runs/D5_eb0962e2db252b46f6c9/result.json) 2.499 · original [D5_bce9a3b2a09767c62d86](runs/D5_bce9a3b2a09767c62d86/result.json) 2.552 · cached [D5_9aa6d6cb742531d422f8](runs/D5_9aa6d6cb742531d422f8/result.json) 2.194 · cached [D5_638ee529dd0dbb43df88](runs/D5_638ee529dd0dbb43df88/result.json) 2.120 · cached [D5_5ba40f3c6c7fa81ec4cd](runs/D5_5ba40f3c6c7fa81ec4cd/result.json) 2.117 |
| lake_ontario / axis_square | 16.7169314627584 | 0/3（可核验 3） · 0/3（可核验 3） | unknown / unknown | — | original [D5_961bbf3fef3ea030184a](runs/D5_961bbf3fef3ea030184a/result.json) not_reached · original [D5_3f7eefbc63784c25b559](runs/D5_3f7eefbc63784c25b559/result.json) not_reached · original [D5_9cea31c9436a4f3ec74b](runs/D5_9cea31c9436a4f3ec74b/result.json) not_reached · cached [D5_00c31f200def5e18870a](runs/D5_00c31f200def5e18870a/result.json) not_reached · cached [D5_f74bca59b63a4fa0074f](runs/D5_f74bca59b63a4fa0074f/result.json) not_reached · cached [D5_641729ff3d0bcbe692f9](runs/D5_641729ff3d0bcbe692f9/result.json) not_reached |
| arctic_ocean / heading_square | 20.317725021888 | 0/3（可核验 3） · 3/3（可核验 3） | unknown / 4.235605 | — | original [D5_82443a2e08a1326e873d](runs/D5_82443a2e08a1326e873d/result.json) not_reached · original [D5_3b13f956ec87d5a99e9a](runs/D5_3b13f956ec87d5a99e9a/result.json) not_reached · original [D5_f068c2ca550437688c60](runs/D5_f068c2ca550437688c60/result.json) not_reached · cached [D5_7c8fa41b6f65d1c4371f](runs/D5_7c8fa41b6f65d1c4371f/result.json) 4.472 · cached [D5_0a4b7415fd15ed5fd8b0](runs/D5_0a4b7415fd15ed5fd8b0/result.json) 4.236 · cached [D5_3997106a0dde7770492f](runs/D5_3997106a0dde7770492f/result.json) 4.143 |

未命中的有效运行保留右删失标签。加速时间门槛只在双方 3/3 达标时计算。
- 开发判定 acceleration_screen_passed。八组质量保护 True。 目标命中数保护 True。
- 命中增加组数 1。 双方全命中且时间至少缩短 10% 的组数 1。
- 已锁定后端 **cached**。[selection.json](selection.json)，SHA-256 c2b16cf6d9e1499b2a6e0bd3aeac1f81437653d8c8562ad2a0a070309b47c4c3。文件修改时间 2026-11-27T13:57:58.902330+00:00。

## 6. 计算成本诊断

| 阶段／实例／覆盖／邻接／后端 | n | 预处理／引导／转移／重放 s | 展开／生成／终点候选／峰值队列 | 顶点／邻居／边条目 | 顶点／邻居／边命中 | 缓存数组 MiB | 算法 wall／CPU s | 进程 wall s | 采样 RSS MiB | 停止原因 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| D5 / arctic_ocean / axis_square / 4 / cached | 3 | 0.003 / 3.054 / 1.804 / 0.004 | 12952 / 51806 / 18964 / 19892 | 107 / 76 / 304 | 592 / 13180 / 51502 | 3.805 | 5.029 / 5.000 | 6.273 | 210.465 | max_seconds×3 |
| D5 / arctic_ocean / axis_square / 4 / original | 3 | 0.003 / 3.570 / 1.334 / 0.004 | 6720 / 26880 / 7136 / 13024 | unknown / unknown / unknown | unknown / unknown / unknown | unknown | 5.022 / 5.000 | 6.369 | 167.562 | max_seconds×3 |
| D5 / arctic_ocean / axis_square / 8 / cached | 3 | 0.003 / 2.379 / 2.506 / 0.004 | 8938 / 71498 / 48017 / 14548 | 109 / 64 / 512 | 1000 / 9386 / 70986 | 3.558 | 5.020 / 5.000 | 6.376 | 174.652 | max_seconds×3 |
| D5 / arctic_ocean / axis_square / 8 / original | 3 | 0.003 / 3.157 / 1.763 / 0.004 | 4416 / 35323 / 18546 / 12367 | unknown / unknown / unknown | unknown / unknown / unknown | unknown | 5.018 / 5.016 | 6.282 | 159.168 | max_seconds×3 |
| D5 / arctic_ocean / heading_square / 4 / cached | 3 | 0.003 / 2.947 / 1.916 / 0.004 | 12616 / 50463 / 18208 / 19644 | 107 / 76 / 304 | 592 / 12844 / 50159 | 3.805 | 5.030 / 5.031 | 6.376 | 209.207 | max_seconds×3 |
| D5 / arctic_ocean / heading_square / 4 / original | 3 | 0.003 / 3.484 / 1.419 / 0.004 | 6758 / 27031 / 7188 / 13085 | unknown / unknown / unknown | unknown / unknown / unknown | unknown | 5.020 / 5.016 | 6.373 | 167.336 | max_seconds×3 |
| D5 / arctic_ocean / heading_square / 8 / cached | 3 | 0.003 / 3.306 / 1.559 / 0.068 | 4636 / 37082 / 13368 / 19081 | 117 / 70 / 560 | 1091 / 5126 / 36522 | 3.686 | 5.027 / 4.984 | 6.377 | 198.633 | max_seconds×3 |
| D5 / arctic_ocean / heading_square / 8 / original | 3 | 0.003 / 3.905 / 1.037 / 0.004 | 2187 / 17494 / 0 / 15307 | unknown / unknown / unknown | unknown / unknown / unknown | unknown | 5.026 / 5.016 | 6.371 | 176.004 | max_seconds×3 |
| D5 / lake_ontario / axis_square / 4 / cached | 3 | 0.002 / 3.908 / 1.004 / 0.003 | 7057 / 28180 / 3771 / 17353 | 75 / 50 / 197 | 387 / 7204 / 27983 | 0.155 | 5.022 / 5.016 | 6.400 | 184.672 | max_seconds×3 |
| D5 / lake_ontario / axis_square / 4 / original | 3 | 0.002 / 3.702 / 1.215 / 0.003 | 6443 / 25725 / 3302 / 15980 | unknown / unknown / unknown | unknown / unknown / unknown | unknown | 5.026 / 5.000 | 6.274 | 178.871 | max_seconds×3 |
| D5 / lake_ontario / axis_square / 8 / cached | 3 | 0.002 / 4.054 / 0.887 / 0.003 | 2751 / 22002 / 0 / 19251 | 70 / 35 / 280 | 561 / 2996 / 21722 | 0.164 | 5.024 / 4.984 | 6.270 | 190.754 | max_seconds×3 |
| D5 / lake_ontario / axis_square / 8 / original | 3 | 0.002 / 3.857 / 1.080 / 0.003 | 2378 / 19019 / 0 / 16641 | unknown / unknown / unknown | unknown / unknown / unknown | unknown | 5.025 / 5.000 | 6.373 | 179.145 | max_seconds×3 |
| D5 / lake_ontario / heading_square / 4 / cached | 3 | 0.002 / 3.831 / 1.088 / 0.003 | 7218 / 28816 / 4048 / 17550 | 75 / 50 / 197 | 387 / 7365 / 28619 | 0.155 | 5.026 / 5.031 | 6.274 | 186.508 | max_seconds×3 |
| D5 / lake_ontario / heading_square / 4 / original | 3 | 0.002 / 3.631 / 1.283 / 0.004 | 5940 / 23721 / 2667 / 15116 | unknown / unknown / unknown | unknown / unknown / unknown | unknown | 5.022 / 5.000 | 6.288 | 174.969 | max_seconds×3 |
| D5 / lake_ontario / heading_square / 8 / cached | 3 | 0.002 / 1.843 / 3.021 / 0.023 | 10171 / 81154 / 58426 / 12561 | 116 / 79 / 617 | 1205 / 10709 / 80537 | 0.210 | 5.018 / 5.016 | 6.275 | 158.145 | max_seconds×3 |
| D5 / lake_ontario / heading_square / 8 / original | 3 | 0.002 / 1.970 / 2.904 / 0.024 | 6896 / 55035 / 36917 / 11226 | unknown / unknown / unknown | unknown / unknown / unknown | unknown | 5.019 / 4.938 | 6.280 | 152.281 | max_seconds×3 |
| H30 / hudson_window_early / axis_square / 4 / cached | 3 | 0.003 / 25.468 / 4.162 / 0.004 | 28812 / 115246 / 0 / 86434 | 79 / 50 / 200 | 401 / 28962 / 115046 | 3.337 | 30.134 / 30.047 | 31.603 | 586.352 | max_seconds×3 |
| H30 / hudson_window_early / axis_square / 8 / cached | 3 | 0.003 / 19.821 / 9.701 / 0.040 | 34198 / 273581 / 161424 / 77961 | 192 / 129 / 1032 | 2011 / 35101 / 272549 | 5.851 | 30.124 / 30.016 | 31.614 | 535.309 | max_seconds×3 |
| H30 / hudson_window_early / heading_square / 4 / cached | 3 | 0.003 / 25.065 / 4.574 / 0.004 | 28133 / 112532 / 0 / 84399 | 79 / 50 / 200 | 401 / 28283 / 112332 | 3.337 | 30.136 / 30.062 | 31.601 | 575.121 | max_seconds×3 |
| H30 / hudson_window_early / heading_square / 8 / cached | 3 | 0.003 / 7.034 / 22.054 / 0.098 | 73734 / 589869 / 456240 / 59905 | 157 / 103 / 824 | 1607 / 74455 / 589045 | 4.875 | 30.102 / 30.062 | 31.697 | 457.270 | max_seconds×3 |
| H30 / hudson_window_late / axis_square / 4 / cached | 3 | 0.003 / 5.407 / 23.073 / 0.004 | 172310 / 689238 / 464080 / 52839 | 122 / 89 / 356 | 692 / 172577 / 688882 | 4.270 | 30.100 / 30.016 | 31.606 | 425.461 | max_seconds×3 |
| H30 / hudson_window_late / axis_square / 8 / cached | 3 | 0.003 / 3.153 / 25.781 / 0.037 | 94287 / 754296 / 613783 / 46227 | 149 / 95 / 760 | 1476 / 94952 / 753536 | 4.409 | 30.088 / 30.047 | 31.604 | 382.047 | max_seconds×3 |
| H30 / hudson_window_late / heading_square / 4 / cached | 3 | 0.003 / 5.118 / 23.507 / 0.004 | 161127 / 644506 / 433769 / 49603 | 119 / 87 / 348 | 679 / 161388 / 644158 | 4.270 | 30.091 / 29.891 | 31.506 | 406.953 | max_seconds×3 |
| H30 / hudson_window_late / heading_square / 8 / cached | 3 | 0.003 / 6.460 / 22.635 / 0.016 | 73271 / 586163 / 438542 / 74358 | 161 / 107 / 856 | 1670 / 74020 / 585307 | 5.003 | 30.141 / 30.016 | 31.610 | 553.098 | max_seconds×3 |
| H30 / lake_window_early / axis_square / 4 / cached | 3 | 0.002 / 6.322 / 22.333 / 0.019 | 169208 / 670003 / 451425 / 49373 | 110 / 92 / 352 | 691 / 169468 / 669651 | 0.224 | 30.089 / 29.875 | 31.502 | 386.082 | max_seconds×3 |
| H30 / lake_window_early / axis_square / 8 / cached | 3 | 0.002 / 2.967 / 25.968 / 0.025 | 95562 / 760338 / 610829 / 53947 | 111 / 82 / 617 | 1217 / 96097 / 759721 | 0.226 | 30.095 / 30.047 | 31.609 | 412.789 | max_seconds×3 |
| H30 / lake_window_early / heading_square / 4 / cached | 3 | 0.002 / 5.905 / 22.796 / 0.019 | 154887 / 613220 / 413759 / 44575 | 110 / 91 / 348 | 683 / 155144 / 612872 | 0.224 | 30.079 / 29.859 | 31.597 | 358.320 | max_seconds×3 |
| H30 / lake_window_early / heading_square / 8 / cached | 3 | 0.002 / 2.376 / 26.633 / 0.050 | 94065 / 736676 / 617122 / 25499 | 126 / 92 / 706 | 1385 / 94679 / 735970 | 0.240 | 30.042 / 29.984 | 31.504 | 242.594 | max_seconds×3 |
| H30 / lake_window_late / axis_square / 4 / cached | 3 | 0.002 / 3.671 / 24.865 / 0.037 | 189218 / 755463 / 536595 / 29669 | 122 / 98 / 384 | 751 / 189504 / 755079 | 0.243 | 30.049 / 29.891 | 31.511 | 269.137 | max_seconds×3 |
| H30 / lake_window_late / axis_square / 8 / cached | 3 | 0.002 / 3.121 / 25.816 / 0.116 | 95707 / 762707 / 644617 / 22390 | 139 / 109 / 824 | 1619 / 96422 / 761883 | 0.268 | 30.035 / 29.812 | 31.602 | 220.586 | max_seconds×3 |
| H30 / lake_window_late / heading_square / 4 / cached | 3 | 0.002 / 3.471 / 25.105 / 0.040 | 168098 / 671205 / 475184 / 27926 | 120 / 96 / 376 | 734 / 168378 / 670829 | 0.236 | 30.046 / 29.891 | 31.502 | 258.828 | max_seconds×3 |
| H30 / lake_window_late / heading_square / 8 / cached | 3 | 0.002 / 3.244 / 25.771 / 0.046 | 84867 / 677900 / 550713 / 42323 | 126 / 95 / 721 | 1415 / 85493 / 677179 | 0.240 | 30.074 / 29.906 | 31.606 | 342.523 | max_seconds×3 |

成本为组中位数。缓存布局及构建计入时限，数组字节和采样 RSS 分别度量保留数组及进程采样。提前达到 max_open 和耗尽算时的运行可能完成不同工作量。

## 7. H1 输入来源与准备

四例使用同一地区原有历史 forcing，时间窗和 seed 同时变化。固定层级为 same_forcing_shifted_window_new_seed。

| 实例 | LKP／CST／结束 UTC | seed | forcing SHA-256／覆盖 | 原生积分末时 | 档案及元数据哈希 | ID／帧／格号 | 质量及生成耗时 | 状态及证据 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| lake_window_early | 2025-08-26T13:45:00Z / 2025-08-26T14:45:00Z / 2025-08-26T14:52:33.740Z | 1041 | wind d23da8d2684adeb56f7b205d84135aecce0a7fbacbe50d94eca933831a524419；wind e93eb9ebf9995368d535885e97c8442e50630b25e247e6efb938bb02b3ec06e4；wind 644b9d28c24f01aeebc7fb75bcb7cb1468aece6068de5d4c37667e63d424130c；wind 46256f2a7357568baa37e1193120521f3cda5706549e69023d5f274621108654；wind 71beb93fd7c77e25ce6f3a1d75d10198e703b7b436640c0909cf0d51c61cf447；current 7269134c0240c7f00eeca6e9e6bc39dc40ae49032004f8561c239510fcd7090f；current 5092a254127774814da296dcc0edb302ca3320c5a8e2bd6f951d09ea25e75484；current ec3918e3251852e1646373b0aaa3e29f75232333879dfabcf37a547a3ffef4f3；current e16e82ce3149104f6f8d8e2d7ece55de11d1c7a7b1f36c2a9fd20b4714bac8c4；current aa575cf91f8ecb84e003389204cae11846fc9a22ac754b2817a4ccb367ee0682；['2025-08-26T13:00:00+00:00', '2025-08-26T17:00:00+00:00'] | 2025-08-26T14:53:00Z | 粒子 6e87f32c4877d6f91355dcb30169684ac19d52ecef12f7c1d1341ca9bd93f56a；元数据 f4d7054cb01b60c7fd73c3989cb5feeddbc5c8424e4b8200164e87626b060fa3；manifest 5c4e76117f9fbe345204f6d1d9fb2f71f2ca6f09fb192b685e2d64c36f10a487 | 稳定 ID True；数组 [50, 500]；格号 matched | 最大误差 0.000000000000；inactive 峰值 0.000000000 / land 峰值 0.000000000 / outside 峰值 0.000000000 / unknown 峰值 0.000000000；生成 9.345 s | verified  [manifest.json](inputs/lake_window_early/manifest.json) · [forcing_validation.json](inputs/lake_window_early/forcing_validation.json) · [prepare.log](inputs/lake_window_early/prepare.log) |
| lake_window_late | 2025-08-26T15:45:00Z / 2025-08-26T16:45:00Z / 2025-08-26T16:52:33.740Z | 1042 | wind d23da8d2684adeb56f7b205d84135aecce0a7fbacbe50d94eca933831a524419；wind e93eb9ebf9995368d535885e97c8442e50630b25e247e6efb938bb02b3ec06e4；wind 644b9d28c24f01aeebc7fb75bcb7cb1468aece6068de5d4c37667e63d424130c；wind 46256f2a7357568baa37e1193120521f3cda5706549e69023d5f274621108654；wind 71beb93fd7c77e25ce6f3a1d75d10198e703b7b436640c0909cf0d51c61cf447；current 7269134c0240c7f00eeca6e9e6bc39dc40ae49032004f8561c239510fcd7090f；current 5092a254127774814da296dcc0edb302ca3320c5a8e2bd6f951d09ea25e75484；current ec3918e3251852e1646373b0aaa3e29f75232333879dfabcf37a547a3ffef4f3；current e16e82ce3149104f6f8d8e2d7ece55de11d1c7a7b1f36c2a9fd20b4714bac8c4；current aa575cf91f8ecb84e003389204cae11846fc9a22ac754b2817a4ccb367ee0682；['2025-08-26T13:00:00+00:00', '2025-08-26T17:00:00+00:00'] | 2025-08-26T16:53:00Z | 粒子 9b7aee3e1bd04066435b80229b6a7488ac89b8638dfb7bf8b404951997086863；元数据 ebaa82778ec00ed722da16c7cee1adc6923679133043f90ad7f538665af1ead7；manifest 9e52a4f474aa0b6b9b77d81a0c22eaf9d9331dedfe5eff38d1969e983bb6447e | 稳定 ID True；数组 [50, 500]；格号 matched | 最大误差 0.000000000000；inactive 峰值 0.000000000 / land 峰值 0.000000000 / outside 峰值 0.000000000 / unknown 峰值 0.000000000；生成 2.528 s | verified  [manifest.json](inputs/lake_window_late/manifest.json) · [forcing_validation.json](inputs/lake_window_late/forcing_validation.json) · [prepare.log](inputs/lake_window_late/prepare.log) |
| hudson_window_early | 2025-08-28T22:00:00Z / 2025-08-29T22:00:00Z / 2025-08-29T22:46:18Z | 2041 | wind a91838d9f73b5e4752302bbdff48b9c9c360951bfa8519152deca6c27091327b；wind 239e8e88c98111c56635e7d4138cbb09a87ca8c824c3ff83ee24cba5dc24414f；wind b3a133eff053796c6233f1df0c5a80338f1582d1106189a0f4dbedc39bffbfe4；wind 28d442ecd22295a816f7f4c3d3a6d34f8198004c5287d717407e468ef2b61866；wind 2347f4714d124e4280ae637aedbeb2bd1021102fd79540daf757b501540ec7a0；wind 8287bccb3f56970926881678ebe62630f4bf2534e7e3a371f9a24b59ad71314e；wind b0249b33322313679480f2aa64e0b0a4d798e2c4eacd8446bab6284504a54be3；wind f0edfe056772055be127c99bfee1032a75048b087d5b4dcb76b33d72631f4664；wind 8efac42b7ecdc199407ba147120e9582c857bd38634e60ea284b09026fc6a774；wind 08919407eeddf932320ca12d77d18df70a3061c38e666f3a070f609fdf41a0d4；wind 94ae1a92c6f5366bf2ddc040007ccf9663b82dfdeaac43f3973ed3cdcf0c0708；current c6abc95e224d20d0823b1171e831dc92fed4c9f7b95eca3aa8fbf0544c6afcaa；current 764ba5e77d97a25836d386d351131353e0c76f587054d99370417a2a68113e31；current a9925344bb3f2eaa4a24342adec50da9df3fb50cae6d5eff6dcf9a0305ea0016；['2025-08-28T21:00:00+00:00', '2025-08-30T03:00:00+00:00'] | 2025-08-29T22:48:00Z | 粒子 88977d665a2e64faee8db264ad7c24cfa4d2421c8adff582b8f63bd3441ae7ff；元数据 bddfb3d428274c3cbbafd84352589ebff28ab9f73c5dc572a58018b9b87dc3ee；manifest b759eaf71f59005e1eb0c6817132b57ca9d7df2dd3bbeb6c0306e10e216ad353 | 稳定 ID True；数组 [61, 500]；格号 matched | 最大误差 0.000000000000；inactive 峰值 0.000000000 / land 峰值 0.000000000 / outside 峰值 0.000000000 / unknown 峰值 0.000000000；生成 8.273 s | verified  [manifest.json](inputs/hudson_window_early/manifest.json) · [forcing_validation.json](inputs/hudson_window_early/forcing_validation.json) · [prepare.log](inputs/hudson_window_early/prepare.log) |
| hudson_window_late | 2025-08-29T02:00:00Z / 2025-08-30T02:00:00Z / 2025-08-30T02:46:18Z | 2042 | wind a91838d9f73b5e4752302bbdff48b9c9c360951bfa8519152deca6c27091327b；wind 239e8e88c98111c56635e7d4138cbb09a87ca8c824c3ff83ee24cba5dc24414f；wind b3a133eff053796c6233f1df0c5a80338f1582d1106189a0f4dbedc39bffbfe4；wind 28d442ecd22295a816f7f4c3d3a6d34f8198004c5287d717407e468ef2b61866；wind 2347f4714d124e4280ae637aedbeb2bd1021102fd79540daf757b501540ec7a0；wind 8287bccb3f56970926881678ebe62630f4bf2534e7e3a371f9a24b59ad71314e；wind b0249b33322313679480f2aa64e0b0a4d798e2c4eacd8446bab6284504a54be3；wind f0edfe056772055be127c99bfee1032a75048b087d5b4dcb76b33d72631f4664；wind 8efac42b7ecdc199407ba147120e9582c857bd38634e60ea284b09026fc6a774；wind 08919407eeddf932320ca12d77d18df70a3061c38e666f3a070f609fdf41a0d4；wind 94ae1a92c6f5366bf2ddc040007ccf9663b82dfdeaac43f3973ed3cdcf0c0708；current c6abc95e224d20d0823b1171e831dc92fed4c9f7b95eca3aa8fbf0544c6afcaa；current 764ba5e77d97a25836d386d351131353e0c76f587054d99370417a2a68113e31；current a9925344bb3f2eaa4a24342adec50da9df3fb50cae6d5eff6dcf9a0305ea0016；['2025-08-28T21:00:00+00:00', '2025-08-30T03:00:00+00:00'] | 2025-08-30T02:48:00Z | 粒子 264dedc98fc499be4d35022e23d88e1903bb84d303a2b93b9b96bbf628f3acee；元数据 7378af9b370e7ad743ae0144da77b6c6340e657474adbb32097c25d28c4f8a97；manifest 4951962432ce7d9f8d7229d73285bab8878ef1ae5e6542edf080585daac7a7de | 稳定 ID True；数组 [61, 500]；格号 matched | 最大误差 0.000000000000；inactive 峰值 0.000000000 / land 峰值 0.000000000 / outside 峰值 0.000000000 / unknown 峰值 0.000000000；生成 8.549 s | verified  [manifest.json](inputs/hudson_window_late/manifest.json) · [forcing_validation.json](inputs/hudson_window_late/forcing_validation.json) · [prepare.log](inputs/hudson_window_late/prepare.log) |

- lake_window_early 使用 OpenDrift 1.14.12；reader 优先级 {'x_sea_water_velocity': ['asar_current'], 'x_wind': ['asar_wind'], 'y_sea_water_velocity': ['asar_current'], 'y_wind': ['asar_wind']}；reader 实现 SHA-256 7d7e936ad12de6eb6b7f0bb27a04bb26fa1910cb37949ff03b3f8ed27694535d；积分 7.441 s。 [实际模型及 reader](inputs/lake_window_early/metadata.json) · [逐帧质量账本](inputs/lake_window_early/mass_audit.json)。
- lake_window_late 使用 OpenDrift 1.14.12；reader 优先级 {'x_sea_water_velocity': ['asar_current'], 'x_wind': ['asar_wind'], 'y_sea_water_velocity': ['asar_current'], 'y_wind': ['asar_wind']}；reader 实现 SHA-256 7d7e936ad12de6eb6b7f0bb27a04bb26fa1910cb37949ff03b3f8ed27694535d；积分 0.752 s。 [实际模型及 reader](inputs/lake_window_late/metadata.json) · [逐帧质量账本](inputs/lake_window_late/mass_audit.json)。
- hudson_window_early 使用 OpenDrift 1.14.12；reader 优先级 {'x_sea_water_velocity': ['asar_current'], 'x_wind': ['asar_wind'], 'y_sea_water_velocity': ['asar_current'], 'y_wind': ['asar_wind']}；reader 实现 SHA-256 7d7e936ad12de6eb6b7f0bb27a04bb26fa1910cb37949ff03b3f8ed27694535d；积分 3.156 s。 [实际模型及 reader](inputs/hudson_window_early/metadata.json) · [逐帧质量账本](inputs/hudson_window_early/mass_audit.json)。
- hudson_window_late 使用 OpenDrift 1.14.12；reader 优先级 {'x_sea_water_velocity': ['asar_current'], 'x_wind': ['asar_wind'], 'y_sea_water_velocity': ['asar_current'], 'y_wind': ['asar_wind']}；reader 实现 SHA-256 7d7e936ad12de6eb6b7f0bb27a04bb26fa1910cb37949ff03b3f8ed27694535d；积分 3.341 s。 [实际模型及 reader](inputs/hudson_window_late/metadata.json) · [逐帧质量账本](inputs/hudson_window_late/mass_audit.json)。

- 四例输入清单绑定 selection SHA-256，并校验清单内全部文件。 [prepared_inputs.json](prepared_inputs.json)。
- 以本地锁文件修改时间对照四份 request.json，均在锁定后开始 True。

四个实例的实际气象覆盖、读入探针、质量守恒与轨迹元数据见各输入目录。

## 8. S30 共同初始化

| 实例 | PT／paper 接纳与迟到 | 预算／算法／进程 s | 离散 J／Pd | axis J／Pd | heading J／Pd | 共同路线对象 SHA-256 | 桥接／合法性／证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| lake_window_early | parallel_track 0.005 s，20.005234720 / 0.890134128；original_paper_greedy 0.167 s，17.155386959 / 0.909383817；迟到 0；None | 30 / 0.167 / 1.633 | 17.155386959 / 0.909383817 | 17.155386959 / 0.909383817 | 17.155386959 / 0.909383817 | 3299b87b604a3c374ef0f5ae851b44e818cd107686769d692a5bdc229710ed3e | 通过桥接和物理重放；路线与 H30 冻结一致；[S30_adfb9e5ea653eede24ca](runs/S30_adfb9e5ea653eede24ca/result.json) |
| lake_window_late | parallel_track 0.005 s，21.238809088 / 0.847987920；original_paper_greedy 0.152 s，17.406323592 / 0.902986082；迟到 0；None | 30 / 0.152 / 1.530 | 17.406323592 / 0.902986082 | 17.406323592 / 0.902986082 | 17.406323592 / 0.902986082 | 097ccb03d909bca1d8f8569101d8fb613f3d470915960653b5822d4a64d0ce9a | 通过桥接和物理重放；路线与 H30 冻结一致；[S30_1f833e286403d018a850](runs/S30_1f833e286403d018a850/result.json) |
| hudson_window_early | parallel_track 0.006 s，26.344691040 / 0.824859360；迟到 0；max_seconds | 30 / 29.871 / 31.401 | 26.344691040 / 0.824859360 | 26.344691040 / 0.824859360 | 26.344691040 / 0.824859360 | 2ce2b2ef9752d859c4c1b2dcfe65041c988e6b73f457c93ddf6fcf2c52fb37a1 | 通过桥接和物理重放；路线与 H30 冻结一致；[S30_a0424591fd5b4ae1b790](runs/S30_a0424591fd5b4ae1b790/result.json) |
| hudson_window_late | parallel_track 0.007 s，26.326128288 / 0.895161696；original_paper_greedy 1.240 s，20.337375787 / 0.917093438；迟到 0；None | 30 / 1.240 / 2.810 | 20.337375787 / 0.917093438 | 20.337375787 / 0.917093438 | 20.337375787 / 0.917093438 | 43a75f41c524093253b5d4d29f073bf4928ea90b9fa7ecae44da708234a29c6a | 通过桥接和物理重放；路线与 H30 冻结一致；[S30_505e73e474c305ac91d3](runs/S30_505e73e474c305ac91d3/result.json) |

S30 的共同路线成本单列。H30 时钟包含同一路线复制和评分。原始记录保留各次被接纳的候选桥接分数和迟到候选。

## 9. H30 逐实例质量与航迹

| 实例 | 覆盖 | J4 中位数 [范围] | J8 中位数 [范围] | G | Pd4／Pd8 中位数 | 有效数 4／8 | 判定 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| lake_window_early | heading_square | 17.151955583 [17.151955583, 17.151955583] | 16.744214940 [16.744214940, 16.744214940] | 2.3772% | 0.909765081 / 0.917916211 | 3/3 · 3/3 | 组完整 |
| lake_window_early | axis_square | 17.151955583 [17.151955583, 17.151955583] | 16.703731421 [16.703731421, 16.703731421] | 2.6133% | 0.909765081 / 0.914320706 | 3/3 · 3/3 | 组完整 |
| lake_window_late | heading_square | 17.276096664 [17.276096664, 17.276096664] | 16.871848574 [16.871848574, 16.871848574] | 2.3399% | 0.906255942 / 0.897995258 | 3/3 · 3/3 | 组完整 |
| lake_window_late | axis_square | 17.276096664 [17.276096664, 17.276096664] | 17.176060142 [17.176060142, 17.176060142] | 0.5790% | 0.906255942 / 0.900488532 | 3/3 · 3/3 | 组完整 |
| hudson_window_early | heading_square | 26.344691040 [26.344691040, 26.344691040] | 22.790164159 [22.790164159, 22.790164159] | 13.4924% | 0.824859360 / 0.895362734 | 3/3 · 3/3 | 组完整 |
| hudson_window_early | axis_square | 26.344691040 [26.344691040, 26.344691040] | 22.840425949 [22.840425949, 22.840425949] | 13.3016% | 0.824859360 / 0.887116976 | 3/3 · 3/3 | 组完整 |
| hudson_window_late | heading_square | 20.337375787 [20.337375787, 20.337375787] | 19.815790368 [19.815790368, 19.815790368] | 2.5647% | 0.917093438 / 0.921818146 | 3/3 · 3/3 | 组完整 |
| hudson_window_late | axis_square | 20.337375787 [20.337375787, 20.337375787] | 19.941886265 [19.941886265, 19.941886265] | 1.9446% | 0.917093438 / 0.922347745 | 3/3 · 3/3 | 组完整 |

以下区段对照取每组中位 J 对应的具体路线。Pd 与 J 来自同一运行。按固定观测时钟的三等分累计 4 邻剩余质量减 8 邻剩余质量，正值表示该段 8 邻剩余质量更低。

| 实例／覆盖 | 4 邻／8 邻原始路线及各自 J／Pd | 前／中／后段对 ΔJ | 首次较低剩余质量 tick | 8 邻对角航程占比 | 轨迹感测次数／重访次数 4 → 8 |
| --- | --- | --- | --- | --- | --- |
| lake_window_early / heading_square | [H30_e8a989b3d685aba19ce3](runs/H30_e8a989b3d685aba19ce3/result.json) 17.151955583 / 0.909765081 · [H30_d61cfd19348d4b766260](runs/H30_d61cfd19348d4b766260/result.json) 16.744214940 / 0.917916211 | 0.264381936 / 0.049230755 / 0.094127952 | 2 | 34.6939% | 1080 / 595 → 1212 / 730 |
| lake_window_early / axis_square | [H30_b6ee15c8bafb918b6221](runs/H30_b6ee15c8bafb918b6221/result.json) 17.151955583 / 0.909765081 · [H30_4da6795f337ffed604b9](runs/H30_4da6795f337ffed604b9/result.json) 16.703731421 / 0.914320706 | 0.273225264 / 0.075297007 / 0.099701891 | 2 | 40.4061% | 1080 / 595 → 1220 / 740 |
| lake_window_late / heading_square | [H30_faf195d7a2f7985206c6](runs/H30_faf195d7a2f7985206c6/result.json) 17.276096664 / 0.906255942 · [H30_18cabf243b8c0853c63a](runs/H30_18cabf243b8c0853c63a/result.json) 16.871848574 / 0.897995258 | 0.493162176 / 0.039405251 / -0.128319337 | 2 | 40.4061% | 1113 / 631 → 1168 / 691 |
| lake_window_late / axis_square | [H30_b244911bf987206c64bc](runs/H30_b244911bf987206c64bc/result.json) 17.276096664 / 0.906255942 · [H30_fec1b2d4c1f7bd27a23d](runs/H30_fec1b2d4c1f7bd27a23d/result.json) 17.176060142 / 0.900488532 | 0.288415296 / -0.098053201 / -0.090325573 | 2 | 31.7477% | 1113 / 631 → 1098 / 617 |
| hudson_window_early / heading_square | [H30_f49fbbfcaf4fae2d083d](runs/H30_f49fbbfcaf4fae2d083d/result.json) 26.344691040 / 0.824859360 · [H30_ce3d6d742f1069c32938](runs/H30_ce3d6d742f1069c32938/result.json) 22.790164159 / 0.895362734 | 0.690674550 / 1.058837179 / 1.805015153 | 2 | 33.3333% | 825 / 371 → 1080 / 601 |
| hudson_window_early / axis_square | [H30_227a952a58d3b8053497](runs/H30_227a952a58d3b8053497/result.json) 26.344691040 / 0.824859360 · [H30_52206899884df27cb12d](runs/H30_52206899884df27cb12d/result.json) 22.840425949 / 0.887116976 | 0.523660800 / 1.197148231 / 1.783456060 | 3 | 36.6667% | 825 / 371 → 1009 / 531 |
| hudson_window_late / heading_square | [H30_b02a228c5947f8eaf53f](runs/H30_b02a228c5947f8eaf53f/result.json) 20.337375787 / 0.917093438 · [H30_043b43b2df0d26b48e51](runs/H30_043b43b2df0d26b48e51/result.json) 19.815790368 / 0.921818146 | 0.410809926 / 0.070601419 / 0.040174075 | 2 | 44.7834% | 1265 / 784 → 1187 / 700 |
| hudson_window_late / axis_square | [H30_981050adec7fbd650047](runs/H30_981050adec7fbd650047/result.json) 20.337375787 / 0.917093438 · [H30_44e04f7a9df369185fb7](runs/H30_44e04f7a9df369185fb7/result.json) 19.941886265 / 0.922347745 | 0.385832304 / -0.029726763 / 0.039383981 | 2 | 40.0000% | 1265 / 784 → 1238 / 752 |

同一粒子 ID 的多次感测视为重访。重访数和剩余质量时间结构描述轨迹差异，不能单独归因于对角航段。

## 10. H1 预声明判定

- 主覆盖全体不退化 True。
- 主覆盖改善至少 0.5% 的实例 lake_window_early, lake_window_late, hudson_window_early, hudson_window_late。达到至少两例 True。
- 主赢家中至少一例 axis 正改善 True。 全部 axis 退化至多 0.5% True。
- 主赢家按地区 {'lake_ontario': 2, 'arctic_ocean': 2}。主检验 True，替代覆盖敏感性 True。
- 有限迁移判定 **within_forcing_transfer_signal**。

## 11. 结论与范围

- 执行状态 **complete**。严格共同前缀审计 True。开发判定 acceleration_screen_passed。 有限迁移判定 within_forcing_transfer_signal。
- D5 八组 J 中位数均通过质量保护。Lake 主覆盖的目标时间中位数从 2.552 秒降至 2.120 秒。Hudson 主覆盖的目标命中从 0/3 升至 3/3。Lake 轴对齐目标两后端均未命中。按预先门槛锁定缓存后端。
- H30 的八邻接路线在四例主覆盖下均降低 J，改善幅度为 2.34% 至 13.49%。四例轴对齐覆盖的 J 也均改善。Lake 晚窗在主覆盖下提前降低剩余质量，前段贡献约 +0.493 的 J 差，超过末段约 −0.128 的反向贡献。其终点 Pd 下降 0.83 个百分点，轴对齐覆盖也下降 0.58 个百分点。
- Hudson 早窗的四邻接中位路线保持共同初始路线。八邻接代表路线三个时段都降低累计剩余质量，主覆盖改善主要来自后段，终点 Pd 提高 7.05 个百分点。这些是同预算下的路线差异，因果归因需要额外对照。
- 48 次 H30 搜索均因 30 秒预算停止。最长算法返回多用约 0.146 秒，正式成绩只采纳在预算内完成评分的候选，并随后独立重放核验。H30 采样峰值 RSS 为 219.68–591.74 MiB。全部 100 个正式任务通过复核；没有监控强制终止或最优性认证。
- 结果限于真实历史 forcing 内平移的两地区、几何覆盖代理与有限运行预算。H2 与长预算未启用，未进行独立天气比较或真实飞行验证。Fundy 保留物理方向未验证标签，未参与本批。
- 协议处置。按两地区内的迁移信号结束本批。跨天气检验须另行注册新 forcing 的 H2。

冻结证据 [selection.json](selection.json) · [prepared_inputs.json](prepared_inputs.json) · [holdout_protocol.json](holdout_protocol.json)。

### 逐次 J、Pd 与执行证据

| 阶段／实例／覆盖／邻接／后端／重复 | 初始 J | 最终 J／Pd | 改进用时／算法用时 s | 停止原因 | 原始记录 |
| --- | --- | --- | --- | --- | --- |
| D5 / lake_ontario / axis_square / 4 / original / 2 | 17.264874448 | 17.264874448 / 0.897364416 | 0.024 / 5.021 | max_seconds | [D5_f67e521ebf93dd6440e0](runs/D5_f67e521ebf93dd6440e0/result.json) · [D5_f67e521ebf93dd6440e0](runs/D5_f67e521ebf93dd6440e0/record.json) |
| D5 / lake_ontario / axis_square / 4 / cached / 0 | 17.264874448 | 17.264874448 / 0.897364416 | 0.026 / 5.022 | max_seconds | [D5_fd0de97ac098b979ff01](runs/D5_fd0de97ac098b979ff01/result.json) · [D5_fd0de97ac098b979ff01](runs/D5_fd0de97ac098b979ff01/record.json) |
| D5 / lake_ontario / heading_square / 8 / original / 1 | 17.264874448 | 16.752262696 / 0.904678365 | 2.499 / 5.019 | max_seconds | [D5_eb0962e2db252b46f6c9](runs/D5_eb0962e2db252b46f6c9/result.json) · [D5_eb0962e2db252b46f6c9](runs/D5_eb0962e2db252b46f6c9/record.json) |
| D5 / arctic_ocean / axis_square / 4 / cached / 0 | 20.386109349 | 20.386109349 / 0.908583112 | 0.031 / 5.027 | max_seconds | [D5_c692ff67e61c7fbb7a97](runs/D5_c692ff67e61c7fbb7a97/result.json) · [D5_c692ff67e61c7fbb7a97](runs/D5_c692ff67e61c7fbb7a97/record.json) |
| D5 / arctic_ocean / axis_square / 4 / cached / 1 | 20.386109349 | 20.386109349 / 0.908583112 | 0.033 / 5.029 | max_seconds | [D5_7210f1680b91c42860ea](runs/D5_7210f1680b91c42860ea/result.json) · [D5_7210f1680b91c42860ea](runs/D5_7210f1680b91c42860ea/record.json) |
| D5 / arctic_ocean / heading_square / 4 / cached / 2 | 20.386109349 | 20.386109349 / 0.908583112 | 0.039 / 5.035 | max_seconds | [D5_fd31dffe883a7b7ecd8e](runs/D5_fd31dffe883a7b7ecd8e/result.json) · [D5_fd31dffe883a7b7ecd8e](runs/D5_fd31dffe883a7b7ecd8e/record.json) |
| D5 / lake_ontario / heading_square / 8 / original / 0 | 17.264874448 | 16.752262696 / 0.904678365 | 2.707 / 5.021 | max_seconds | [D5_787aca509575bc0f59f4](runs/D5_787aca509575bc0f59f4/result.json) · [D5_787aca509575bc0f59f4](runs/D5_787aca509575bc0f59f4/record.json) |
| D5 / arctic_ocean / axis_square / 4 / original / 0 | 20.386109349 | 20.386109349 / 0.908583112 | 0.023 / 5.019 | max_seconds | [D5_d8ddeb6cd09883806454](runs/D5_d8ddeb6cd09883806454/result.json) · [D5_d8ddeb6cd09883806454](runs/D5_d8ddeb6cd09883806454/record.json) |
| D5 / arctic_ocean / axis_square / 8 / original / 0 | 20.386109349 | 20.386109349 / 0.908583112 | 0.022 / 5.018 | max_seconds | [D5_3b733407bcbea89f68c7](runs/D5_3b733407bcbea89f68c7/result.json) · [D5_3b733407bcbea89f68c7](runs/D5_3b733407bcbea89f68c7/record.json) |
| D5 / lake_ontario / heading_square / 8 / cached / 1 | 17.264874448 | 16.752262696 / 0.904678365 | 2.120 / 5.018 | max_seconds | [D5_638ee529dd0dbb43df88](runs/D5_638ee529dd0dbb43df88/result.json) · [D5_638ee529dd0dbb43df88](runs/D5_638ee529dd0dbb43df88/record.json) |
| D5 / lake_ontario / axis_square / 8 / cached / 2 | 17.264874448 | 17.264874448 / 0.897364416 | 0.028 / 5.024 | max_seconds | [D5_641729ff3d0bcbe692f9](runs/D5_641729ff3d0bcbe692f9/result.json) · [D5_641729ff3d0bcbe692f9](runs/D5_641729ff3d0bcbe692f9/record.json) |
| D5 / arctic_ocean / heading_square / 4 / original / 2 | 20.386109349 | 20.386109349 / 0.908583112 | 0.030 / 5.026 | max_seconds | [D5_3fcf34ccfd6dff672827](runs/D5_3fcf34ccfd6dff672827/result.json) · [D5_3fcf34ccfd6dff672827](runs/D5_3fcf34ccfd6dff672827/record.json) |
| D5 / arctic_ocean / axis_square / 8 / original / 2 | 20.386109349 | 20.386109349 / 0.908583112 | 0.020 / 5.017 | max_seconds | [D5_cd85966de274efa36b11](runs/D5_cd85966de274efa36b11/result.json) · [D5_cd85966de274efa36b11](runs/D5_cd85966de274efa36b11/record.json) |
| D5 / arctic_ocean / heading_square / 8 / original / 0 | 20.386109349 | 20.386109349 / 0.908583112 | 0.028 / 5.023 | max_seconds | [D5_82443a2e08a1326e873d](runs/D5_82443a2e08a1326e873d/result.json) · [D5_82443a2e08a1326e873d](runs/D5_82443a2e08a1326e873d/record.json) |
| D5 / lake_ontario / heading_square / 4 / original / 0 | 17.264874448 | 17.264874448 / 0.897364416 | 0.026 / 5.022 | max_seconds | [D5_5f387d5b61b75137911b](runs/D5_5f387d5b61b75137911b/result.json) · [D5_5f387d5b61b75137911b](runs/D5_5f387d5b61b75137911b/record.json) |
| D5 / arctic_ocean / heading_square / 8 / original / 1 | 20.386109349 | 20.386109349 / 0.908583112 | 0.032 / 5.028 | max_seconds | [D5_3b13f956ec87d5a99e9a](runs/D5_3b13f956ec87d5a99e9a/result.json) · [D5_3b13f956ec87d5a99e9a](runs/D5_3b13f956ec87d5a99e9a/record.json) |
| D5 / lake_ontario / axis_square / 4 / cached / 1 | 17.264874448 | 17.264874448 / 0.897364416 | 0.026 / 5.022 | max_seconds | [D5_a76c2492fb2f4fbf0294](runs/D5_a76c2492fb2f4fbf0294/result.json) · [D5_a76c2492fb2f4fbf0294](runs/D5_a76c2492fb2f4fbf0294/record.json) |
| D5 / lake_ontario / heading_square / 8 / cached / 2 | 17.264874448 | 16.752262696 / 0.904678365 | 2.117 / 5.017 | max_seconds | [D5_5ba40f3c6c7fa81ec4cd](runs/D5_5ba40f3c6c7fa81ec4cd/result.json) · [D5_5ba40f3c6c7fa81ec4cd](runs/D5_5ba40f3c6c7fa81ec4cd/record.json) |
| D5 / lake_ontario / axis_square / 8 / original / 2 | 17.264874448 | 17.264874448 / 0.897364416 | 0.029 / 5.025 | max_seconds | [D5_9cea31c9436a4f3ec74b](runs/D5_9cea31c9436a4f3ec74b/result.json) · [D5_9cea31c9436a4f3ec74b](runs/D5_9cea31c9436a4f3ec74b/record.json) |
| D5 / arctic_ocean / axis_square / 8 / cached / 2 | 20.386109349 | 20.386109349 / 0.908583112 | 0.024 / 5.020 | max_seconds | [D5_fd79cc9c4f8bdf261133](runs/D5_fd79cc9c4f8bdf261133/result.json) · [D5_fd79cc9c4f8bdf261133](runs/D5_fd79cc9c4f8bdf261133/record.json) |
| D5 / arctic_ocean / heading_square / 8 / original / 2 | 20.386109349 | 20.386109349 / 0.908583112 | 0.030 / 5.026 | max_seconds | [D5_f068c2ca550437688c60](runs/D5_f068c2ca550437688c60/result.json) · [D5_f068c2ca550437688c60](runs/D5_f068c2ca550437688c60/record.json) |
| D5 / lake_ontario / heading_square / 8 / original / 2 | 17.264874448 | 16.752262696 / 0.904678365 | 2.552 / 5.017 | max_seconds | [D5_bce9a3b2a09767c62d86](runs/D5_bce9a3b2a09767c62d86/result.json) · [D5_bce9a3b2a09767c62d86](runs/D5_bce9a3b2a09767c62d86/record.json) |
| D5 / arctic_ocean / axis_square / 8 / cached / 0 | 20.386109349 | 20.386109349 / 0.908583112 | 0.028 / 5.024 | max_seconds | [D5_8cb332ee8e6e52de970a](runs/D5_8cb332ee8e6e52de970a/result.json) · [D5_8cb332ee8e6e52de970a](runs/D5_8cb332ee8e6e52de970a/record.json) |
| D5 / lake_ontario / axis_square / 8 / original / 0 | 17.264874448 | 17.264874448 / 0.897364416 | 0.028 / 5.025 | max_seconds | [D5_961bbf3fef3ea030184a](runs/D5_961bbf3fef3ea030184a/result.json) · [D5_961bbf3fef3ea030184a](runs/D5_961bbf3fef3ea030184a/record.json) |
| D5 / lake_ontario / axis_square / 8 / original / 1 | 17.264874448 | 17.264874448 / 0.897364416 | 0.032 / 5.029 | max_seconds | [D5_3f7eefbc63784c25b559](runs/D5_3f7eefbc63784c25b559/result.json) · [D5_3f7eefbc63784c25b559](runs/D5_3f7eefbc63784c25b559/record.json) |
| D5 / lake_ontario / heading_square / 4 / cached / 0 | 17.264874448 | 17.264874448 / 0.897364416 | 0.026 / 5.023 | max_seconds | [D5_3b3cd38395c14d50ae8c](runs/D5_3b3cd38395c14d50ae8c/result.json) · [D5_3b3cd38395c14d50ae8c](runs/D5_3b3cd38395c14d50ae8c/record.json) |
| D5 / arctic_ocean / axis_square / 4 / original / 1 | 20.386109349 | 20.386109349 / 0.908583112 | 0.026 / 5.022 | max_seconds | [D5_902273bac81b8aa5726b](runs/D5_902273bac81b8aa5726b/result.json) · [D5_902273bac81b8aa5726b](runs/D5_902273bac81b8aa5726b/record.json) |
| D5 / lake_ontario / heading_square / 4 / original / 2 | 17.264874448 | 17.264874448 / 0.897364416 | 0.025 / 5.022 | max_seconds | [D5_fc9b8dc6a000512b93af](runs/D5_fc9b8dc6a000512b93af/result.json) · [D5_fc9b8dc6a000512b93af](runs/D5_fc9b8dc6a000512b93af/record.json) |
| D5 / arctic_ocean / heading_square / 8 / cached / 1 | 20.386109349 | 20.317725022 / 0.910565427 | 4.236 / 5.027 | max_seconds | [D5_0a4b7415fd15ed5fd8b0](runs/D5_0a4b7415fd15ed5fd8b0/result.json) · [D5_0a4b7415fd15ed5fd8b0](runs/D5_0a4b7415fd15ed5fd8b0/record.json) |
| D5 / lake_ontario / axis_square / 4 / original / 1 | 17.264874448 | 17.264874448 / 0.897364416 | 0.029 / 5.026 | max_seconds | [D5_b86d40121539a1f4766c](runs/D5_b86d40121539a1f4766c/result.json) · [D5_b86d40121539a1f4766c](runs/D5_b86d40121539a1f4766c/record.json) |
| D5 / lake_ontario / heading_square / 4 / original / 1 | 17.264874448 | 17.264874448 / 0.897364416 | 0.025 / 5.022 | max_seconds | [D5_d2f89c1a437c7002f593](runs/D5_d2f89c1a437c7002f593/result.json) · [D5_d2f89c1a437c7002f593](runs/D5_d2f89c1a437c7002f593/record.json) |
| D5 / arctic_ocean / axis_square / 8 / original / 1 | 20.386109349 | 20.386109349 / 0.908583112 | 0.023 / 5.019 | max_seconds | [D5_6b7a06cfdc4ef46c19b5](runs/D5_6b7a06cfdc4ef46c19b5/result.json) · [D5_6b7a06cfdc4ef46c19b5](runs/D5_6b7a06cfdc4ef46c19b5/record.json) |
| D5 / lake_ontario / heading_square / 8 / cached / 0 | 17.264874448 | 16.752262696 / 0.904678365 | 2.194 / 5.018 | max_seconds | [D5_9aa6d6cb742531d422f8](runs/D5_9aa6d6cb742531d422f8/result.json) · [D5_9aa6d6cb742531d422f8](runs/D5_9aa6d6cb742531d422f8/record.json) |
| D5 / arctic_ocean / heading_square / 4 / cached / 1 | 20.386109349 | 20.386109349 / 0.908583112 | 0.034 / 5.030 | max_seconds | [D5_042436698b10052404a9](runs/D5_042436698b10052404a9/result.json) · [D5_042436698b10052404a9](runs/D5_042436698b10052404a9/record.json) |
| D5 / arctic_ocean / axis_square / 4 / original / 2 | 20.386109349 | 20.386109349 / 0.908583112 | 0.026 / 5.022 | max_seconds | [D5_1434abf9fb7a28c80748](runs/D5_1434abf9fb7a28c80748/result.json) · [D5_1434abf9fb7a28c80748](runs/D5_1434abf9fb7a28c80748/record.json) |
| D5 / lake_ontario / axis_square / 8 / cached / 0 | 17.264874448 | 17.264874448 / 0.897364416 | 0.028 / 5.025 | max_seconds | [D5_00c31f200def5e18870a](runs/D5_00c31f200def5e18870a/result.json) · [D5_00c31f200def5e18870a](runs/D5_00c31f200def5e18870a/record.json) |
| D5 / lake_ontario / heading_square / 4 / cached / 2 | 17.264874448 | 17.264874448 / 0.897364416 | 0.029 / 5.026 | max_seconds | [D5_28c054bebe96af82091e](runs/D5_28c054bebe96af82091e/result.json) · [D5_28c054bebe96af82091e](runs/D5_28c054bebe96af82091e/record.json) |
| D5 / arctic_ocean / heading_square / 4 / original / 1 | 20.386109349 | 20.386109349 / 0.908583112 | 0.023 / 5.019 | max_seconds | [D5_34e2bbc0c5fa4422fe15](runs/D5_34e2bbc0c5fa4422fe15/result.json) · [D5_34e2bbc0c5fa4422fe15](runs/D5_34e2bbc0c5fa4422fe15/record.json) |
| D5 / lake_ontario / heading_square / 4 / cached / 1 | 17.264874448 | 17.264874448 / 0.897364416 | 0.033 / 5.029 | max_seconds | [D5_d00bc038198edfc1f422](runs/D5_d00bc038198edfc1f422/result.json) · [D5_d00bc038198edfc1f422](runs/D5_d00bc038198edfc1f422/record.json) |
| D5 / lake_ontario / axis_square / 4 / original / 0 | 17.264874448 | 17.264874448 / 0.897364416 | 0.032 / 5.029 | max_seconds | [D5_c98dc163d6225b15ce67](runs/D5_c98dc163d6225b15ce67/result.json) · [D5_c98dc163d6225b15ce67](runs/D5_c98dc163d6225b15ce67/record.json) |
| D5 / arctic_ocean / heading_square / 4 / cached / 0 | 20.386109349 | 20.386109349 / 0.908583112 | 0.033 / 5.029 | max_seconds | [D5_bbe92d53ab88fb62f169](runs/D5_bbe92d53ab88fb62f169/result.json) · [D5_bbe92d53ab88fb62f169](runs/D5_bbe92d53ab88fb62f169/record.json) |
| D5 / arctic_ocean / axis_square / 8 / cached / 1 | 20.386109349 | 20.386109349 / 0.908583112 | 0.022 / 5.018 | max_seconds | [D5_4999bc0c27462ad16038](runs/D5_4999bc0c27462ad16038/result.json) · [D5_4999bc0c27462ad16038](runs/D5_4999bc0c27462ad16038/record.json) |
| D5 / arctic_ocean / heading_square / 4 / original / 0 | 20.386109349 | 20.386109349 / 0.908583112 | 0.024 / 5.020 | max_seconds | [D5_05612e48c5685e18a612](runs/D5_05612e48c5685e18a612/result.json) · [D5_05612e48c5685e18a612](runs/D5_05612e48c5685e18a612/record.json) |
| D5 / arctic_ocean / axis_square / 4 / cached / 2 | 20.386109349 | 20.386109349 / 0.908583112 | 0.041 / 5.038 | max_seconds | [D5_2940682d8df1febfbce9](runs/D5_2940682d8df1febfbce9/result.json) · [D5_2940682d8df1febfbce9](runs/D5_2940682d8df1febfbce9/record.json) |
| D5 / arctic_ocean / heading_square / 8 / cached / 0 | 20.386109349 | 20.317725022 / 0.910565427 | 4.472 / 5.026 | max_seconds | [D5_7c8fa41b6f65d1c4371f](runs/D5_7c8fa41b6f65d1c4371f/result.json) · [D5_7c8fa41b6f65d1c4371f](runs/D5_7c8fa41b6f65d1c4371f/record.json) |
| D5 / lake_ontario / axis_square / 4 / cached / 2 | 17.264874448 | 17.264874448 / 0.897364416 | 0.025 / 5.021 | max_seconds | [D5_6a4097e9360703a1a0d9](runs/D5_6a4097e9360703a1a0d9/result.json) · [D5_6a4097e9360703a1a0d9](runs/D5_6a4097e9360703a1a0d9/record.json) |
| D5 / lake_ontario / axis_square / 8 / cached / 1 | 17.264874448 | 17.264874448 / 0.897364416 | 0.026 / 5.022 | max_seconds | [D5_f74bca59b63a4fa0074f](runs/D5_f74bca59b63a4fa0074f/result.json) · [D5_f74bca59b63a4fa0074f](runs/D5_f74bca59b63a4fa0074f/record.json) |
| D5 / arctic_ocean / heading_square / 8 / cached / 2 | 20.386109349 | 20.317725022 / 0.910565427 | 4.143 / 5.034 | max_seconds | [D5_3997106a0dde7770492f](runs/D5_3997106a0dde7770492f/result.json) · [D5_3997106a0dde7770492f](runs/D5_3997106a0dde7770492f/record.json) |
| H30 / hudson_window_late / heading_square / 8 / cached / 0 | 20.337375787 | 19.815790368 / 0.921818146 | 2.207 / 30.140 | max_seconds | [H30_fea751cd114ce8da25aa](runs/H30_fea751cd114ce8da25aa/result.json) · [H30_fea751cd114ce8da25aa](runs/H30_fea751cd114ce8da25aa/record.json) |
| H30 / lake_window_early / heading_square / 4 / cached / 1 | 17.155386959 | 17.151955583 / 0.909765081 | 0.420 / 30.091 | max_seconds | [H30_e8a989b3d685aba19ce3](runs/H30_e8a989b3d685aba19ce3/result.json) · [H30_e8a989b3d685aba19ce3](runs/H30_e8a989b3d685aba19ce3/record.json) |
| H30 / lake_window_late / axis_square / 4 / cached / 1 | 17.406323592 | 17.276096664 / 0.906255942 | 0.594 / 30.052 | max_seconds | [H30_b244911bf987206c64bc](runs/H30_b244911bf987206c64bc/result.json) · [H30_b244911bf987206c64bc](runs/H30_b244911bf987206c64bc/record.json) |
| H30 / lake_window_early / heading_square / 8 / cached / 1 | 17.155386959 | 16.744214940 / 0.917916211 | 1.098 / 30.040 | max_seconds | [H30_d61cfd19348d4b766260](runs/H30_d61cfd19348d4b766260/result.json) · [H30_d61cfd19348d4b766260](runs/H30_d61cfd19348d4b766260/record.json) |
| H30 / hudson_window_late / axis_square / 4 / cached / 2 | 20.337375787 | 20.337375787 / 0.917093438 | 0.147 / 30.143 | max_seconds | [H30_f557132fb78ad6e80728](runs/H30_f557132fb78ad6e80728/result.json) · [H30_f557132fb78ad6e80728](runs/H30_f557132fb78ad6e80728/record.json) |
| H30 / hudson_window_early / axis_square / 8 / cached / 0 | 26.344691040 | 22.840425949 / 0.887116976 | 21.535 / 30.124 | max_seconds | [H30_cff06aa38a46777c16cc](runs/H30_cff06aa38a46777c16cc/result.json) · [H30_cff06aa38a46777c16cc](runs/H30_cff06aa38a46777c16cc/record.json) |
| H30 / hudson_window_late / heading_square / 8 / cached / 1 | 20.337375787 | 19.815790368 / 0.921818146 | 2.164 / 30.146 | max_seconds | [H30_043b43b2df0d26b48e51](runs/H30_043b43b2df0d26b48e51/result.json) · [H30_043b43b2df0d26b48e51](runs/H30_043b43b2df0d26b48e51/record.json) |
| H30 / lake_window_early / axis_square / 4 / cached / 2 | 17.155386959 | 17.151955583 / 0.909765081 | 0.429 / 30.096 | max_seconds | [H30_f5df5395b7eb8a5f6e09](runs/H30_f5df5395b7eb8a5f6e09/result.json) · [H30_f5df5395b7eb8a5f6e09](runs/H30_f5df5395b7eb8a5f6e09/record.json) |
| H30 / lake_window_early / axis_square / 4 / cached / 0 | 17.155386959 | 17.151955583 / 0.909765081 | 0.430 / 30.089 | max_seconds | [H30_2304f3c2757365a27d97](runs/H30_2304f3c2757365a27d97/result.json) · [H30_2304f3c2757365a27d97](runs/H30_2304f3c2757365a27d97/record.json) |
| H30 / lake_window_late / axis_square / 8 / cached / 0 | 17.406323592 | 17.176060142 / 0.900488532 | 2.539 / 30.033 | max_seconds | [H30_9876653feb7cb2aab430](runs/H30_9876653feb7cb2aab430/result.json) · [H30_9876653feb7cb2aab430](runs/H30_9876653feb7cb2aab430/record.json) |
| H30 / hudson_window_early / axis_square / 4 / cached / 0 | 26.344691040 | 26.344691040 / 0.824859360 | 0.136 / 30.131 | max_seconds | [H30_2b4aac5c4f17396fa452](runs/H30_2b4aac5c4f17396fa452/result.json) · [H30_2b4aac5c4f17396fa452](runs/H30_2b4aac5c4f17396fa452/record.json) |
| H30 / hudson_window_late / heading_square / 8 / cached / 2 | 20.337375787 | 19.815790368 / 0.921818146 | 2.092 / 30.141 | max_seconds | [H30_5811ff7fc6447d0a8758](runs/H30_5811ff7fc6447d0a8758/result.json) · [H30_5811ff7fc6447d0a8758](runs/H30_5811ff7fc6447d0a8758/record.json) |
| H30 / lake_window_late / heading_square / 4 / cached / 0 | 17.406323592 | 17.276096664 / 0.906255942 | 0.642 / 30.051 | max_seconds | [H30_783d14363e54c0a414a0](runs/H30_783d14363e54c0a414a0/result.json) · [H30_783d14363e54c0a414a0](runs/H30_783d14363e54c0a414a0/record.json) |
| H30 / hudson_window_early / heading_square / 4 / cached / 1 | 26.344691040 | 26.344691040 / 0.824859360 | 0.138 / 30.134 | max_seconds | [H30_f49fbbfcaf4fae2d083d](runs/H30_f49fbbfcaf4fae2d083d/result.json) · [H30_f49fbbfcaf4fae2d083d](runs/H30_f49fbbfcaf4fae2d083d/record.json) |
| H30 / lake_window_late / axis_square / 4 / cached / 2 | 17.406323592 | 17.276096664 / 0.906255942 | 0.594 / 30.049 | max_seconds | [H30_34e5bfb67adc0e0df588](runs/H30_34e5bfb67adc0e0df588/result.json) · [H30_34e5bfb67adc0e0df588](runs/H30_34e5bfb67adc0e0df588/record.json) |
| H30 / lake_window_early / axis_square / 8 / cached / 1 | 17.155386959 | 16.703731421 / 0.914320706 | 0.758 / 30.095 | max_seconds | [H30_4da6795f337ffed604b9](runs/H30_4da6795f337ffed604b9/result.json) · [H30_4da6795f337ffed604b9](runs/H30_4da6795f337ffed604b9/record.json) |
| H30 / lake_window_late / heading_square / 4 / cached / 2 | 17.406323592 | 17.276096664 / 0.906255942 | 0.654 / 30.046 | max_seconds | [H30_ecda8b859e2a80d84df0](runs/H30_ecda8b859e2a80d84df0/result.json) · [H30_ecda8b859e2a80d84df0](runs/H30_ecda8b859e2a80d84df0/record.json) |
| H30 / hudson_window_late / axis_square / 8 / cached / 2 | 20.337375787 | 19.941886265 / 0.922347745 | 3.354 / 30.088 | max_seconds | [H30_8662869590233e0b2de5](runs/H30_8662869590233e0b2de5/result.json) · [H30_8662869590233e0b2de5](runs/H30_8662869590233e0b2de5/record.json) |
| H30 / hudson_window_early / axis_square / 8 / cached / 2 | 26.344691040 | 22.840425949 / 0.887116976 | 21.692 / 30.121 | max_seconds | [H30_b40c2413313da68b726a](runs/H30_b40c2413313da68b726a/result.json) · [H30_b40c2413313da68b726a](runs/H30_b40c2413313da68b726a/record.json) |
| H30 / lake_window_early / heading_square / 8 / cached / 0 | 17.155386959 | 16.744214940 / 0.917916211 | 1.085 / 30.044 | max_seconds | [H30_77a91ed09074d8a652b6](runs/H30_77a91ed09074d8a652b6/result.json) · [H30_77a91ed09074d8a652b6](runs/H30_77a91ed09074d8a652b6/record.json) |
| H30 / hudson_window_early / heading_square / 4 / cached / 2 | 26.344691040 | 26.344691040 / 0.824859360 | 0.144 / 30.139 | max_seconds | [H30_811c749e4b8af6fd1502](runs/H30_811c749e4b8af6fd1502/result.json) · [H30_811c749e4b8af6fd1502](runs/H30_811c749e4b8af6fd1502/record.json) |
| H30 / lake_window_late / heading_square / 8 / cached / 2 | 17.406323592 | 16.871848574 / 0.897995258 | 10.998 / 30.072 | max_seconds | [H30_04e60d4fe2aefca9cfed](runs/H30_04e60d4fe2aefca9cfed/result.json) · [H30_04e60d4fe2aefca9cfed](runs/H30_04e60d4fe2aefca9cfed/record.json) |
| H30 / lake_window_late / axis_square / 8 / cached / 2 | 17.406323592 | 17.176060142 / 0.900488532 | 2.560 / 30.035 | max_seconds | [H30_b8f23ab2448973d578c4](runs/H30_b8f23ab2448973d578c4/result.json) · [H30_b8f23ab2448973d578c4](runs/H30_b8f23ab2448973d578c4/record.json) |
| H30 / lake_window_late / heading_square / 8 / cached / 0 | 17.406323592 | 16.871848574 / 0.897995258 | 11.175 / 30.074 | max_seconds | [H30_9737b3621b2f8a7856a7](runs/H30_9737b3621b2f8a7856a7/result.json) · [H30_9737b3621b2f8a7856a7](runs/H30_9737b3621b2f8a7856a7/record.json) |
| H30 / lake_window_early / axis_square / 8 / cached / 0 | 17.155386959 | 16.703731421 / 0.914320706 | 0.815 / 30.104 | max_seconds | [H30_66486b3a104f239aba95](runs/H30_66486b3a104f239aba95/result.json) · [H30_66486b3a104f239aba95](runs/H30_66486b3a104f239aba95/record.json) |
| H30 / lake_window_early / heading_square / 4 / cached / 2 | 17.155386959 | 17.151955583 / 0.909765081 | 0.416 / 30.079 | max_seconds | [H30_c377267008211de3b76c](runs/H30_c377267008211de3b76c/result.json) · [H30_c377267008211de3b76c](runs/H30_c377267008211de3b76c/record.json) |
| H30 / hudson_window_late / axis_square / 4 / cached / 0 | 20.337375787 | 20.337375787 / 0.917093438 | 0.104 / 30.100 | max_seconds | [H30_34d4cab0b12059cfa6b7](runs/H30_34d4cab0b12059cfa6b7/result.json) · [H30_34d4cab0b12059cfa6b7](runs/H30_34d4cab0b12059cfa6b7/record.json) |
| H30 / lake_window_early / heading_square / 8 / cached / 2 | 17.155386959 | 16.744214940 / 0.917916211 | 1.151 / 30.042 | max_seconds | [H30_95509095fd2e2c6ce359](runs/H30_95509095fd2e2c6ce359/result.json) · [H30_95509095fd2e2c6ce359](runs/H30_95509095fd2e2c6ce359/record.json) |
| H30 / hudson_window_early / axis_square / 4 / cached / 2 | 26.344691040 | 26.344691040 / 0.824859360 | 0.140 / 30.136 | max_seconds | [H30_1e9f60fe88ced95a0d18](runs/H30_1e9f60fe88ced95a0d18/result.json) · [H30_1e9f60fe88ced95a0d18](runs/H30_1e9f60fe88ced95a0d18/record.json) |
| H30 / hudson_window_late / axis_square / 8 / cached / 0 | 20.337375787 | 19.941886265 / 0.922347745 | 3.350 / 30.084 | max_seconds | [H30_f193721b8db86ab06802](runs/H30_f193721b8db86ab06802/result.json) · [H30_f193721b8db86ab06802](runs/H30_f193721b8db86ab06802/record.json) |
| H30 / hudson_window_late / heading_square / 4 / cached / 0 | 20.337375787 | 20.337375787 / 0.917093438 | 0.091 / 30.087 | max_seconds | [H30_94f8e6b85b12f990942f](runs/H30_94f8e6b85b12f990942f/result.json) · [H30_94f8e6b85b12f990942f](runs/H30_94f8e6b85b12f990942f/record.json) |
| H30 / hudson_window_late / axis_square / 4 / cached / 1 | 20.337375787 | 20.337375787 / 0.917093438 | 0.101 / 30.096 | max_seconds | [H30_981050adec7fbd650047](runs/H30_981050adec7fbd650047/result.json) · [H30_981050adec7fbd650047](runs/H30_981050adec7fbd650047/record.json) |
| H30 / hudson_window_early / heading_square / 4 / cached / 0 | 26.344691040 | 26.344691040 / 0.824859360 | 0.140 / 30.136 | max_seconds | [H30_e2b50a7ac703ef475325](runs/H30_e2b50a7ac703ef475325/result.json) · [H30_e2b50a7ac703ef475325](runs/H30_e2b50a7ac703ef475325/record.json) |
| H30 / lake_window_late / heading_square / 4 / cached / 1 | 17.406323592 | 17.276096664 / 0.906255942 | 0.622 / 30.044 | max_seconds | [H30_faf195d7a2f7985206c6](runs/H30_faf195d7a2f7985206c6/result.json) · [H30_faf195d7a2f7985206c6](runs/H30_faf195d7a2f7985206c6/record.json) |
| H30 / lake_window_late / heading_square / 8 / cached / 1 | 17.406323592 | 16.871848574 / 0.897995258 | 10.495 / 30.081 | max_seconds | [H30_18cabf243b8c0853c63a](runs/H30_18cabf243b8c0853c63a/result.json) · [H30_18cabf243b8c0853c63a](runs/H30_18cabf243b8c0853c63a/record.json) |
| H30 / hudson_window_early / axis_square / 8 / cached / 1 | 26.344691040 | 22.840425949 / 0.887116976 | 21.450 / 30.127 | max_seconds | [H30_52206899884df27cb12d](runs/H30_52206899884df27cb12d/result.json) · [H30_52206899884df27cb12d](runs/H30_52206899884df27cb12d/record.json) |
| H30 / hudson_window_early / heading_square / 8 / cached / 2 | 26.344691040 | 22.790164159 / 0.895362734 | 7.731 / 30.102 | max_seconds | [H30_efa705a621eee0a8a2f8](runs/H30_efa705a621eee0a8a2f8/result.json) · [H30_efa705a621eee0a8a2f8](runs/H30_efa705a621eee0a8a2f8/record.json) |
| H30 / hudson_window_late / axis_square / 8 / cached / 1 | 20.337375787 | 19.941886265 / 0.922347745 | 3.381 / 30.094 | max_seconds | [H30_44e04f7a9df369185fb7](runs/H30_44e04f7a9df369185fb7/result.json) · [H30_44e04f7a9df369185fb7](runs/H30_44e04f7a9df369185fb7/record.json) |
| H30 / lake_window_late / axis_square / 8 / cached / 1 | 17.406323592 | 17.176060142 / 0.900488532 | 2.533 / 30.039 | max_seconds | [H30_fec1b2d4c1f7bd27a23d](runs/H30_fec1b2d4c1f7bd27a23d/result.json) · [H30_fec1b2d4c1f7bd27a23d](runs/H30_fec1b2d4c1f7bd27a23d/record.json) |
| H30 / lake_window_early / axis_square / 4 / cached / 1 | 17.155386959 | 17.151955583 / 0.909765081 | 0.408 / 30.082 | max_seconds | [H30_b6ee15c8bafb918b6221](runs/H30_b6ee15c8bafb918b6221/result.json) · [H30_b6ee15c8bafb918b6221](runs/H30_b6ee15c8bafb918b6221/record.json) |
| H30 / hudson_window_early / axis_square / 4 / cached / 1 | 26.344691040 | 26.344691040 / 0.824859360 | 0.137 / 30.134 | max_seconds | [H30_227a952a58d3b8053497](runs/H30_227a952a58d3b8053497/result.json) · [H30_227a952a58d3b8053497](runs/H30_227a952a58d3b8053497/record.json) |
| H30 / hudson_window_early / heading_square / 8 / cached / 0 | 26.344691040 | 22.790164159 / 0.895362734 | 7.377 / 30.146 | max_seconds | [H30_4682561c232631392cb5](runs/H30_4682561c232631392cb5/result.json) · [H30_4682561c232631392cb5](runs/H30_4682561c232631392cb5/record.json) |
| H30 / lake_window_early / axis_square / 8 / cached / 2 | 17.155386959 | 16.703731421 / 0.914320706 | 0.766 / 30.091 | max_seconds | [H30_8eb8426a2ec3af42d5dd](runs/H30_8eb8426a2ec3af42d5dd/result.json) · [H30_8eb8426a2ec3af42d5dd](runs/H30_8eb8426a2ec3af42d5dd/record.json) |
| H30 / lake_window_early / heading_square / 4 / cached / 0 | 17.155386959 | 17.151955583 / 0.909765081 | 0.400 / 30.078 | max_seconds | [H30_674d40dd2d4e2a838fe3](runs/H30_674d40dd2d4e2a838fe3/result.json) · [H30_674d40dd2d4e2a838fe3](runs/H30_674d40dd2d4e2a838fe3/record.json) |
| H30 / hudson_window_early / heading_square / 8 / cached / 1 | 26.344691040 | 22.790164159 / 0.895362734 | 7.434 / 30.102 | max_seconds | [H30_ce3d6d742f1069c32938](runs/H30_ce3d6d742f1069c32938/result.json) · [H30_ce3d6d742f1069c32938](runs/H30_ce3d6d742f1069c32938/record.json) |
| H30 / lake_window_late / axis_square / 4 / cached / 0 | 17.406323592 | 17.276096664 / 0.906255942 | 0.597 / 30.049 | max_seconds | [H30_a2dc37500e87f25dba17](runs/H30_a2dc37500e87f25dba17/result.json) · [H30_a2dc37500e87f25dba17](runs/H30_a2dc37500e87f25dba17/record.json) |
| H30 / hudson_window_late / heading_square / 4 / cached / 1 | 20.337375787 | 20.337375787 / 0.917093438 | 0.098 / 30.093 | max_seconds | [H30_b02a228c5947f8eaf53f](runs/H30_b02a228c5947f8eaf53f/result.json) · [H30_b02a228c5947f8eaf53f](runs/H30_b02a228c5947f8eaf53f/record.json) |
| H30 / hudson_window_late / heading_square / 4 / cached / 2 | 20.337375787 | 20.337375787 / 0.917093438 | 0.095 / 30.091 | max_seconds | [H30_44fe80b3ca70ca32dc14](runs/H30_44fe80b3ca70ca32dc14/result.json) · [H30_44fe80b3ca70ca32dc14](runs/H30_44fe80b3ca70ca32dc14/record.json) |
