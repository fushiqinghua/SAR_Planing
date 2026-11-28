# P2/H3：新天气日期外推预注册（数据与运行未就绪）

方法锁：C0 = 冻结的 physical_refinement_diagnostic_v1，候选 = 冻结 physical_lazy_prefix_v1；两组仍采用原八邻接、heading_square、J-only、探测后剩余质量之和、每次30s、相同 S30 初始路线。方法源码、参数和 Git blob 见 h3_date_registry.json。不能根据本次日期结果选择算法/调整配额。

## H3 日期和种子（UTC LKP）

现有 H2 的 date_lock.json 确认六个 H2 主日期全部合格且 replacements={}；下面六日原先仅为 H2 预登记的 alternates，没有进入 H2 正式评分，故作为此次**预定首选**。日期级天气不完全独立，间隔约一周至数周；因此称新 forcing 日期迁移而非完全独立同分布海况。

| 场景 | 日期 | 两个 seeds | 原 H2 候补身份 |
|---|---|---|---|
| Lake Ontario | 2025-08-05 | 3401/3402 | lake_h2_alt1 |
| Lake Ontario | 2025-09-16 | 3501/3502 | lake_h2_alt2 |
| Lake Ontario | 2025-09-30 | 3601/3602 | lake_h2_alt3 |
| Hudson Bay | 2025-08-08 | 4401/4402 | hudson_h2_alt1 |
| Hudson Bay | 2025-09-19 | 4501/4502 | hudson_h2_alt2 |
| Hudson Bay | 2025-10-03 | 4601/4602 | hudson_h2_alt3 |

Lake LKP 同日14:45、CST同日15:45、截至 CST+453.74s；Hudson LKP当日00:00、CST次日00:00、截至 CST+2778s。

若且仅若**数据源缺失、时间空间不合格、海冰/模型适用性失败**，按提前登记的候补顺序替换：
Lake 2025-08-19 seeds 3701/3702，2025-10-07 seeds 3801/3802；Hudson 2025-08-29 seeds 4701/4702，2025-10-10 seeds 4801/4802。不得因为规划结果、粒子位置、域外比例、Pd 等替代。候补不足则 data_incomplete。

## 数据获取和资格（与 H2 相同产品）

Lake HRRR CONUS 10 m UGRD/VGRD 同日 13–17Z 的 f00，LOOFS 当日18Z nowcast 中有效时刻13–17Z 原生顶 sigma 层；Hudson GFS 0.25度 D−1 18Z cycle f003..f033，每3h，HYCOM ESPC-D-V02 原生 hourly ssu/ssv/sic，按 H2 固定 bbox，所有有效水样本 sic 为已知零。原始字节 sha、来源、cycle/valid UTC、时间/空间/掩膜方向、风流覆盖、特殊质量均须审计，并在任何路线评分前冻结最终六日期。每个 seed 只生成一次500粒子的 OpenDrift 档案，初始半径100m、q=0.78、地速20m/s；域外质量不得删或重归一化。

**当前没有验证上述新日期的数据一定可获取。** 原 H2 acquisition/reader 和 runner 被旧方法锁硬性绑定，不能直接改其日期常量复用；需要新建独立 H3 数据与执行入口并先通过针对性回归测试。历史 nowcast 在实时搜救中不保证已可用，因此本研究只证明历史重建条件下的性能。

## 正式协议（执行器未实现，不得作为已完成）

S30 12任务共360s；E30 12档案×C0/Lazy×3次共72任务2160s。算法预算上限2520s（42min），排除下载/漂移/准备/启动/独立评分。全部使用双物理重放、共同初始路线、相同粒子、相同时间和预算。按日期/seed/重复区块打乱两方法次序；全部原始失败结果留存。

逐 seed 三次 J 中位，逐日期取两 seed 改善中位；验收门槛见 P1_DECISIONS.md。完整汇报 J、对应 Pd、整段生存曲线、资源、RSS、异常、各地区中位/最坏和 0.5% 改善日期数。不能将重复运行当新的天气样本。
