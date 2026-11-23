# B1 历史风流来源与可得性

**B1 已通过。四个 Table I 场景中，Lake Ontario 一组已在本地打开并核验，另外三组等待数据。** 用户手动下载的归档包含 5 份 HRRR 逐小时 f00 分析风与 5 份 LOOFS 18 UTC 循环的 nowcast 表层流，两者有效时间均为 2025-08-26 13–17 UTC。该组合用于事后环境重建，18 UTC 循环晚于 15:45 UTC 的 CST，原作者的起报周期仍未知。[当前四场景来源清单](../../data/manifests/historical_sources.json) · [逐文件本机验证](../../outputs/baseline_v1.1/b1/local/validation_local.json)

手动交付以前的 20 项线上探测均在 HTTPS 连接阶段返回 `WinError 10013`。当时的四场景清单与获取回执已单独保存。[初次探测快照](../../outputs/baseline_v1.1/b1/initial_sources.json) · [初次获取回执](../../outputs/baseline_v1.1/b1/lake_acquisition.json)

## 任务窗口

起点取事故时刻，搜索结束取 CST 加 `T × 扫宽（米）/ 20 m/s`。每海里按 1852 米换算。下表最后一列为本次查询采用的小时边界，左右各多留一个整点。使用其他采样间隔的产品需依据文件内有效时次重新核对。坐标来自 Table I 配置，顺序为经度、纬度。[任务配置](../../configs/stage7_scenarios.yaml)

| 场景及产品 | 事故 UTC | 搜索结束 UTC | 计划检查时段 UTC |
|---|---|---|---|
| Lake Ontario · HRRR / LOOFS | 2025-08-26 14:45 | 08-26 15:52:33.740 | 08-26 13:00 至 17:00 |
| Bay of Fundy · HRRR / GoMOFS | 2025-02-14 00:00 | 02-14 09:33:57.200 | 02-13 23:00 至 02-14 11:00 |
| Salish Sea · HRRR / CIOPS | 2025-08-24 00:00 | 08-24 12:41:14.560 | 08-23 23:00 至 08-24 14:00 |
| Arctic Ocean · GFS / ESPC-D-V02 | 2025-08-29 00:00 | 08-30 00:46:18.000 | 08-28 23:00 至 08-30 02:00 |

## 初次线上来源调查

