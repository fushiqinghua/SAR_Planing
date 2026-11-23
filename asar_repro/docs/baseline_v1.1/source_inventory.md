# B1 历史风流来源与可得性

2026-11-23 对四组 Table I 任务进行核验。本地可核验的历史风流文件对为 **0/4**。20 项归档探测都完成了 DNS 解析，随后在 HTTPS 连接时报 `WinError 10013`。Lake Ontario 的实际获取命令在风索引和湖流对象列表两处也遇到同一错误，落盘气象、水动力数据共 0 字节。此次结果只反映当前机器的访问情况。[逐项来源清单](../../data/manifests/historical_sources.json) · [获取回执](../../outputs/baseline_v1.1/b1/lake_acquisition.json)

## 任务窗口

起点取事故时刻，搜索结束取 CST 加 `T × 扫宽（米）/ 20 m/s`。每海里按 1852 米换算。下表最后一列为本次查询采用的小时边界，左右各多留一个整点。使用其他采样间隔的产品需依据文件内有效时次重新核对。坐标来自 Table I 配置，顺序为经度、纬度。[任务配置](../../configs/stage7_scenarios.yaml)

| 场景及产品 | 事故 UTC | 搜索结束 UTC | 计划检查时段 UTC |
|---|---|---|---|
| Lake Ontario · HRRR / LOOFS | 2025-08-26 14:45 | 08-26 15:52:33.740 | 08-26 13:00 至 17:00 |
| Bay of Fundy · HRRR / GoMOFS | 2025-02-14 00:00 | 02-14 09:33:57.200 | 02-13 23:00 至 02-14 11:00 |
| Salish Sea · HRRR / CIOPS | 2025-08-24 00:00 | 08-24 12:41:14.560 | 08-23 23:00 至 08-24 14:00 |
| Arctic Ocean · GFS / ESPC-D-V02 | 2025-08-29 00:00 | 08-30 00:46:18.000 | 08-28 23:00 至 08-30 02:00 |

## 逐场景证据

- **Lake Ontario。** LKP 为 (−76.500, 44.210)，CSP 为 (−76.496, 44.215)。NCEI 的 LOOFS 目录列有 2025 年。GLERL 列出历史数据入口和 LAOFS 名称。NOAA 记录了旧版大湖 `glofs.*.fields.forecast` 整周期产品。本地分别探测 HRRR 的 AWS、Google 镜像、历史 OFS 桶的新旧路径和 NCEI THREDDS。样本获取选择 12Z 起报的 f01–f05，目标为 13–17 UTC。这是可复查的周期选择，原作者采用的周期未知。[HRRR 档案](https://registry.opendata.aws/noaa-hrrr-pds/) · [LOOFS 年目录](https://www.ncei.noaa.gov/thredds/catalog/model-loofs-files/catalog.html) · [GLERL 历史数据入口](https://www.glerl.noaa.gov/res/Programs/ipemf/glcfs_data_access.html) · [NOAA OFS 归档与旧命名](https://github.com/NOAA-Big-Data-Program/nodd-data-docs/blob/main/OFS/README.md)
- **Bay of Fundy。** NCEI GoMOFS 的 2025 年目录列有 02 月。事故日前一小时也在计划窗口内。待取得对应有效时次后，需在湾内 LKP、CSP 和任务区域的湿网格核对潮流覆盖。[GoMOFS 月目录](https://www.ncei.noaa.gov/thredds/catalog/model-gomofs-files/2025/catalog.html)
- **Salish Sea。** ECCC 文档公布 CIOPS-West 的 Salish Sea 500 米逐小时产品和 `today` 分发入口。此次对 2025-08-24 的尝试没有取得历史对象键或文件。狭窄水道的空间覆盖尚待核验。[ECCC CIOPS 数据说明](https://eccc-msc.github.io/open-data/msc-data/nwp_ciops/readme_ciops-datamart_en/)
- **Arctic Ocean / Hudson’s Bay。** HYCOM 的 2025 年目录提供 OPeNDAP、NetcdfSubset 服务，目录的变量清单含 `ssu`、`ssv`。已将该服务地址保存在清单中。若 Lake 和 Fundy 继续受阻，可在此服务中取覆盖跨日任务的局部水流子集，并与同窗 GFS 风场核对。实际返回的单位、时次、有效水面覆盖均待查。[ESPC-D-V02 年度服务](https://tds.hycom.org/thredds/catalogs/ESPC-D-V02_ice.html?dataset=ESPC-D-V02-ice-2025) · [GFS 档案](https://registry.opendata.aws/noaa-gfs-bdp-pds/)

工作区原有 Stage 7 粒子和常量配置属于 `constant_synthetic`。在可读的毕业设计目录与用户 Downloads 中检索了 NetCDF、GRIB 候选文件；找到的其他项目 2024 年数据和软件包测试样例与表中任务不匹配。当前终端未发现 AWS CLI，Python 未报告代理配置。本环境可通过 xarray 打开 NetCDF，未检测到用于此脚本 GRIB 解码的 cfgrib / ecCodes。实际历史数据的单位、时空覆盖、散列、缺测与掩膜仍为空。

## 重跑与验收

在 `SAR_Planing-v1.1/asar_repro` 下运行，沿用 B0 的解释器。输出到新的清单文件可保留本次已冻结的探测记录。

```powershell
$PY = 'C:\Users\35448\.conda\envs\maritime-sar\python.exe'
$env:PYTHONPATH = (Resolve-Path '.\src').Path
$env:PYTHONUSERBASE = Join-Path (Get-Location) '.python-user'
$env:PATH = (Join-Path (Split-Path $PY) 'Library\bin') + [IO.Path]::PathSeparator + $env:PATH
$env:PYTHONDONTWRITEBYTECODE = '1'
& $PY scripts/fetch_lake_b1.py
& $PY scripts/inventory_historical.py --output data/manifests/historical_sources_retry.json
& $PY -m pytest -q -p no:cacheprovider tests/test_b1_inventory.py
```

获取脚本按 HRRR 索引的字节范围保存两条 10 米风 GRIB2 消息，记录原始 URL、索引 SHA-256、字节区间和子集 SHA-256。LOOFS 查询实际对象列表，再选择小时文件组或整周期场文件。湖流样本下载总上限默认为 256 MiB，超出会在回执中报告。每次回执保存在 `data/raw/historical/lake_ontario/acquisition_*.json`。若已合法取得同产品的本地文件，可按 `<raw-dir>/<scenario>/wind`、`current` 分目录放置，向清单脚本传 `--raw-dir`。保留原始来源、起报周期及下载或裁切记录。

获取命令的退出码 2 表示该次获取未完成。清单命令的退出码 2 表示尚无可同时打开两类文件头的场景；退出码 0 表示至少有一对候选文件可供核查。要通过 B1，还须逐文件核对来源与指纹、10 米风和表层流的两个物理分量、单位、有效时间连续性，以及任务区域的有效水面覆盖。GRIB 需要可读取其网格和分量的解码器，或有可核对来源与转换记录的 NetCDF 子集。通过这些核查后才能进入 B2。
