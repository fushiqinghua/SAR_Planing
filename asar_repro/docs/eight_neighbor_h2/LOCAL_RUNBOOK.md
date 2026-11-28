# H2 新日期 forcing 执行与核验

本批沿用预注册的 Lake Ontario 和 Hudson Bay 日期、候补、seed 和物理模型。确认批提交 `972082c` 选定 `completion_J`，新方法锁绑定原方法与评分文件、确认批证据和本机环境。日期资格只使用源数据和读入结果。LKP 至原生积分尾帧全覆盖后才允许生成粒子。

在 `asar_repro` 使用原有 `maritime-sar` Python，保持现有 OpenDrift。默认输出 `outputs/eight_neighbor_h2_20261127/local_r1`，官方响应原字节放在 `data/raw/h2`。

```powershell
python scripts/prepare_eight_neighbor_h2.py plan
python scripts/prepare_eight_neighbor_h2.py lock-method
python scripts/prepare_eight_neighbor_h2.py acquire
python scripts/prepare_eight_neighbor_h2.py audit
python scripts/run_eight_neighbor_h2.py validate
python scripts/prepare_eight_neighbor_h2.py prepare
python scripts/run_eight_neighbor_h2.py freeze
python scripts/run_eight_neighbor_h2.py run --stage S30
python scripts/run_eight_neighbor_h2.py freeze-s30
python scripts/run_eight_neighbor_h2.py run --stage H30
python scripts/run_eight_neighbor_h2.py summarize
```

`acquire` 支持对单日期使用 `--block`，支持按 `--source noaa|hycom|both` 分开获取。NOAA 原始 GRIB 消息由响应范围和索引绑定，LOOFS 对象来自永久归档目录，HYCOM 保存固定经纬范围和 31 个逐小时有效时刻的官方子集。年度 HYCOM 数据未提供经独立核实的逐帧 cycle，因此只把逐帧 UTC 标为已验证。风流读取保留原生坐标、方向、湿干或缺测掩膜；Hudson 全部湿样本的冰浓度须为已知零。

`audit` 保留每次快照。传输失败、未知格式或本地字节变化会保留原因和证据。若明确判为不合格，只能在所有主日期均完成资格判断后用预声明的顺序候补。六个日期通过时写入 `date_lock.json`。持有该锁后才为 12 个固定 seed 各运行一次 Leeway。参考轨迹及求解不参与日期选择。已有通过核验的档案可重用，失败档案保留，seed 不重抽。

S30 的共同四邻接初始路线先做原离散和物理评分桥接，再将同一条路线交给两种邻接和覆盖模式。H30 计入复制、引导、补全、完整重放与归档时间，使用固定的 J-only 模式。正式任务串行新进程，5 个数值线程环境变量设为 1，最大 RSS 2 GiB。30 秒算法预算以外的进程余量单列。

汇总按 3 次重复、2 个 seed、日期三级聚合。结果 CSV 包含两种覆盖及同路线 J/Pd，生存曲线保持共同观测时钟。可用候选和有限预算结束只提供本次质量证据。模型使用几何覆盖代理与历史重建环境。