- **Lake Ontario。** LKP 为 (−76.500, 44.210)，CSP 为 (−76.496, 44.215)。NCEI 的 LOOFS 目录列有 2025 年。GLERL 列出历史数据入口和 LAOFS 名称。NOAA 记录了旧版大湖 `glofs.*.fields.forecast` 整周期产品。本地分别探测 HRRR 的 AWS、Google 镜像、历史 OFS 桶的新旧路径和 NCEI THREDDS。样本获取选择 12Z 起报的 f01–f05，目标为 13–17 UTC。这是可复查的周期选择，原作者采用的周期未知。[HRRR 档案](https://registry.opendata.aws/noaa-hrrr-pds/) · [LOOFS 年目录](https://www.ncei.noaa.gov/thredds/catalog/model-loofs-files/catalog.html) · [GLERL 历史数据入口](https://www.glerl.noaa.gov/res/Programs/ipemf/glcfs_data_access.html) · [NOAA OFS 归档与旧命名](https://github.com/NOAA-Big-Data-Program/nodd-data-docs/blob/main/OFS/README.md)
- **Bay of Fundy。** NCEI GoMOFS 的 2025 年目录列有 02 月。事故日前一小时也在计划窗口内。待取得对应有效时次后，需在湾内 LKP、CSP 和任务区域的湿网格核对潮流覆盖。[GoMOFS 月目录](https://www.ncei.noaa.gov/thredds/catalog/model-gomofs-files/2025/catalog.html)
- **Salish Sea。** ECCC 文档公布 CIOPS-West 的 Salish Sea 500 米逐小时产品和 `today` 分发入口。此次对 2025-08-24 的尝试没有取得历史对象键或文件。狭窄水道的空间覆盖尚待核验。[ECCC CIOPS 数据说明](https://eccc-msc.github.io/open-data/msc-data/nwp_ciops/readme_ciops-datamart_en/)
- **Arctic Ocean / Hudson’s Bay。** HYCOM 的 2025 年目录提供 OPeNDAP、NetcdfSubset 服务，目录的变量清单含 `ssu`、`ssv`。已将该服务地址保存在清单中。若 Lake 和 Fundy 继续受阻，可在此服务中取覆盖跨日任务的局部水流子集，并与同窗 GFS 风场核对。实际返回的单位、时次、有效水面覆盖均待查。[ESPC-D-V02 年度服务](https://tds.hycom.org/thredds/catalogs/ESPC-D-V02_ice.html?dataset=ESPC-D-V02-ice-2025) · [GFS 档案](https://registry.opendata.aws/noaa-gfs-bdp-pds/)

## 手动交付的本地证据

ZIP 的 SHA-256 为 `72f7f4473fa81b15de09c1316d41f3b6596471a36c15e4539717ce1f5db0ae78`。包内校验表所列 26 个文件全部匹配，场景配置快照也与当前仓库逐字节一致。风场逐条核对 NOAA 索引、字节范围和消息 SHA-256。湖流五个完整 NetCDF 对应包内 NOAA 对象列表的键和长度。下载响应与获取时间取自随包回执，本地验证直接使用解压后的原始字节。[哈希复核输出](../../outputs/baseline_v1.1/b1/local/hashes.txt)

- **风场。** 10 条 GRIB2 消息均为 10 米 U/V，网格为 1799×1059 的 Lambert 等角圆锥投影，格距 3 km。本地独立解包所得全场最小值、最大值、均值、标准差与下载环境的 ecCodes 结果一致，LKP、CSP 的最近格点编号及分量值也一致。原始分量相对于模型网格，B2 需要验证到地理东、北方向的旋转。[NCEP 数据表示模板 5.0](https://www.nco.ncep.noaa.gov/pmb/docs/grib2/grib2_doc/grib2_temp5-0.shtml) · [NCEP 网格模板 3.30](https://www.nco.ncep.noaa.gov/pmb/docs/grib2/grib2_doc/grib2_temp3-30.shtml)
- **湖流。** NetCDF 的数值时间轴与字符时间戳逐文件一致。FVCOM 单元中心的 `u`、`v` 为地理东、北流速，单位 `meters s-1`。最浅 sigma 层索引为 0，sigma 约 −0.025。15 UTC 时，CSP 上层中心距水面约 0.442 m，东、北流速分别为 0.201452 和 0.013135 m/s。
- **有效水域。** LKP、CSP 五个时次均在湿单元内。17×17 任务格的 289 个中心在风场内；湖流原始三角网格覆盖其中 221 个湿中心，其余 68 个在网格外。该统计以格心取样，不判定域外点是陆地。B2 需保留域外状态，B3 需逐粒子核验水陆与质量。

## 重跑与验收

从 `SAR_Planing-v1.1/asar_repro` 运行。完整解压目录为 `data/raw/historical/ASAR_B1_LakeOntario_20250826/`。以下命令离线读取原始数据并更新 Lake Ontario 条目。

```powershell
$PY = 'C:\Users\35448\.conda\envs\maritime-sar\python.exe'
$env:PYTHONPATH = (Resolve-Path '.\src').Path
$env:PYTHONUSERBASE = Join-Path (Get-Location) '.python-user'
$env:PATH = (Join-Path (Split-Path $PY) 'Library\bin') + [IO.Path]::PathSeparator + $env:PATH
$env:PYTHONDONTWRITEBYTECODE = '1'
& $PY data/raw/historical/ASAR_B1_LakeOntario_20250826/scripts/verify_hashes.py
& $PY scripts/verify_lake_b1.py
& $PY -m pytest -q -p no:cacheprovider tests/test_b1_inventory.py tests/test_b1_package.py
```

在本机 `maritime-sar` 下，包内 `validate_b1.py` 因缺少 ecCodes 无法启动。仓库的 `verify_lake_b1.py` 使用 NumPy 解码本包实际使用的 simple packing，pyproj 复核格点，netCDF4 检查流场，逐时次对照随包参考结果。程序在全部核验通过后才写入清单。重新运行线上清单命令时，它也会核验标准目录中已交付的本地数据。旧 Stage 7 的 `constant_synthetic` 粒子属于独立实验。
