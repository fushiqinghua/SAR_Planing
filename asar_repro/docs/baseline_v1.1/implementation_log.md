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

## B1 · Table I 历史风流文件可得性

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
| [四场景来源清单](../../data/manifests/historical_sources.json) | `12448657F1C2829C48CF0538E8EBEF53F26C8EBF12D5012668221C188775E5C5` |
| [来源核验说明](source_inventory.md) | `A475EA81CCCDEEB62AAB085EB236ACB79608FE95F9BC00E9D959790B58FB7EA6` |
| [获取回执](../../outputs/baseline_v1.1/b1/lake_acquisition.json) | `7612D5D99B7A85F90AC022C95D31C33D681C68778B7D81FF4D729BDCB6E47401` |
| [清单命令输出](../../outputs/baseline_v1.1/b1/inventory.txt) | `8F55B405F5787082854E5567ADAFDDF6EA6FD56FCB53A626AD4A7A37A7BD498B` |
| [B1 pytest 输出](../../outputs/baseline_v1.1/b1/b1_pytest.txt) | `472BF8A255B3109F013735317AB25E5C93B5ACCA2245A56DFC7A1FC33E6E3D37` |
| [全量 pytest 输出](../../outputs/baseline_v1.1/b1/full_pytest.txt) | `B41B9CBE82653B8A47C4B6C68565D4F193516D784EFA422A5CCBDF847A35BFDA` |
