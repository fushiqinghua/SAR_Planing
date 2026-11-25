"""Assemble local diagnostic evidence; never edits frozen inputs/results/code."""
import json, hashlib, sys
from pathlib import Path
from datetime import datetime
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=ROOT/'outputs/stdc_v0_2/adaptive_20261124'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,o):p.write_text(json.dumps(o,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    c=read(HERE/'candidate_audit/summary.json');e=read(HERE/'exact_windows/summary.json');b=read(HERE/'bound_audit/bounds.json')
    large=read(HERE/'exact_windows/larger_summary.json') if (HERE/'exact_windows/larger_summary.json').exists() else None
    oldmanifest=read(OLD/'artifact_sha256.json')['files']
    changed=[p for p,s in oldmanifest.items() if not (OLD/p).is_file() or sha(OLD/p)!=s]
    assert not changed,changed
    save(HERE/'preservation.json',dict(status='passed',previous_adaptive_artifacts_checked=len(oldmanifest),changed=changed,
        production_sources_checked_by_each_audit=True,real_input_sha_checked_by_original_load_case=True,
        no_original_evaluator_forcing_or_baseline_writes=True))
    save(HERE/'exact_windows/command.json',dict(interpreter=sys.executable,cwd=str(ROOT),toy_seed=1041,archive_seed=41,
        commands=[[sys.executable,str(HERE/'exact_windows/audit_exact_windows.py')],
                  [sys.executable,'-u',str(HERE/'exact_windows/audit_larger_windows.py')]],
        environment=dict(PYTHONPATH='scripts/offline_guard;src;scripts',PYTHONDONTWRITEBYTECODE='1',
            ASAR_OFFLINE='1',PROJ_NETWORK='OFF',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1'),
        note='first redirected larger-window attempt was interrupted externally after no output; retained empty logs; no result inferred from it; second unbuffered attempt records diagnostic caps separately'))
    names={'lake_ontario':'Lake Ontario','arctic_ocean':'Hudsons Bay','bay_of_fundy':'Bay of Fundy'}
    lines=['# 270 个 rollout 候选零改善：机制诊断与下一步','',
        '日期：2026-11-24。仅新增诊断脚本与产物；原目标、评价器、forcing、粒子归档、生产搜索实现和旧正式结果均不修改。',
        '本报告区分确定性重建、有限邻域数值穷举、条件性下界和待验证方案；本次不是新的同预算性能比赛。','',
        '## 核心结论','',
        '270 次不是 270 条新路线：重建的候选全部等于生成时 incumbent。最终直接 STDC 路径在全部 4/6/8 步固定端点窗口内没有更小 J；这支持“短邻域局部稳定”，不能推出接近全局最优。',
        '下一步优先使用独立、可给出受限最优性状态的修复求解器寻找非局部改善见证，再据此设计更大的修复邻域；不应继续优先调短窗口 beam 宽度或叠加单粒子 DP。','',
        '## 270 的真实含义','',
        '原日志只存 complete_candidates 计数，未逐候选存路径。本次按封存的每阶段局部扩展额度和当时 incumbent 重建 72 次局部运行；265 个阶段的关键计数全部一致。墙钟截止被替换为已付出的精确扩展额度，不把重建当成新的独立实验。',
        '270/270 与当时 incumbent 完全同路径；去重只有 8 个场景+完整路径、13 个场景+incumbent+窗口组合。J 最大累计差 2.84e-14，远低于 1e-10 容差，未发现原评分器或候选接受逻辑错误。',
        '261 次来自 8 步窗口、9 次来自 6 步、0 次来自 4 步。局部扩展 27444、完整下界调用 73680、cheap 下界调用 100001、beam 丢弃 25140，多样性额外仅保留 9 个状态。',
        '139 次全局 incumbent 更新引起局部重置并丢弃 6118 个排队状态；重置保持正确性，但会重复优先尝试高度重叠窗口。','',
        '|场景|计数|唯一完整路径|产出候选的不同时间窗口|可调度窗口/每次实际完成|',
        '|---|---:|---:|---:|---|',
        '|Lake Ontario|90|3|4|132 / 3–5|','|Hudsons Bay|90|2|3|165 / 2–4|','|Bay of Fundy|90|3|4|150 / 3–4|','',
        '## 独立穷举：短邻域是否真无改善','',
        '新诊断先以 seed=1041 的 12 个 toy 案例验证独立逐粒子递推与原 score_path 的一致性。随后对每个场景最终 direct STDC/work/r0 路径，枚举所有4/6/8步固定端点替换，不使用beam、STDC/DP下界或启发式剪枝。所有最佳路线用原评分器重放。',
        '枚举数按窗口累计，含重复完整路径，不能当作独立样本。审计对象是最终直接 STDC 路径，不是原270次每个中途incumbent；因此不能声称原beam从未丢失过中途改进。','',
        '|场景|窗口数|枚举合法窗口路径|改善窗口|最终8步自由终点路径数|自由终点改善|','|---|---:|---:|---:|---:|---:|']
    for x in e['scenes']:
        lines.append(f"|{names[x['scene']]}|{x['windows']}|{x['enumerated_paths']}|{x['improving_windows']}|{x['free_terminal8_paths']}|{int(x['free_terminal8_best_J']<x['baseline_J']-1e-10)}|")
    lines+=['','447个固定端点窗口、211237条累计窗口路径均无J改善；最后8步自由终点同样无改善。仅增大beam或覆盖更多同类短窗口，无法突破这些最终incumbent。','',
        '## 更大窗口的有限诊断','',
        '补充长度10/12固定端点枚举，每场景90秒诊断额度。达到额度明确标记 budget_exceeded，未完成窗口不计作穷尽；这不是5秒正式比赛。第一次重定向启动未输出结果，被外部终止，其日志保留；以下只采用第二次有进度记录的运行。']
    if large:
        lines+=['','三个场景全部10步窗口已穷尽（40/51/46个），无改善。12步仅完成9/12/36个窗口，三个场景均触发90秒额度；不能把未完成部分视为无改善。已完成10/12步窗口累计枚举17225702条局部路径，仍为按窗口累计的非独立计数。']
        lines+=['','|场景|状态|已完成窗口|已枚举路径|改善窗口|最好J|','|---|---|---:|---:|---:|---:|']
        for x in large['scenes']:
            lines.append(f"|{names[x['scene']]}|{x['status']}|{x['windows']}|{x['enumerated_paths']}|{x['improving_windows']}|{x['best']['best_J']:.12f}|")
    lines+=['','## 尚无全局接近最优证据','',
        '|场景|当前可行J U|STDC根下界L|单粒子DP根下界|(U−L)/U|','|---|---:|---:|---:|---:|']
    for scene,x in b['scenes'].items():
        lines.append(f"|{names[scene]}|{x['U_best_direct_STDC']:.9f}|{x['root_stdc_lower_bound']:.9f}|{x['root_particle_dp_lower_bound']:.9f}|{100*x['uncertainty_fraction_of_U']:.2f}%|")
    lines+=['',
        '上述比例是尚未排除的不确定区间，不是预测可获得的收益，也不是当前真实最优差距。直接STDC的18次正式运行全部预算中止，且未保存可恢复所有frontier状态和min admissible f，无法事后补更紧全局证书。paper_greedy排序堆头不能冒充下界。',
        '单粒子DP允许每个粒子各自选择最理想路线，忽略所有粒子必须共享同一搜救路线：sum_i b_i min_path C_i <= min_path sum_i b_i C_i。压缩内存没有修复这一松弛。本次三个根的DP界都弱于STDC，但不能推出所有深度普遍支配。','',
        '## 为什么当前策略受限','',
        '1. 固定左右端点和完整后缀，把大尺度航向、目标簇顺序及终点都锁住；只对既有路线做局部形状修补。',
        '2. 窗口优先级来自一跳即时探测差，且非负机会直接求和，容易优先重叠长窗口；先穿过低概率区再捕获另一轨迹簇的动作容易被忽略。',
        '3. 多样性只用最大残余质量的3×3粗格及当前航向，不描述未来可拦截轨迹集合；实际仅9个额外状态。日志不足以量化签名碰撞比例。',
        '4. 小预算、重置、冷却及beam限制覆盖面。但独立无beam短窗口穷举仍失败，故不能把最终路线不改善主要归因于beam24太小。',
        '5. 旧 midpoint 已经做过自由终点、整段后缀beam；简单改回这种做法会重复旧路线。需要独立修复求解器先判断是否存在可行改善。','',
        '## 优先下一步：独立修复Oracle，然后再做实用算法','',
        'A. 建同一冻结粒子模型的时空MILP诊断。位置 x[t,v]为二元，每步唯一且4连通；从较晚前缀起释放终点并联合优化全部后缀，随后逐步释放更早前缀、扩大走廊。原incumbent必须始终在可行集合中。',
        '逐粒子权重 w[i,t] = w[i,t−1] − q[c_i(t)] z[i,t]；z = w[i,t−1] x[t,c_i(t)]。用 0<=z<=w_prev、z<=p_i*x、z>=w_prev−p_i*(1−x) 精确表示二元乘积。特殊bin固定无检测，t=0不检测。目标仍是sum_{t=1..T,i}w[i,t]，没有增加Pd约束或改权重。',
        '先做q=0/1、重复探测、动态轨迹、域外质量、t=0及toy全Oracle核验。任何可行结果都用原score_path重放；求解器optimal仅指当前受限子问题及数值容差，受限模型的dual bound不能当成全问题下界。',
        'SciPy 1.17的milp已提供时间/节点上限、mip_dual_bound、mip_gap与状态；可先用现有环境，不需安装或升级依赖。技术依据：[SciPy官方文档](https://docs.scipy.org/doc/scipy-1.17.0/reference/generated/scipy.optimize.milp.html)。这只是建议，尚未实现/验证本任务的MILP。',
        'B. 若找到更低J的合法路径，提取首次分叉时刻、无检测转移时长、改变的目标簇顺序及需要重做的后缀长度。由此设计事件导向的大邻域修复：围绕未来残余轨迹质量的时空交会点提出多个不同簇顺序，允许暂时较差的部分路线，联合完成后缀后才按完整J接受。避免把同一个热点的细微航向变化当成实质多样性。',
        '大邻域重规划的框架已有路径规划文献；这里是针对本模型的工程研究假设，不宣称新颖性或保证提升。参照：[IJCAI 2021原论文页面](https://ijcai.org/proceedings/2021/568)，其多智能体任务与本SAR目标不同，不能直接移植收益结论。',
        'C. 诊断先给各场景固定300秒探索预算，单列状态和受限gap；它不与5秒生产结果混比。找到改善见证后，再做5/15/30秒端到端同墙钟对照，计入构建、seed、求解与重放。MILP节点数不等同A*扩展数。不得把诊断发现的最优路径免费喂给正式方法。',
        '验收：每条路径合法、原评分一致；分别计J改善、Pd变化、J/Pd同时改善和时间/内存。若独立求解器找到改善但新算法找不到，问题在搜索；若受限求解器完成无改善，仅扩大邻域诊断，不能宣传全局最优；若超时无改善，结论仍未知。','',
        '## J与Pd的边界','',
        'M0=1时，J = T − sum_{t=1..T}(T−t+1) ΔPd_t，而 Pd_T = sum_t ΔPd_t。原目标更奖励早发现，所以J降低不保证最终Pd提高。保持J为唯一接受目标、Pd独立评估；不偷偷添加Pd约束或把等J更高Pd作为新次级目标。','',
        '另按逐粒子所有几何可达机会同时检测构造乐观Pd上界：Lake≈100%、Hudson≈100%、Fundy≈99.9999979%。三场景完全没有可达检测机会的粒子质量均为0；这排除了“Fundy的低Pd全部来自粒子从CSP绝对不可达”的解释，但不能说明这些机会能被同一条连续路径同时利用。当前Pd距该极松上界10.2636/9.1417/58.4135个百分点，不是可实现增益。180条已存路径的实际检测次数及独立Pd重算均通过检查，详见bound_audit/pd_upper.json。','',
        '## 交付与限制','',
        f"上一轮 {len(oldmanifest)} 份正式/验证产物SHA逐一复核不变。新增仅位于本诊断目录。源码和真实输入SHA在各审计前后验证；未运行OpenDrift、未修改forcing、未运行新的正式同预算对照。本轮没有生产代码修改，因此不重跑此前1114项全量测试；新增诊断通过12个toy枚举交叉检查、265次阶段重建检查及3个根界检查。",
        'Fundy始终 physical_direction_unverified=true；所有模型仍沿用既有all-water碰撞近似。任何局部诊断或预算中止均不标记全局epsilon认证。',
        '数据：candidate_audit/summary.json、candidate_records.json；exact_windows/summary.json、各场景JSON和larger_summary.json；bound_audit/bounds.json。命令与stdout/stderr在对应子目录，第一轮更大窗口中止保留而不隐去。']
    (HERE/'diagnosis_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    save(HERE/'evidence_summary.json',dict(candidates=c,short_windows=e,large_windows=large,
        root_bounds={s:{k:x[k] for k in ('U_best_direct_STDC','L_root_max','uncertainty_fraction_of_U')} for s,x in b['scenes'].items()},
        conclusions=['270 reconstructed candidates all equal contemporaneous incumbent','final direct routes locally stable in tested short neighborhoods','global near-optimality not established'],
        model_changed=False,production_code_changed=False,physical_direction_unverified=['bay_of_fundy']))
    save(HERE/'artifact_sha256.json',dict(files={str(p.relative_to(HERE)).replace('\\','/'):sha(p) for p in HERE.rglob('*') if p.is_file() and p!=HERE/'artifact_sha256.json'}))
    print('report assembled; previous artifacts preserved',len(oldmanifest),flush=True)

if __name__=='__main__':main()
