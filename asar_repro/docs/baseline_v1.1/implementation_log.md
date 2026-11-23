# A^SAR Baseline v1.1 实施日志

## B0 · 冻结阶段 8 基线

**状态为 `passed`。** 按执行手册 §3 核验了历史版本的可恢复性。开始时，`SAR_Planing-upload` 的工作树干净，`upload/asar-repro-stage8` 和其本地远端跟踪分支均指向 `abd1b472798fbf3d318e83d09caf9b69cc459122`。为这个提交创建了本地标签 `asar-repro-v1.0` 和独立工作树 `SAR_Planing-v1.1`，后续开发分支为 `baseline-v1.1`。

手册 SHA-256 为 `5ABD8007A4E8590C99F4AA03D8A2B2573C0130578B7FC370D8219A5EE391ADB0`。本轮变更限于本日志与下表五份证据文件。

### 核验命令和环境

建分支前在上传仓库执行 `git status --short --branch`、`git branch --show-current`、`git rev-parse HEAD`、`git branch -avv`、`git tag --list` 和 `git worktree list --porcelain`。查明分支和标签名可用后，在 baseline 目录执行以下一次性操作，均以 0 退出。

```powershell
git -C SAR_Planing-upload worktree add -b baseline-v1.1 ../SAR_Planing-v1.1 abd1b472798fbf3d318e83d09caf9b69cc459122
git -C SAR_Planing-upload tag asar-repro-v1.0 abd1b472798fbf3d318e83d09caf9b69cc459122
```

以下测试在 `SAR_Planing-v1.1/asar_repro` 下运行。实测 Python 3.11.18、OpenDrift 1.14.12；包版本和实际源码导入位置保存在环境快照中。禁写字节码并关闭 pytest 缓存，使 v1.0 已跟踪的缓存文件也能按字节比对。

```powershell
$PY = 'C:\Users\35448\.conda\envs\maritime-sar\python.exe'
$env:PYTHONUSERBASE = Join-Path (Get-Location) '.python-user'
$env:PYTHONPATH = (Resolve-Path '.\src').Path
$env:PATH = (Join-Path (Split-Path $PY) 'Library\bin') + [IO.Path]::PathSeparator + $env:PATH
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTEST_ADDOPTS = '-p no:cacheprovider'
& $PY -m pytest -q
& $PY -m pytest -q tests/test_heuristic_counterexample.py
```

| 测试 | 通过 / 失败 / 跳过 | pytest 耗时 | 含解释器启动的实测耗时 | 退出码 |
|---|---:|---:|---:|---:|
| 全量回归 | 130 / 0 / 0 | 20.94 s | 24.47 s | 0 |
| 单独复跑动态反例 | 2 / 0 / 0 | 0.25 s | 2.53 s | 0 |

### 数值与数据状态

3×3 动态反例中，根节点的 `paper_greedy` 值为 2.6170801771，96 条合法路径的精确最小余下 J 为 2.5417333379，高估 0.0753468392。专项还验证了第二个动态例子在 ε=1 时返回次优路线，以及两例的论文模式均为未认证。

从历史 `outputs/stage7/metrics.csv` 选取 ASAR_paper，按场景交叉核对各自 `results.json`。四组均为 `constant_synthetic`，每组 500 粒子、q=0.78。下列是已冻结运行的分组统计。B0 复跑了原测试中的粒子质量、J/Pd 和路径重放检查，本轮没有另行启动四场景 benchmark。

| 场景 | T | 正常结束 | 达到 600 次扩展后返回初始 PT |
|---|---:|---:|---:|
| Lake Ontario | 49 | 3 | 5 |
| Bay of Fundy | 55 | 4 | 4 |
| Salish Sea | 41 | 5 | 3 |
| Arctic Ocean | 60 | 3 | 5 |

