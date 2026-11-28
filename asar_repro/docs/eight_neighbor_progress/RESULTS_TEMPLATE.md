# P30 本地结果分析模板（用户执行后填写）

## 1. 冻结身份与验证
- 分支、源码 commit、protocol.json sha256、Python/包版本、四个固定 H2 输入及原 S30 路线。
- toy/独立 Oracle 测试、全量 pytest：通过 / 失败 / 跳过。
- 36/36 任务完成、预算内、无 watchdog；原模型与独立回放一致。

## 2. 质量主表
依照 instance_comparison.csv 列出 C0/C0_PREFIX/C0_PROGRESS 三方法的每例 J/Pd 以及三组相对比较。主判断为 progress_vs_control；原固定配额屏幕失败仍保留。

## 3. 机制解释
从 progress_diagnostics.csv 汇总每例三次的首次 search 改善、激活次数、开启时刻、保留早中段次数、尾段占比。尤其检查 Hudson 4101 是否受原先晚完成瓶颈保护。记录补全次数、主搜索终端、guide 与 transition 开销。

## 4. 时间与内存
同质量目标时间若没有预注册，则仅报告 incumbent 历史与算法耗时为诊断值，不宣称同质量加速。报告最大和中位 RSS、展开/生成/开放集规模。

## 5. 决策
按照 DECISIONS.md 的 0.1% 门槛、两地区胜出、J 不退化、Pd 护栏分别核对，不通过时不调换指标或剔除实例。说明后续是否准备新 forcing 独立日期验证。
