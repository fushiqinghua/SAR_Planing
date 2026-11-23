# 新增真实风流数据：B1 本机接入验收

**状态：passed（仅 B1 数据层）。新增场景的 B2 reader、B3 粒子与规划对照尚未执行。**

Lake Ontario 已在 B3/B7 使用真实风流。本轮对同一 ZIP 重验，确认 26 份包内交付文件指纹一致，未把它重复计为新增场景。结合“另外两个场景”及本地目录，额外核验 Hudsons Bay 与 Bay of Fundy；Salish Sea 不在本轮范围。

| 场景 | 本地交付 forcing | 有效 UTC | 任务窗口 UTC | 状态 |
|---|---|---|---|---|
| arctic_ocean | 11 风文件 / 3 流文件；风 11 帧 / 流 31 帧 | 2025-08-28T21:00:00+00:00 → 2025-08-30T03:00:00+00:00 | 2025-08-29T00:00:00+00:00 → 2025-08-30T00:46:18+00:00 | B1 verified；B2/B3 false |
| bay_of_fundy | 13 风文件 / 1 流文件；风 13 帧 / 流 13 帧 | 2025-02-13T23:00:00+00:00 → 2025-02-14T11:00:00+00:00 | 2025-02-14T00:00:00+00:00 → 2025-02-14T09:33:57.200000+00:00 | B1 verified；B2/B3 false |

每个新增包 39 份交付文件完成 SHA-256 复核。原始消息边界也与 .idx 字节范围和逐消息 SHA 对照；不是只检查文件头。风场全网格 min/max/mean/std、LKP/CSP 的索引和数值均与下载环境的独立 ecCodes 记录一致。HYCOM/GoMOFS 全部交付时次解码，验证变量、维度、单位、缺测、任务点和窗口覆盖。

## 数值事实、处理与局限

- Hudsons Bay 对应代码 arctic_ocean / alias hudsons_bay。GFS 风来自固定 2025-08-28 18 UTC 循环 f003–f033，3 小时间隔；它是地理东/北分量。HYCOM ssu/ssv 为水流，sic 是海冰比例；没有使用海冰漂移速度。
- HYCOM short + scale_factor 只解包一次，_FillValue=-30000 仍是掩膜。原经度 0–360 已转换为 −180–180 后核对任务点；不改写原 NetCDF。LKP/CSP 周围 2×2 邻域全部时次有效；有效水域 sic=0。这不替代将来沿真实粒子轨迹的检查。
- HYCOM 为官方 NCSS 原网格子集，不持有全球母文件哈希；年度聚合序列尚未逐帧核实原循环。读取 time 坐标，而非全局 time_origin/created_on。
- Bay of Fundy 风是 HRRR 网格方向 U/V；GoMOFS u_sur/v_sur 位于 ROMS 不同交错网格，为 xi/eta 分量。本轮只核验原数值，未把它们当作地理东/北流；B2 必须验证插值、对齐、旋转和静态/动态湿干掩膜。
- GoMOFS 交付为约 123 MB 的表层原变量提取与时间串接文件。13 个完整母文件只保存来源/指纹及下载环境的比较记录，本机没有母文件，因此 original_parent_files_reverified_locally=false。不能把下载环境记录写成本机独立重验。
- 两组均为历史环境重建；未证明作者相同循环、原粒子/人工 PT 或当时实时可得性。未新增任何 ε-最优或规划认证声明。

## 本机问题与修复

既有 maritime-sar 没有 ecCodes，GDAL 也缺少 GRIB 插件；本轮未安装、升级任何依赖。新增严格 NumPy GFS 解码器，仅接受本包的 GRIB2 3.0/4.0/5.3、无缺测位图、general group splitting 与一/二阶差分；其他格式明确报错。
首轮 HYCOM 坐标检查因 0–360 经度与负经度任务点不一致而 blocked，记录保留在 additional_b1_20261123。修复坐标标准化后，在新目录重新验收，并新增该回归用例。中间仅 Hudsons Bay 通过的记录保留在 additional_b1_20261123_verified；当前两组结果以本目录为准。

实现依据为 NOAA [模板 5.3](https://www.nco.ncep.noaa.gov/pmb/docs/grib2/grib2_doc/grib2_temp5-3.shtml)、[模板 7.3](https://www.nco.ncep.noaa.gov/pmb/docs/grib2/grib2_doc/grib2_temp7-3.shtml)；省略时区的时间单位按 [CF 4.4](https://cfconventions.org/Data/cf-conventions/cf-conventions-1.11/cf-conventions.html#time-coordinate) 解释为 UTC，并与包内 UTC 时次对照。

## 测试、文件和复跑

全量 pytest：248 passed，18.86 s；新增 14 项测试。全部原有 512 份跟踪文件与 B7 的 426 份冻结输入/证据保持不变。实际解释器：C:\Users\35448\.conda\envs\maritime-sar\python.exe；版本：{'numpy': '2.4.6', 'netCDF4': '1.7.5', 'pyproj': '3.7.2', 'opendrift': '1.14.12'}。

新增脚本：scripts/b1_gfs.py、scripts/b1_extra_currents.py、scripts/import_additional_b1.py、scripts/report_additional_b1.py；测试：tests/test_b1_additional.py；ZIP/校验表指纹：configs/b1_additional_packages.json。源码未改动搜索、启发式、评分、旧 reader 或原海上搜救仿真程序。

新增清单 data/manifests/historical_sources_additional_b1.json 保留旧清单的 Lake Ontario 和 Salish Sea 条目，仅加入两组本机 verified 条目。旧 data/manifests/historical_sources.json 是 B3/B7 冻结依赖，保持原字节；B2 扩展应显式选择新清单。

在 asar_repro 下使用现有解释器（将 NEW 换成不存在的输出目录名）：

```powershell
$PY='C:\Users\35448\.conda\envs\maritime-sar\python.exe'
$env:PYTHONPATH=(Resolve-Path 'scripts/offline_guard').Path+';'+(Resolve-Path 'src').Path
$env:PATH=(Join-Path (Split-Path $PY) 'Library\bin')+';'+$env:PATH
$env:PYTHONIOENCODING='utf-8'
$env:ASAR_OFFLINE='1'
$env:PROJ_NETWORK='OFF'
& $PY -m pytest -q
& $PY scripts/import_additional_b1.py --include-fundy --output-dir outputs/baseline_v1.1/NEW
```

交付 CSV：forcing_times_and_fingerprints.csv（68 条新增风/流时次记录）；图片：forcing_coverage.png；逐文件证据：arctic_ocean_validation.json、bay_of_fundy_validation.json、lake_ontario_recheck.json；测试：full_pytest.json；最终状态：acceptance.json。输出目录中的 SHA 清单保护新增代码、配置、清单、报告与证据。

当前停在 B1。下一阶段只需开展这两组新增场景的 B2：GFS 地理风采样、HYCOM 掩膜/海冰与时空插值、HRRR 旋转、GoMOFS ROMS 交错网格/方向/湿干处理；B2 通过后再进入 B3，保持现有 Lake Ontario 输入及评分协议不变。