历史 OPEN 限制为 2400，时间限制为 30 秒。17/32 次中止均记录为 `max_expansions`，其 J/Pd 属于所返回的 PT。真实历史风流文件对留到 B1 验证；B0 未使用真实 forcing。

### 历史文件保护与新增证据

测试前后枚举 v1.0 提交的 180 个已跟踪文件（含空目录占位文件），逐个比较 Git blob 与工作树字节，并比较前后两次 SHA-256 清单。180 个文件全部一致，覆盖旧源码、各阶段输出、粒子归档、summary.csv 和旧报告。新增证据单独保存。

| 文件 | SHA-256 |
|---|---|
| [环境与包版本](../../outputs/baseline_v1.1/b0/environment.json) | `36815959BE52FC5A1552818A29F50332DB7E997FDCD800F01A8E331039104D0B` |
| [v1.0 全部文件指纹](../../outputs/baseline_v1.1/b0/v1.0_sha256.json) | `7776A385E546D9E84DA6CDEA8D391B545F2E33CC2B598BD1DFA2BB023C3D0089` |
| [全量 pytest 输出](../../outputs/baseline_v1.1/b0/full_pytest.txt) | `E487124B273DCC95B4FEF74A75F976526FC9AEBD6ECBDBFDC1558BF2834552C4` |
| [反例 pytest 输出](../../outputs/baseline_v1.1/b0/counterexample_pytest.txt) | `CDF1FD5BF6D9D49F9BA3FE10976A7939BD2B5D273C1145286E690BA3692E786F` |
| [B0 验收报告](../../outputs/baseline_v1.1/b0/baseline_report.json) | `DBD1E3C09E3881FE16D719AC1EF676F500F8A8E44396D9AF1C260D7508B80C19` |

## B1 · Table I 历史风流文件可得性（首次线上探测）

**状态为 `blocked`。** 基于 `baseline-v1.1` 上的 B0 提交 `734380e`，对 Lake Ontario 做了最小文件获取，并逐个探测其余三组备选场景。清单生成和代码回归已完成。实际收取的风场、流场文件各为 0，四组数据均为 `unverified`。完整任务窗口、小时缓冲、来源目录证据和下一次重跑命令见[来源核验说明](source_inventory.md)。

### 运行与判读

命令均在 `asar_repro` 下使用上文 B0 环境执行。这里的 `$PY` 指向 `maritime-sar` 解释器。

| 命令 | 退出码 | 本次结果 |
|---|---:|---|
| `& $PY scripts/fetch_lake_b1.py` | 2 | Lake 选择 12Z 预报 f01–f05。风索引和湖流列表在建立 HTTPS 连接时报 WinError 10013 |
| `& $PY scripts/inventory_historical.py` | 2 | 20/20 项 DNS 解析成功，20/20 项 HTTPS 连接失败，0/4 对可以打开 |
| `& $PY -m pytest -q tests/test_b1_inventory.py` | 0 | 14 passed，0 failed，0 skipped，1.70 秒 |
| `& $PY -m pytest -q` | 0 | 144 passed，0 failed，0 skipped，13.04 秒 |

新增离线测试包含四组手算 UTC 结束时刻、跨日缓冲、目录响应与本地文件的区分、文件头与来源回执的指纹匹配、损坏文件、GRIB 范围与消息完整性、分月分页与别名、湖流不完整周期、下载限额、短传输与重试保护。测试数据均为测试目录中的临时样例。Lake 本次停止原因是网络访问错误，256 MiB 湖流限额未触发。J、Pd、粒子质量、扩展节点与搜索用时本阶段均不适用。

全量回归后再次对照 B0 清单，v1.0 的 180 个已跟踪文件全部通过 SHA-256 核对。在历史文件达到手册的时空覆盖、物理分量和来源核验要求前，B2 等待。

### 本阶段文件与指纹

