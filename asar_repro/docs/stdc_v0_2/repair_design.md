# STDC 归因后的工程修复方案

本轮修复重复计算与重复状态扩展，保持 STDC 数学下界、原目标函数、运动输入、t=0 约定和冻结搜索预算不变。下界偏松是目前方法的局限，不将工程提速描述为已经解决弱下界或已经超过 baseline A^SAR。

## 1. 等价几何缓存

每个启发式实例固定 grid、q、motion 和 horizon。精确 k 步可达集及对应 q、1−q、q_max、粒子探测因子只依赖当前位置和相对 k，适合复用。公开入口保留输入校验，时间循环不再重复校验相同顶点。四连通矩形图无等待，远于最远顶点之后的精确可达集按奇偶交替；radius 消融在距离饱和后不再变化。

所有乘法、求和和 max 的顺序保留。特殊粒子 bin 因子始终为 1。缓存只读，不存储路径 belief 或按 `(depth,vertex)` 缓存 h。浮点几何数组使用 16 MiB LRU 上限，可达整数数组单独计量。新增独立旧实现参考测试要求不同模型、传感器、路径前缀的浮点结果逐位一致。

## 2. 完整状态 h 缓存

可选 `heuristic_cache_size=4096`。缓存键为 `(depth,vertex,belief.dtype,belief.shape,belief完整字节)`，不使用近似量化、容差或哈希值代替完整字节。仅缓存 h，g 不在缓存值内。单次搜索的启发式、运动、探测率和预算固定。

缓存命中不得改变 h、堆排序或节点计数。验证驱动器要求单独开启 h 缓存时的整个 SearchResult 与无缓存实现一致。条目驱逐只影响后续计算成本，不影响数学值。

## 3. 严格完整状态支配

可选 `exact_dominance=True`，默认关闭。若两个节点具有相同的完整状态键，任意同一合法后缀产生相同未来 belief 序列和新增目标代价。因此 g 较大或相等的节点可由 g 较小的节点支配。

`best_g` 保存完整状态遇到的最小累计 g。遇到严格较小 g 必须重新入队，不能仅使用 closed 集永久封闭；旧堆项在出队时按当前 best_g 判定过期。支配不依赖启发式可采纳性，因而也可以应用于 paper_greedy 的工程对照，但不会赋予 paper_greedy 动态 ε 保证。

适用前提是未来合法行动、目标代价、运动与探测只依赖完整 belief、位置、深度及单次固定配置。若将来加入转向代价、燃油、已访问约束或其他历史依赖，必须扩展状态键。严禁只按 `(depth,vertex)` 合并。

`max_open` 继续计数实际堆项，包含尚未弹出的过期项。过期出队耗时但不计有效扩展。支配表保留已遇状态，可能消耗额外内存；其规模不能从 OPEN 上限直接推断。统计分别记录状态条目、键载荷、缓存命中、支配删除、过期出队。载荷计数不包含 Python 对象开销且可能存在共享引用；实际内存比较使用独立进程峰值工作集。

## 4. 预先固定的八组对照

| variant | 内容 |
|---|---|
| paper_reference | 提交 4a01dee 的 search.py，原 paper_greedy |
| mass_reference | 提交 4a01dee 的 search.py，原 mass_lb |
| stdc_reference | 提交 4a01dee 的 search.py 与 stdc_heuristic.py |
| stdc_geometry | 新几何缓存，关闭 h 缓存与支配 |
| stdc_cache | 几何缓存 + 完整状态 h 缓存 |
| stdc_reuse | 几何缓存 + h 缓存 + 严格支配 |
| paper_reuse | paper_greedy + 相同 h 缓存与支配 |
| mass_reuse | mass_lb + 相同 h 缓存与支配 |

所有组采用冻结的 Lake Ontario 真实粒子、初始 PT、ε∈{1.10,1.04,1.00}、5000 扩展 / 20000 OPEN / 30 s。每组每 ε 独立进程重复三次，共 72 次；方法次序轮转。真实运行前核对原 forcing、粒子、metadata、协议与评价器 SHA，不重跑 Leeway，不替换合成输入。

paper/mass 的复用对照用于区分通用搜索优化与 STDC 特有收益。仅旧 STDC 的耗时降低不足以证明优于 baseline A^SAR。每条路径以同一冻结评分器独立回放 J、Pd、合法性并保留 incumbent 来源与预算中止原因。

## 5. 验证门槛及结论规则

依次执行新测试、完整历史测试、160 组随机小图逐前缀 Oracle、35 组小图搜索、两组 Lake Ontario smoke，最后完整对照。旧 490 次搜索保留，新开关单独和组合验证。历史测试或可采纳性断言失败必须记录 blocked 并停止，不放宽阈值或删掉失败结果。

报告依据观测结果自动生成。J 未改善时明确说明弱下界导致的有限预算路径质量问题尚未解决；若改善，只报告该冻结场景和具体 ε 的数值事实。时间重复不是独立场景样本，不声称统计显著或跨场景泛化。

可采纳模式仅在离散模型前提成立且搜索真正完成时保留条件性 ε 保证。预算中止一律 uncertified；paper_greedy 即使 completed 也不能认证动态 ε 界。原 baseline-v1.1、B7 原始数据和评价器保持不变；新代码及结果仅在研究分支和新目录中保存。

## 6. 调用方式

旧调用自动获得几何计算加速；为了保留旧搜索 reference，完整状态复用需要显式开启：

```python
reuse_stats = {}
result = search_asar(
    grid, **search_args, heuristic="stdc_lb", epsilon=1.1,
    initial_path=initial_pt,
    max_expansions=5000, max_open=20000, max_seconds=30,
    exact_dominance=True, heuristic_cache_size=4096,
    reuse_stats=reuse_stats,
)
```

在现有 maritime-sar 解释器、离线环境与正确 PYTHONPATH 下，为每轮使用新的输出目录：

```powershell
& $PY scripts/run_stdc_repair.py init --run-dir outputs/stdc_v0_2/<fresh-run>
foreach ($stageName in @('new_tests','full_tests','random_audit','small_search','lake_smoke','comparison')) {
    & $PY scripts/run_stdc_repair.py $stageName --run-dir outputs/stdc_v0_2/<fresh-run>
    if ($LASTEXITCODE -ne 0) { throw 'blocked: inspect the saved stage logs' }
}
& $PY scripts/report_stdc_repair.py --run-dir outputs/stdc_v0_2/<fresh-run>
```

首次修复验证 `repair_20261123` 在全量测试的临时目录 fixture 创建处因缺失父目录而中止，保留为 blocked；该用例未进入断言。只修正测试启动目录准备后，`repair_20261123_r2` 从新测试重新开始全部验证。未删除、跳过或弱化该历史用例；两个尝试分别保存日志。
