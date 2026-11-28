# P2/H3 新天气日期验证

六个预注册主日期的历史 forcing 全部合格，候补使用数为 0。十二份粒子归档通过核验，S30 12/12 和 E30 72/72 均有效。E30 每个 seed 下的 C0 与 Lazy 共用粒子和 S30 路线，单次算法预算为 30 秒。

| 地区 | 2025 年 UTC 日期 | Lazy 相对 C0 的日期级 J 改善 |
|---|---|---:|
| Lake Ontario | 08-05 | +0.2260% |
| Lake Ontario | 09-16 | +0.1225% |
| Lake Ontario | 09-30 | +0.1010% |
| Hudson Bay | 08-08 | −0.0017% |
| Hudson Bay | 09-19 | 0.0000% |
| Hudson Bay | 10-03 | 0.0000% |

**跨日期 J 门槛未通过。** Lake Ontario 三日均达到 0.1%，Hudson Bay 三日均未达标。总计 3/6 达到 0.1%，预注册要求至少 4/6 且每个地区至少一天达标。全部十二个 seed 均通过终点 Pd 护栏，最大降幅为 0.4431 个百分点。C0 和 Lazy 的算法耗时中位数分别为 29.823 秒和 29.849 秒，峰值 RSS 的中位数分别为 316.84 MiB 和 407.12 MiB，Lazy 增加 **28.5%**。

专项测试 197 项、全量测试 1,866 项和 29 个子测试通过。数据指纹、评分器和冻结方法的版本以及全局最优认证状态见协议和交付复核。结论适用于这六个历史天气日期的预注册工程筛选。

- [最终报告](local_r1/reports/20261128T152733015237Z/REPORT.md) · [汇总 JSON](local_r1/reports/20261128T152733015237Z/summary.json) · [逐 seed CSV](local_r1/reports/20261128T152733015237Z/seeds.csv)
- [路线图](local_r1/reports/20261128T152733015237Z/paths.png) · [剩余质量曲线](local_r1/reports/20261128T152733015237Z/survival.png) · [资源图](local_r1/reports/20261128T152733015237Z/resources.png)
- [六日 forcing 资格](local_r1/qualification/20261128T144553898503Z.json) · [来源清单](local_r1/source_manifests) · [粒子指纹](local_r1/inputs_lock.json)
- [冻结协议](local_r1/protocol.json) · [S30 路线锁](local_r1/s30_lock.json) · [测试日志](local_r1/validation) · [84 次记录](local_r1/runs) · [交付复核](local_r1/commands/20_delivery_checks.json)
- [代码清单](local_r1/commands/21_code_inventory.json) · [本地复跑手册](../../docs/second_innovation_next/P2_H3_LOCAL_EXECUTION.md)

清单保留原始资料的本地路径、字节数和 SHA-256。源文件和粒子数组在本地实验归档中，从原始输入复跑时需按清单取得和核验这些文件。