| 文件 | SHA-256 |
|---|---|
| [归档清单脚本](../../scripts/inventory_historical.py) | `3B328BBD204C6EC9774A4387DC9497CE2A6DA97A93CF6B98BD58BF16DB9AAF32` |
| [Lake 最小获取脚本](../../scripts/fetch_lake_b1.py) | `6CEEE3A92FB1B0388BFA35B0A383D4DCB5AC12C69468B561F3EC3211221F0FAA` |
| [B1 测试](../../tests/test_b1_inventory.py) | `ABFE70ABED4523559100ED9FCF18E26F4027AB9B7EE07847F531EC4BD86E80A8` |
| [当时的四场景来源清单](../../outputs/baseline_v1.1/b1/initial_sources.json) | `12448657F1C2829C48CF0538E8EBEF53F26C8EBF12D5012668221C188775E5C5` |
| 来源核验说明初版（Git `1b9f961`） | `A475EA81CCCDEEB62AAB085EB236ACB79608FE95F9BC00E9D959790B58FB7EA6` |
| [获取回执](../../outputs/baseline_v1.1/b1/lake_acquisition.json) | `7612D5D99B7A85F90AC022C95D31C33D681C68778B7D81FF4D729BDCB6E47401` |
| [清单命令输出](../../outputs/baseline_v1.1/b1/inventory.txt) | `8F55B405F5787082854E5567ADAFDDF6EA6FD56FCB53A626AD4A7A37A7BD498B` |
| [B1 pytest 输出](../../outputs/baseline_v1.1/b1/b1_pytest.txt) | `472BF8A255B3109F013735317AB25E5C93B5ACCA2245A56DFC7A1FC33E6E3D37` |
| [全量 pytest 输出](../../outputs/baseline_v1.1/b1/full_pytest.txt) | `B41B9CBE82653B8A47C4B6C68565D4F193516D784EFA422A5CCBDF847A35BFDA` |

## B1 · Lake Ontario 手动交付复核

**状态为 `passed`，真实文件对为 1/4。** 用户交付的 ZIP 为 261,221,397 字节，SHA-256 为 `72f7f4473fa81b15de09c1316d41f3b6596471a36c15e4539717ce1f5db0ae78`。解压目录为 `data/raw/historical/ASAR_B1_LakeOntario_20250826/`。本地保留 ZIP 和原始文件，Git 提交收录校验工具、四场景清单和验证记录。

HRRR 五个 f00 文件共 21,911,006 字节，各含两个 10 米风原始消息。LOOFS 五个 18 UTC 循环 nowcast 完整文件共 350,797,365 字节。两组数据均覆盖 2025-08-26 13–17 UTC，间隔 3600 秒。任务时段为 14:45 至 15:52:33.740 UTC。数据支持事后重建；CST 时可用的实时预报回放和原作者起报周期均缺乏证据。

全场风和最浅层流的有效分量均已读取。LKP 和 CSP 每小时均落在湿单元，分别为从零计数的第 44948、44949 号单元。289 个搜索格心中 221 个在湿单元内，68 个在网格外。B2 需验证 HRRR 网格风旋转、LOOFS 单元中心的顶层映射与湿干掩膜，并显式处理域外查询。本轮工作限于数据验收，J、Pd、搜索扩展和粒子质量账本留给后续阶段。

| 用 `maritime-sar` 执行的命令 | 退出码 | 实测结果 |
|---|---:|---|
| 随包 `scripts/verify_hashes.py` | 0 | 26/26 个校验项匹配 |
| 随包 `scripts/validate_b1.py --report …` | 1 | 此解释器缺少 `eccodes`，包内脚本在导入阶段退出 |
| `scripts/verify_lake_b1.py` | 0 | 本地读取 10 个文件。NumPy 的 GRIB 解码与参考 ecCodes 全场摘要和两个点样值吻合；netCDF4 打开实际 FVCOM 文件验证时空和湿单元 |
| `-m pytest -q tests/test_b1_inventory.py tests/test_b1_package.py` | 0 | 18 passed，0 failed，0 skipped，3.03 秒 |
| `-m pytest -q` | 0 | 148 passed，0 failed，0 skipped，12.39 秒 |

