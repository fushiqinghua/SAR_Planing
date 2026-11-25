# 270 个 rollout 候选的只读归因

原正式实验仅保存局部候选计数，没有逐候选路径。本诊断从封存的 72 次运行中读取每个局部阶段使用的扩展额度与进入该阶段时的 incumbent，用同一 BurstRollout 做无墙钟截止的确定性重建，并以新分析子类记录 _candidate；不重跑全局搜索、不改变生产实现。

生产源码 SHA 在重建前后与冻结协议一致；三个真实归档通过原 load_case 的 SHA/forcing 验收。265 个阶段的关键计数逐项一致，重建状态 passed。

- 270/270 候选与生成时 incumbent 完全同路径，严格 J 改善 0。
- 只包含 8 个 scene+完整路径：Lake 3、Hudson 2、Fundy 3；13 个 scene+incumbent+窗口+完整路径组合。
- 每个场景计数 90。J 浮点差最大分别为 0、3.55e-15、2.84e-14，来自不同累计路径；不构成数值改进。
- 261 个候选来自 8 步窗口、9 个来自 6 步窗口、0 个来自 4 步窗口。
- 132/165/150 个可调度窗口，实际每次只完成 3–5/2–4/3–4 个；所有已完成候选涉及的纯时间区间分别只有 4/3/4 个。
- 共启动 481 次窗口、完成 270 次；139 次外部 incumbent 改善触发重置，丢弃 6118 个已排队局部状态。重置可维持与新 incumbent 一致，但会反复从相近的最高机会窗口开始。
- 局部累计扩展 27444、完整下界调用 73680、cheap 下界调用 100001、beam 截断 25140。
- 多样性额外槽位累计仅保留 9 个状态，Lake 0、Hudson 0、Fundy 9。签名采用最大残留空间质量单元的 3×3 粗格与航向；它没有表示完整未来轨迹拦截差异。现日志不能将全部未保留事件确定归因为签名碰撞，不能杜撰碰撞比例。

270 是含重复的完成候选数，不是 270 条独立新路径。以上不能证明近全局最优；需结合父诊断的固定端点独立枚举，才能判断有限邻域的局部最优性。

Fundy: physical_direction_unverified=true。

复跑（从 asar_repro 根目录，使用既有 offline_guard/PYTHONPATH 环境，禁止生成 pyc）：

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& 'C:\Users\35448\.conda\envs\maritime-sar\python.exe' 'outputs/stdc_v0_2/rollout_limit_diagnosis_20261124/candidate_audit/analyze_candidates.py'
```

结果：summary.json、candidate_records.json、reconstructed_runs.json、phase_checks.json、stdout.txt、stderr.txt。这里只新增诊断文件；没有改动原目标、评价器、forcing、旧实验或源码。
