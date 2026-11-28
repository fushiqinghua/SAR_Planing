# 进展感知前缀调度：三组同预算筛选

**结果：progress_prefix_development_screen_not_passed**。36/36 有效运行；每方法 3 次重复，算法预算各 30 s。
本批仅使用已见 H2 开发实例，不作为新天气独立验证。
每例取 J 中位代表的完整路线，Pd 不跨路线拼接。

## 核心比较：C0_PROGRESS 对 C0

| 实例 | C0 J | Progress J | J 改善 | Pd 变化（百分点） | 0.1% | 非退化 |
|---|---:|---:|---:|---:|---|---|
| lake_h2_d1_s3101 | 14.307066617 | 14.281396295 | +0.1794% | -0.1652 | True | True |
| lake_h2_d2_s3201 | 14.058508572 | 13.907239443 | +1.0760% | +0.5234 | True | True |
| hudson_h2_d1_s4101 | 28.448979882 | 28.492906300 | -0.1544% | -0.7694 | False | False |
| hudson_h2_d2_s4201 | 58.739707200 | 58.522087200 | +0.3705% | +0.5140 | True | True |

## 三组配对判定

| 配对 | 通过 | ≥0.1% | ≥0.5% | J 全部非退化 | Pd 护栏 |
|---|---|---:|---:|---|---|
| fixed_vs_control | False | 3/4 | 1/4 | False | True |
| progress_vs_control | False | 3/4 | 1/4 | False | False |
| progress_vs_fixed | False | 1/4 | 1/4 | False | False |

## 归因与边界

固定配额为同时重跑的机制对照，主结论仅来自进展感知与原 C0 的对照。
新增方法仅修改搜索前缀的展开顺序，未接入新的实时传感器或风流信息。
每次 30 秒预算计入算法内排序和候选重放。输入读取、独立重放、进程耗时与峰值 RSS 单列。
未通过不能删除不利实例或事后更改门槛。
明细见 comparison.csv、progress_diagnostics.csv、survival.csv 与 runs/。

[人工复核与边界](ANALYSIS.md) · [独立验证](independent_verification.json) · [图表](progress_comparison.png)