新增 [HRRR 编码核验](../../scripts/b1_hrrr.py)、[离线数据包核验与清单合并](../../scripts/verify_lake_b1.py)、[数据包测试](../../tests/test_b1_package.py)。[常规清单入口](../../scripts/inventory_historical.py) 也会复核已解压的数据。Bay of Fundy、Salish Sea、Arctic Ocean 三组清单与首次快照逐项相同。v1.0 已跟踪的 180 个文件的 SHA-256 全部匹配。

| 本次证据 | SHA-256 |
|---|---|
| [本地验证 JSON](../../outputs/baseline_v1.1/b1/local/validation_local.json) | `54102833f169a06b280a0e67d5b40991685f7e7a745bd5999cda88cec920153b` |
| [合并后的来源清单](../../data/manifests/historical_sources.json) | `fa6f8c839bf894a3654a74c28e347f598b413e4ae0484bd7d090b718a43fc400` |

获取回执中的原始 URL、起报周期、HRRR 字节区间及逐文件 SHA-256 在合并后的清单中。详细复跑步骤与各测试输出见[来源说明](source_inventory.md)、[逐文件校验输出](../../outputs/baseline_v1.1/b1/local/hashes.txt)、[本地验收输出](../../outputs/baseline_v1.1/b1/local/verification.txt)、[专项测试](../../outputs/baseline_v1.1/b1/local/package_pytest.txt)和[全量回归](../../outputs/baseline_v1.1/b1/local/full_pytest.txt)。

## B2 · Lake Ontario 真实风流适配

**状态为 `passed`。** 从 B1 提交 `57284b0` 接续，逐文件复验 5 份 HRRR 与 5 份 LOOFS 的 SHA-256，并从原始字节解码风流。四个场景中本轮接入 Lake Ontario。数据用于事后环境重建。实测环境为 B0 的 `maritime-sar`，OpenDrift 1.14.12、NumPy 2.4.6、netCDF4 1.7.5、pyproj 3.7.2 和 Shapely 2.2.0。v1.0 的 180 个已跟踪文件全部通过 SHA-256 复核，原 `run_constant` 包含在全量回归中。

