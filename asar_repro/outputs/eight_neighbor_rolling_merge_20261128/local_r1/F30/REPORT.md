# 精确状态合并与滚动规划：阶段结果

阶段：F30。有效性：complete。判定：rolling_merge_development_screen_not_passed。

四例均为已见开发数据。此报告只汇总完整原始记录；ANALYSIS.md 不会被覆盖。

| 对比 | 通过 | 达到 0.5% 的实例数 | J 无退化 | Pd 护栏 |
|---|---|---:|---|---|
| C0_M_vs_C0 | False | 0 | True | True |
| C1_M_vs_C1 | False | 0 | True | True |
| C1_M_vs_C0_M | False | 0 | False | True |
| C1_M_vs_C0 | False | 0 | False | True |

滚动候选继续条件：C1_M/C0_M 与 C1_M/C0 均通过原质量门槛。
仅通用合并对比改善不能归因为滚动净收益。内层 incumbent 时间仅作诊断，不作同质量加速证明。
