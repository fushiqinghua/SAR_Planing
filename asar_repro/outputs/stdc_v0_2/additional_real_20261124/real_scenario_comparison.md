# 两组追加真实场景接入与对照（2026-11-24）

**整体状态：blocked。** Hudsons Bay 已通过 B2/B3 并完成同预算对照；Bay of Fundy 停在 B2 方向核验。不能宣称两组均正式完成。

## 数据来源与输入冻结

| 场景 | 历史风/流 | 接入结论 |
|---|---|---|
| Hudsons Bay（配置键 arctic_ocean） | GFS 固定预报周期 + HYCOM ESPC-D-V02 | B1/B2/B3 通过；500 个粒子；seed=41 |
| Bay of Fundy | HRRR f00 + GoMOFS native surface 子集 | B1 文件校验通过，B2 方向检查 blocked；未生成粒子或运行搜索 |

真实的是历史数值天气/海流模型产品，不是实测搜救目标轨迹。Leeway 生成的粒子仍是模型模拟；不冒充原作者逐字节相同 forcing 或事故真值。
原数据清单为 `data/manifests/historical_sources_additional_b1.json`；所有本地原始文件在 B2/B3 及每个对照子进程使用前均核对 SHA-256。
Hudson 粒子：`b3/arctic_ocean/particles.npz`，SHA-256 `6ed4ca52ecccc9369adae67f7da75477057317599869389224b6ffb488babfb6`。

Hudson 事故 UTC=2025-08-29T00:00:00Z，CST=2025-08-30T00:00:00Z；对象 LIFE-RAFT-DB-10；LKP=(-90.6,62.85)，CSP=(-90.447,62.786)。
N=500、seed=41、初始半径 100 m、T=60、q=0.78、65×85 四连通网格、扫宽/格宽 926 m、搜索步长 46.3 s。任务参数沿用原 stage7 配置，无调参追逐结果。
OpenDrift 1.14.12 在 Hudson 预处理阶段仅运行一次，完成 24 小时预漂移及搜索段；搜索仅消费冻结的绝对 UTC/trajectory_id/cell_ids/未探测权重。
质量守恒最大误差 4.44e-16；全部 500 个 ID 保留；该次 land/outside/inactive/unknown 质量均为 0，没有删除粒子或重新归一化。

两组完整对象、UTC、LKP/CSP、扫宽、T、来源 URL、产品类型、预报周期、有效时间及 SHA 详见 `scenario_manifest.json`。Fundy 任务参数为：PIW-1，事故 2025-02-14T00:00:00Z，CST=09:00:00Z，CSP=(-65.072,45.283)，扫宽 740.8 m，T=55，步长 37.04 s；这些参数已保留，但该场景未通过 reader 核验。

## Bay of Fundy 阻塞证据

| 点 | 文件 angle（度） | 经纬度几何 XI 方向（度） | 差值（度） |
|---|---:|---:|---:|
| LKP | 32.004353 | 25.098762 | 6.905590 |
| CSP | 32.004244 | 24.920559 | 7.083686 |

