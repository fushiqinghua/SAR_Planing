# Bay of Fundy 接入修复记录

**结论：按用户授权的 official_native_angle 口径完成接入；原地理方向严格校验仍未通过。**
这次修复的是接入与验收口径，不是 NOAA 原始角度的物理正确性。旧 blocked 记录未覆盖。

## 问题归因与下载核验

重新从 NOAA 官方 S3 下载了完整 gomofs.t00z.20250214.2ds.n005.nc（171414927 字节），全文件 SHA-256 与原 B1 下载清单一致：
`c2879d000da71de2509e5f5194130de8c063256dc9c784a443826474894a378e`。
15 个关键变量的原始数组字节与交付子集首时刻一致，覆盖 angle、经纬度、流速、静态及动态湿干掩膜。因此排除本地下载损坏、CF 解包和子集提取导致该矛盾；不据此宣称全部 13 个 parent 已重下。
文件角度约 32° 与地理网格方向约 25° 的冲突在上游原文件中已存在，具体历史原因仍未知。
同日官方 S3 目录完整列举 41 个条目（无分页遗漏），没有 regulargrid 产品。没有把同一份文件重新下载后冒充已获得修订数据。
本地配准与旋转形式与 [ROMS 官方 uv_rotate.F](https://github.com/myroms/roms/blob/develop/ROMS/Utility/uv_rotate.F) 一致：先将相邻两个原生面上的分量平均到 rho，再使用原文件 angle 转到 east/north。源码副本及原始下载/比对证据均在本目录。

## 授权后的改动

- 新增 `scripts/run_fundy_native.py`，保留全部原始节点值、旋转、时间、reader、质量及 SHA 检查；只把地理方向差异改为有限数值诊断，并强制保留未验证标签。
- 原 `run_additional_real.py` 的 2° 严格门槛及旧报告保持原样。原 forcing 字节、原规划目标和评价器均未改动。
- 新增 `tests/test_fundy_native_policy.py`：验证未认证标记和新旧检查只在授权点存在差异。
- 标签：`historical_real_native_angle_geography_unverified`；`physical_direction_unverified=true`；`original_strict_gate_passed=false`。

## 运行结果

新增测试 2 passed；全量 926 passed，0 failures/errors/skipped。
Leeway 只运行一次；N=500、seed=41、PIW-1、事故 UTC=2025-02-14T00:00Z、CST=09:00Z、T=55、q=.78、步长 37.04 s、格宽/扫宽 740.8 m。最大质量误差 5.55e-16。
全部 ID、绝对 UTC、cell_ids 和初始权重保留。该次各特殊质量桶均为零，无缺测退化事件。归档从 native 轨迹独立重建重放通过，不重跑 Leeway。
粒子 SHA-256：`3cb169401cc0c4a98306a2d3535f73e92e5cf31dc6db984eabcd9cc7d4ec9ad0`。
搜索接口 smoke 共 8 次：0 次正常完成、8 次明确预算中止；最终路径 J 重放最大误差 0。
Smoke 使用最多 100 扩展、3 秒、OPEN 20000，只验证接口与评分，不用于宣称 STDC 的真实场景性能提升。正式同预算重复实验尚未运行。
所有路径均 uncertified，不添加动态 paper_greedy 或预算中止搜索的 ε 最优声明。
保全检查：4696 个既有研究文件、654 个冻结 baseline 文件以及前轮 434 份归档条目未变。

## 文件与命令

粒子：`b3/bay_of_fundy/particles.npz`；完整配置/来源/标签：`metadata.json` 与 `b2/bay_of_fundy/forcing_audit.json`。
质量 CSV：`b3/bay_of_fundy/mass_audit.csv`；带明确限制的图：`fundy_particles_qualified.png`。
接口测试结果：`smoke/metrics.csv`、每次 command.json/stdout/stderr/result.json；源码快照在 B2/B3/smoke 目录。
首次单连接下载因 180 秒超时留下的文件不作为输入；分段下载重新组装并校验得到 verified_parent_n005.nc，只有该文件用于 parent 核验。
在 maritime-sar 下使用既有 offline_guard/src/scripts PYTHONPATH、单线程、UTF-8 和进程级 safe.directory 环境，入口命令如下（新输出目录必须独立准备，已有目录拒绝覆盖）：

```powershell
python -m pytest tests/test_fundy_native_policy.py -q -x -p no:cacheprovider
python -m pytest -q -x -p no:cacheprovider
python scripts/run_fundy_native.py b2 --run-dir outputs/stdc_v0_2/fundy_repair_20261124
python scripts/run_fundy_native.py b3 --run-dir outputs/stdc_v0_2/fundy_repair_20261124
python outputs/stdc_v0_2/fundy_repair_20261124/run_smoke.py
```