- **HRRR。** 读取原生 10 米网格 U/V，先在 3 km Lambert 投影网格双线性插值，再用查询位置的子午线收敛角转成地理东、北分量。以 B1 独立解码的原生格点和球面 Lambert 正切圆锥解析式作对照，最大分量差为 1.64×10⁻¹² m/s，速率模长最大差为 1.52×10⁻¹² m/s。[NCEP 网格模板 3.30](https://www.nco.ncep.noaa.gov/pmb/docs/grib2/grib2_doc/grib2_temp3-30.shtml) · [PROJ Lambert 投影](https://proj.org/en/stable/operations/projections/lcc.html)
- **LOOFS。** 在原生 UTM 三角网格查找包含位置的单元，采用其最浅 sigma 层的面心向量。原文件的经纬度投影到原生平面后，34395 个节点的最大坐标差约为 0.26 m。选取层的 sigma 约为 −0.025，全域节点所对应的层中心距水面约 0.027–5.712 m。事故点和搜索起点在五个整点的流速均与 B1 原位置样值一致。
- **时间与缺测。** 两类输入由各自文件的有效 UTC 驱动，共五个逐小时时次，覆盖 13–17 UTC。时间线性插值的最大许可间隔为 3600 秒。流场的两个括点都须为同一位置提供有效湿单元速度。原始数值缺失、干单元、网格外和时段外有显式状态。OpenDrift 的四个速度分量分别由两个互不重叠的 reader 提供，域外速度保留为缺测。
- **空间抽样。** 搜索格心的 289 个点中，风覆盖全部，流覆盖 221 个，其余 68 个在网格外。本轮另在搜索区域外扩 3 km 的矩形上抽样 25×25 个点，风覆盖 625 个，流覆盖 249 个，其余 376 个在网格外。3 km 是本轮的核验缓冲参数。岸线策略标记为 `historical_real_forcing_allwater`，同时执行 FVCOM 的湿干、域外速度门禁。实际粒子可达范围与搁浅处理留给 B3。

通过 OpenDrift 环境查询核验事故时刻、预漂移中点、CST、搜索结束，并在两个任务位置核对所有四个物理分量。CST 时 CSP 的风为 (4.982572, 2.270503) m/s，流为 (0.212247, 0.012753) m/s。速度分量的 OpenDrift float32 值与适配器计算值的最大差为 2.27×10⁻⁷ m/s。报告按时次保存了全场统计、经纬度范围、域外计数、reader 优先级与输入指纹。J、Pd、搜索扩展和粒子质量账本在本阶段不适用。[forcing 审计](../../outputs/baseline_v1.1/b2/forcing_audit.json)

### 新增文件与运行

- 读取模块核验输入哈希、坐标、单位和时间，并提供独立于漂移模型的采样接口。`probe` 返回向量及状态，`sample` 对缺测查询抛出异常。[forcing 读取与查询](../../src/asar_repro/forcing.py)
- HRRR 模块提供共享的 GRIB2 simple packing 解码与旋转，B1 核验入口也调用共享解码逻辑。[HRRR 解码和旋转](../../src/asar_repro/hrrr.py) · [B1 核验入口](../../scripts/b1_hrrr.py)
- OpenDrift 适配层提供表层风流接口与 reader 注册配置。审计脚本对四个时刻的任务位置、搜索格心和外扩范围生成 JSON。[OpenDrift readers](../../src/asar_repro/historical_reader.py) · [实测审计命令](../../scripts/validate_forcing.py)
- 专项测试在 pytest 隔离目录生成 3×3×4 CF 文件，覆盖单位、经纬度方向和跨日界线、插值、UTC、缺测、来源哈希以及 OpenDrift 数据选择。[B2 专项测试](../../tests/test_forcing.py)

在 `asar_repro` 中沿用 B0 的 PowerShell 环境。精确运行命令和结果如下。

| 命令 | 退出码 | 实测结果 |
|---|---:|---|
| `& $PY -m pytest -q tests/test_forcing.py` | 0 | 12 passed，0 failed，0 skipped，9.78 s |
| `& $PY scripts/validate_forcing.py` | 0 | Lake Ontario 通过，含解释器启动 12.18 s |
| `& $PY -m pytest -q` | 0 | 160 passed，0 failed，0 skipped，13.47 s |

专项单独执行时出现 88 条来自环境中 cmocean/Matplotlib 的弃用警告。警告原文保留在[专项日志](../../outputs/baseline_v1.1/b2/forcing_pytest.txt)。原始风流文件均位于 B1 导入目录，审计过程直接读取，没有生成裁切文件。

| 证据 | SHA-256 |
|---|---|
| [forcing_audit.json](../../outputs/baseline_v1.1/b2/forcing_audit.json) | `B78F6BEABCF396270A06B2305F29BFFE2FA989D9AF3914E7FFC44DE86D94D5BB` |
| [审计命令输出](../../outputs/baseline_v1.1/b2/forcing_audit_run.txt) | `6E2AE4A59F4C310B67773AD179025FE64C67E0FBB7B758CB8E7229915A66A551` |
| [全量 pytest 输出](../../outputs/baseline_v1.1/b2/full_pytest.txt) | `35C98144768CB8FB1B643E849C33E7F729A2D25971F08A3E2BEB2DF1E7C59D67` |

## B3 · Lake Ontario 真实 Leeway 轨迹与质量验收

**状态为 `passed`。** 从 B2 提交 `21bda2f` 接续，使用 `maritime-sar` 的 OpenDrift 1.14.12 对 Lake Ontario 运行一次连续漂移。场景参数沿用 PIW-2（本机对象编号 2）、100 m 初始半径、500 粒子、seed 41、17×17 搜索格和 185.2 m 格宽。风取五个 HRRR f00 分析时次，水流取 LOOFS 18 UTC 循环的回算时次。实验类型为 `historical_real_forcing_allwater`，表示事后环境重建。FVCOM 湿干和域外状态用于速度门禁，岸线策略采用全水域假设。

| 核验项 | 实测结果 |
|---|---|
| 原生轨迹 | 2025-08-26 14:45:00 至 15:53:00 UTC，30 s 积分，136 步 / 137 帧 |
| 规划轨迹 | 15:45:00 至 15:52:33.740 UTC，步长 9.26 s，共 49 步 / 50 帧 |
| 逐 ID 状态 | 500 个原始 ID（0–499）均贯穿全程。原生与规划帧的所有粒子均处于有效、可搜索格 |
| 纯漂移质量 | 逐原生帧的总权重误差不超过 6.67×10⁻¹⁶。陆地、域外、停用、未知四个特殊格本次质量均为 0 |
| 固定审计路线 | 从 CSP 向东起步、沿同一行往返。第 0 帧不探测，后续统一使用论文的 `q=0.78` |
| 路线审计结果 | `J=47.21975499424` 步，累计 `Pd=0.05770030656`，末帧剩余质量 `M_T=0.94229969344`。逐步质量守恒最大残差 4.44×10⁻¹⁶ |
| 独立复验 | 重积分后 21 个 NPZ 字段逐项完全一致。普通重跑通过源文件、配置和归档指纹检查后命中缓存 |

逐小时原生风流以线性插值接入 Leeway。模拟继续到搜索结束之后第一个 30 秒整点，以覆盖最后一个 9.26 秒规划帧。位置重采样复用 `Frames`，只在状态与掩膜一致时插值。原生与规划帧逐位置复核风流覆盖；一旦发生 forcing 导致的停用，后续帧保留该 ID 的域外、干单元或未知权重。专项测试用手算样例验证四类特殊格权重及重复探测。固定路线的数值用于审计粒子和评分器。搜索扩展数在 B3 不适用。

缓存身份包含源文件 SHA-256、场景配置、B2 审计、相关实现和依赖版本。原始文件缺失或指纹不符时，命令报告 `blocked`。配置哈希不同或缓存损坏时，命令拒绝复用。全量回归后比对 v1.0 的 180 个已跟踪文件，全部指纹匹配。

### 代码与复跑

- 一次性漂移、UTC 对齐、分格和固定路线质量计算由新模块实现。[历史漂移模块](../../src/asar_repro/historical_drift.py)
- 命令入口检查 B2 输入并发布原子归档，支持缓存命中和显式重积分。[生成与复验脚本](../../scripts/generate_historical_drift.py) · [绘图脚本](../../scripts/plot_historical_drift.py) · [专项测试](../../tests/test_historical_drift.py)

从 `asar_repro` 沿用 B0 的 PowerShell 环境。首次生成可指定新的 `--output-dir` 以保留现有归档。

| 命令 | 退出码 | 实测结果 |
|---|---:|---|
| `& $PY scripts/generate_historical_drift.py` | 0 | 首次生成 9.21 s，Leeway 积分 6.84 s，随后缓存重读 0.23 s |
| `& $PY scripts/generate_historical_drift.py --verify-replay` | 0 | 独立复验 8.15 s |
| `& $PY -m pytest -q tests/test_historical_drift.py` | 0 | 5 passed，0 failed，0 skipped，0.72 s |
| `& $PY -m pytest -q` | 0 | 165 passed，0 failed，0 skipped，12.07 s |

### 冻结证据

| 文件 | SHA-256 |
|---|---|
| [particles.npz](../../outputs/baseline_v1.1/lake_ontario_real/particles.npz) | `8b30a87e543f1b33c39e70e1d0054e1750ec046ba2e0b627dd311d9945749456` |
| [metadata.json](../../outputs/baseline_v1.1/lake_ontario_real/metadata.json) | `1e96ecea2547ca918dd068b7f86a3d4b680cdc89ad6814b1132ca80cdc5e89fc` |
| [mass_audit.csv](../../outputs/baseline_v1.1/lake_ontario_real/mass_audit.csv) | `47b66d2f36652b3aa28001997845fe430bbea2e8550fc673ebbcd47186b4339a` |

图件和机器可读复验日志可在归档中核对。[三时刻粒子分布](../../outputs/baseline_v1.1/lake_ontario_real/particles.png) · [CST 风流快照](../../outputs/baseline_v1.1/lake_ontario_real/forcing_snapshot.png) · [UTC 覆盖图](../../outputs/baseline_v1.1/lake_ontario_real/time_coverage.png) · [生成日志](../../outputs/baseline_v1.1/b3/generation.json) · [缓存命中](../../outputs/baseline_v1.1/b3/cache_hit.json) · [独立复验](../../outputs/baseline_v1.1/b3/replay_audit.json) · [全量 pytest](../../outputs/baseline_v1.1/b3/full_pytest.txt)

## B4 · 搜索结果语义与正确性边界

**状态为 `passed`。** 从 B3 提交 `fc5c815` 接续，执行手册 §7。此次审计没有发现需要修改搜索数学或启发式的退出路径错误，因此保留 `search.py`、`heuristic.py`、Oracle、评分器及所有原反例。修订 adapter 的报告输出，新增统一分类和记录模块。原 v1.0 的 180 个冻结文件中 179 个字节不变；仅复现仓库自身的 `planner_adapter.py` 按 B4 要求增强报告，未接入或修改用户原有海上搜救程序。

### 代码、配置与测试清单

| 文件 | 本轮作用 |
|---|---|
| [search_reporting.py](../../src/asar_repro/search_reporting.py) | 分开记录理论适用性、完成条件、路线来源；独立评分重放；完整必需字段；按 forcing 与算法分组统计 |
| [planner_adapter.py](../../src/asar_repro/planner_adapter.py) | 复用统一结果接口；补充时间、输入指纹、M_T；保持旧 status、路径和航点接口 |
| [audit_search_results.py](../../scripts/audit_search_results.py) | 可指定 zero/mass_lb/paper_greedy 的 toy benchmark；只读重放旧 32 次运行；自动报告和状态图 |
| [b4_search_audit.json](../../configs/b4_search_audit.json) | 三个 toy、两档 ε、无剪枝/剪枝/两种中止 profile，共 72 次 |
| [test_search_reporting.py](../../tests/test_search_reporting.py) | 退出路径、上界与来源、确定性时钟、无路径 null、接口计时与配置、forcing 分组 |
| [test_b4_artifacts.py](../../tests/test_b4_artifacts.py) | 保存字段、CSV null、两例反例、17/32 历史、来源指纹及 CLI 方法选择 |
| [search_result_semantics.md](search_result_semantics.md) | 结果字典、认证前提、时间口径、已发现的边界行为与报告限制 |

使用 B0 PowerShell 环境与既有 maritime-sar；实际 Python 3.11.18、NumPy 2.4.6、SciPy 1.17.1、OpenDrift 1.14.12。未安装或升级依赖，未重新生成 B3 真实轨迹。

| 命令 | 退出码 | 实测结果 |
|---|---:|---|
| `& $PY scripts/audit_search_results.py` | 0 | 72 条 toy，32 条历史记录，历史 J 重放误差 0 |
| `& $PY -m pytest -q tests/test_search_reporting.py tests/test_b4_artifacts.py tests/test_heuristic_counterexample.py` | 0 | 46 passed，1.87 s |
| `& $PY -m pytest -q` | 0 | 209 passed，0 failed，0 skipped，15.38 s |

CLI 可使用 `--heuristic mass_lb --output-dir <新目录>` 选择方法，专项测试实测生成 24 条 mass_lb 记录。完整测试包含旧 toy Oracle、动态反例、粒子/矩阵交叉验证、OpenDrift smoke 和旧 adapter 离线重放。

### 数值与发现

- 新结果明确分开 completed_search、aborted_feasible_incumbent、aborted_without_path。中止且无完整解时 path、J、Pd_T、M_T 为 null。有初始 PT 的中止结果归属 ParallelTrack。
- mass_lb/zero 理论适用性与获得完成证书分别记录；只有完整结束且模型前提成立时标记条件性离散 ε 界。paper_greedy 在本轮所有记录中均不认证。质量守恒、每步单格探测、q∈[0,1]、无虚假检测、t=0 不探测的前提保持不变。
- 72 条 toy 中 36 条正常完成、18 条保留 PT 的显式时间限额中止、18 条无完整路线中止。两种有下界的模式在 ε=1 时与 Oracle 的 J 差为 0；ε=1.1 界也逐例通过。这是有限样例事实，不等于所有输入的数值形式证明。
- 3×3、T=4、q=.78 反例仍为 `2.6170801771 > 2.5417333379`。另一动态例子 ε=1 的 paper_greedy 为 `2.197771238744739`，Oracle 为 `2.185746589095029`，差 `0.01202464964970984`。原反例文件与测试未修改。
- 历史 32 条中 17 条为 max_expansions，来源全部为 PT；15 条正常完成。全部仍标记 constant_synthetic，原报告可追溯。真实环境统计未混入这些结果。
- 审计确认：根若先被初始上界剪掉，即便展开/OPEN 限额为 0，也可正常耗尽 OPEN。这不是“触发限额却误报完成”。首轮新增测试对这个分支的预期过严，随后将限额测试改为无剪枝以实际触发边界，并单独保留根剪枝结束测试。无需改动搜索。
- 时间为协作式检查，不是硬实时中断；max_seconds 不包括 adapter 生成 PT 的时间，因此 PT、纯求解和二者总计分列。历史缺失的环境/Git 不以新值补造。

### 保存的证据

[审计配置、版本与源码指纹](../../outputs/baseline_v1.1/b4/audit.json) · [toy JSON](../../outputs/baseline_v1.1/b4/toy_runs.json) · [toy CSV](../../outputs/baseline_v1.1/b4/toy_metrics.csv) · [历史 JSON](../../outputs/baseline_v1.1/b4/legacy_runs.json) · [历史 CSV](../../outputs/baseline_v1.1/b4/legacy_metrics.csv) · [自动报告](../../outputs/baseline_v1.1/b4/report.md) · [完成/中止分栏图](../../outputs/baseline_v1.1/b4/legacy_status.png) · [专项 pytest](../../outputs/baseline_v1.1/b4/b4_pytest.txt) · [全量 pytest](../../outputs/baseline_v1.1/b4/full_pytest.txt) · [命令输出](../../outputs/baseline_v1.1/b4/audit_run.txt) · [原版与 B3 保留校验](../../outputs/baseline_v1.1/b4/preservation_audit.json)。

三个输入分别固化为 `static_input.npz`、`dynamic_suboptimal_input.npz`、`appendix_b_input.npz`，保存在上述 B4 目录；每条 toy 记录带矩阵归档指纹。B3 的 particles.npz、metadata.json、mass_audit.csv 均与上一轮 SHA-256 完全相同。

**本轮停在 B4。** 下一阶段 B5 尚未实施：冻结输入上的 ε/预算扫描、cProfile、峰值内存与基于热点的有限工程优化。B6 真实场景算法比较、其他三份用户数据包的导入与后续阶段仍待指令。