文件为 spherical=1，angle.units=radians、long_name=angle between XI-axis and EAST。Geod 和独立局部切平面差分均支持约 25° 的几何方向。现有 2° 门槛未更改；不擅自重算 angle、放宽断言或改环境 forcing。
这是尚未解决的原始元数据/坐标约定冲突，不能仅凭此断言 NOAA 上游有错。须复核原始 parent/grid 文件的 angle 和速度分量基底；当前本地只有已交付子集及上游提取审计，13 个完整 parent 文件未重新在本地校验。
ROMS 对 angle 的定义见 [官方 mod_grid.F](https://github.com/myroms/roms/blob/develop/ROMS/Modules/mod_grid.F)；[NOAA OFS FAQ](https://www.tidesandcurrents.noaa.gov/ofs/ofs_faq.html) 也给出了相应 east/north 旋转约定。它们支持核验方法，未解释本地约 7° 的冲突。
详情与源文件 SHA：`fundy_orientation_diagnosis.json`；原失败命令、stderr 和 summary 均保留在 `b2_r2/bay_of_fundy/` 及 `b2_fundy_r2.*`。

## Hudson 同预算实验

8 个既有变体，每个协议 3 次重复，共 48 次；另有 8 次 smoke。重复使用同一 seed=41 粒子归档，用于观察耗时波动，不是 3 个独立随机环境。方法顺序循环轮换，子进程顺序运行。
work：最多 5000 次扩展、30 s、OPEN≤20000；wall：5 s、OPEN≤20000，不限制扩展数。算法预处理计入方法耗时；共同 PT 构造及输入 SHA 校验单独报告。128 MiB 为 DP 管理数组预算，不是全进程峰值内存上限。
共同动态 PT：J=25.293460991040，Pd=0.817636946880，构造耗时 0.002424 s。

下表为每组 3 次的中位数。J 越小越好；Pd 越大越好；目标仍是原评价器 J，不改成 Pd 或多目标。

| 预算 | 方法 | J 中位数 | J 范围 | Pd 中位数 | 耗时 s | 扩展数 | 进程峰值 MiB | 正常完成/预算中止 |
|---|---|---:|---|---:|---:|---:|---:|---|
| work | paper_baseline | 20.390881327 | [20.390881327, 20.390881327] | 0.906729745 | 1.3710 | 696 | 284.97 | 3/0 |
| work | prior_stdc | 20.386109349 | [20.386109349, 20.386109349] | 0.908583112 | 4.8865 | 5000 | 387.85 | 0/3 |
| work | compressed_stdc | 20.386109349 | [20.386109349, 20.386109349] | 0.908583112 | 5.1346 | 5000 | 377.45 | 0/3 |
| work | dp_only | 25.293460991 | [25.293460991, 25.293460991] | 0.817636947 | 0.0065 | 0 | 219.14 | 0/3 |
| work | stdc_dp | 25.293460991 | [25.293460991, 25.293460991] | 0.817636947 | 0.0060 | 0 | 219.21 | 0/3 |
| work | mid_plain | 20.386109349 | [20.386109349, 20.386109349] | 0.908583112 | 10.9870 | 4922 | 335.24 | 0/3 |
| work | mid_diverse | 20.386109349 | [20.386109349, 20.386109349] | 0.908583112 | 12.2964 | 4919 | 346.41 | 0/3 |
| work | mid_dp | 25.293460991 | [25.293460991, 25.293460991] | 0.817636947 | 0.0057 | 0 | 219.32 | 0/3 |
| wall | paper_baseline | 20.390881327 | [20.390881327, 20.390881327] | 0.906729745 | 1.2855 | 696 | 284.30 | 3/0 |
| wall | prior_stdc | 20.386109349 | [20.386109349, 20.386109349] | 0.908583112 | 5.0257 | 4881 | 386.33 | 0/3 |
| wall | compressed_stdc | 20.386109349 | [20.386109349, 20.386109349] | 0.908583112 | 5.0252 | 4396 | 370.28 | 0/3 |
| wall | dp_only | 25.293460991 | [25.293460991, 25.293460991] | 0.817636947 | 0.0061 | 0 | 218.96 | 0/3 |
| wall | stdc_dp | 25.293460991 | [25.293460991, 25.293460991] | 0.817636947 | 0.0056 | 0 | 218.92 | 0/3 |
| wall | mid_plain | 20.390576890 | [20.390576890, 25.293460991] | 0.906963945 | 5.0080 | 1130 | 316.14 | 0/3 |
| wall | mid_diverse | 25.293460991 | [20.390576890, 25.293460991] | 0.817636947 | 5.0082 | 852 | 321.62 | 0/3 |
| wall | mid_dp | 25.293460991 | [25.293460991, 25.293460991] | 0.817636947 | 0.0058 | 0 | 219.20 | 0/3 |

逐次配对差值见 `benchmark/paired_comparisons.csv`；最终路径、incumbent 来源、各阶段预算、轨迹 ID 映射、质量曲线、误差、峰值内存及停止原因均保存在每个子进程 `result.json`。

全体状态：6 正常完成，42 预算中止；每条最终路径、每次 incumbent 及候选路径均经原评价器独立重放与合法性校验，最终 J 重放最大误差 0。

### 核心比较与适用范围

- work：最佳中位 J 变体 prior_stdc；相对 paper_baseline，J 下降 0.023403%，Pd 差值 +0.001853367。
- wall：最佳中位 J 变体 prior_stdc；相对 paper_baseline，J 下降 0.023403%，Pd 差值 +0.001853367。
- 中段 rollout 在 5 秒协议中有 3/6 次只保留共同 PT；详见各 repeat 的 phase 和 incumbent_origin。中位数不能掩盖这些未改善的结果。
- 时间预算使用协作式检查；本批方法最大超时余量为 0.031692 s，逐次值保存在 metrics.csv。另有 180 s 子进程 watchdog，本批未触发。

DP 预算阻塞：5525 个格点、T=60、压缩后 386 个轨迹组需要约 992.89 MiB 管理数组，超过固定 128 MiB。dp_only/stdc_dp/mid_dp 均在分配前停止，扩展数 0、incumbent 为共同 PT。它们的 PT 分数不能解释为 DP 搜索能力差或正常完成。
该尺度压缩仅将 500 列降为 386 列（减少 22.8%）；压缩/DP 的收益与 Lake Ontario 的小网格不能直接类推。
原 paper_greedy 的动态可采纳性未成立，即使状态 completed 也不意味着认证最优；研究变体预算中止也没有条件性离散 ε 证书。本批全部 uncertified。
Lake Ontario 旧最佳 J=17.264874448 属于另一套任务/粒子/时域，不能作为 Hudson 的绝对 J 达标线。旧实验未复跑、未覆盖；只能做每个场景内部的配对比较。

## 测试、失败记录与保全

- 新 reader 测试最终 21 passed；全量最终 924 passed，0 failed/errors/skipped。新测试包含两面配准、角度旋转、湿干/缺测、原拓扑插值、绝对 UTC、禁止外推、SHA 拒绝和中文路径 netCDF 回归。
- 初次新测试的整数 NaN fixture 错误已在新测试内修正；历史 CLI 首次失败来自 Git dubious ownership，恢复仅进程级 safe.directory 后通过，未改历史测试。
- netCDF4 绝对中文路径 I/O 错误在新 reader 中改为已校验字节的内存 Dataset，并补回归；先前失败记录没有删除。
- 个别 pytest 管道 stderr 含 pyreadline 析构 warning，退出码为 0；保留原 stderr，与测试断言失败明确区分。
- 4696 个研究目录既有文件、654 个冻结 baseline 文件 SHA 均不变；baseline 分支与提交未移动；原评价器、B7、Stage7、旧研究结果和原 forcing 未覆盖。
- 最终复核了 350 份阶段归档条目；完整版本/输入/实现哈希见 `validation_summary.json`、`environment.json` 和各阶段 manifest。

## 本次代码文件

- `src/asar_repro/additional_forcing.py`：追加历史 forcing 的只读适配。
- `tests/test_additional_forcing.py`：21 项数值/文件测试。
- `scripts/run_additional_real.py`：B2/B3 顺序 gate、一次 Leeway、质量与归档验证。
- `scripts/compare_additional_real.py`：双场景协议、冻结输入、独立子进程对照和绘图；两组全部通过才允许双场景运行。
- `scripts/compare_available_real.py`：明确记录 Fundy blocked 的 Hudson 单场景对照入口；保留全部逐场景 gate。
- `outputs/.../finalize_report.py`：生成本报告及最终验证摘要。

## 模型局限与尚未实现

保持既有 all-water 海岸碰撞近似，但原 forcing 的 dry/masked/outside 状态仍进入 land/unknown/outside 质量；尚未实现完整岸线碰撞或漂浮物搁浅物理。HYCOM 湿样本 sea-ice fraction 全部核验为零；未模拟海冰耦合。
GFS 按 3 小时、HRRR/HYCOM/GoMOFS 按 1 小时线性时间插值；空间采用各自原网格双线性或保留拓扑的三角插值。解码、配准与插值是本地适配近似；不声称作者原 forcing/手工 PT 复现。
Fundy 仍需解决原始 angle/几何方向冲突后重新通过 B2，随后才能运行 B3 和同预算对照。尚未扩大 DP 内存预算、改变算法目标/forcing 或开展新的创新点；本轮无 GitHub 推送。

## 离线命令

在项目根目录使用 maritime-sar 解释器，并按 `offline_rerun.ps1` 设置离线、UTF-8、PATH、PYTHONPATH、单线程和进程级 Git trust 环境。所有输出使用新目录，已有目录会拒绝覆盖。
最终测试命令：

```powershell
& $PY -m pytest -q -x -p no:cacheprovider --basetemp C:/Users/35448/Documents/Codex/2026-11-23/new-chat-4/additional_real_final_pytest --junitxml "$RUN/final_full_tests.xml"
```

完整离线复跑命令、日志重定向和 Hudson/Fundy 的不同阶段范围见 `offline_rerun.ps1`。如再次检查 Fundy，原 B2 命令会继续拒绝方向不一致的数据；不绕过。

核心路径顺序可视化：`hudson_core_comparison.png`；逐步质量及 J 差异见 `hudson_stepwise_comparison.csv`。baseline 与 STDC 首次在 t=51 分岔，改善量由原评分器重放获得。

主要交付：`benchmark/metrics.csv`、`aggregate.csv`、`paired_comparisons.csv`；路径图、剩余质量/质量改进曲线和效率图均在 `benchmark/`；粒子图和质量 CSV 在 `b3/arctic_ocean/`。
