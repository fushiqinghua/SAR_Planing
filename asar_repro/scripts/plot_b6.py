"""Scientific B6 figures and a report with explicit environment and result boundaries."""

from matplotlib.figure import Figure
import numpy as np


def label(row):
    return row["algorithm"] + ("" if row["epsilon"] is None else f" eps={row['epsilon']:g}")


def generate(output, graph, args, times, cfg, rows, spec, env, clouds):
    colors = ["#444444", "#167a90", "#cd6127", "#7a57a0", "#318b62", "#a18325", "#a14d74"]
    width = cfg["cell_width_m"]
    extent = [-graph.cols*width/2, graph.cols*width/2, -graph.rows*width/2, graph.rows*width/2]
    prior = args["motion"].cell_mass(args["p"], 0)[:graph.size].reshape(graph.rows,graph.cols)
    def xy(path):
        rc = np.array([graph.coordinates(v) for v in path])
        return (rc[:,1]+.5-graph.cols/2)*width, (graph.rows/2-rc[:,0]-.5)*width
    fig = Figure(figsize=(13,9), layout="constrained")
    axes = fig.subplots(2,2,sharex=True,sharey=True)
    unique = [rows[0]] + [r for r in rows[1:] if r["search_completed"]]
    for ax in axes.flat:
        ax.imshow(prior,extent=extent,origin="upper",cmap="Blues",vmin=0,vmax=prior.max())
        ax.set(xlabel="East of CSP (m)",ylabel="North of CSP (m)",aspect="equal")
    for i,row in enumerate(unique):
        x,y = xy(row["path"])
        axes[0,0].plot(x,y,color=colors[i],lw=1.5,label=label(row))
        ax = list(axes.flat)[i+1]
        ax.plot(x,y,color=colors[i],lw=1.6)
        ax.quiver(x[:-1],y[:-1],np.diff(x),np.diff(y),angles="xy",scale_units="xy",scale=1,
                  color=colors[i],width=.004,alpha=.55)
        ax.plot(x[0],y[0],"o",mec="black",mfc="white",ms=7)
        ax.plot(x[-1],y[-1],"*",color=colors[i],ms=11)
        for t in (1,5,15,30,49):
            ax.annotate(str(t),(x[t],y[t]),fontsize=8,xytext=(3,3),textcoords="offset points")
        ax.set_title(label(row)+f"\nJ={row['J']:.6f}, Pd={row['Pd_T']:.6f}",fontsize=10)
    axes[0,0].legend(fontsize=8)
    axes[0,0].set_title("Distinct routes over CST prior mass\nFour aborted runs return the PT route",fontsize=10)
    fig.suptitle("Lake Ontario historical reconstruction | 49 legal moves | circles: start, stars: end\n"
                 "No discrete certificate obtained; PT also represents four aborted incumbents")
    fig.savefig(output/"paths.png",dpi=150)

    fig = Figure(figsize=(13,3.9),layout="constrained")
    axes = fig.subplots(1,4,sharex=True,sharey=True)
    masses = [args["motion"].cell_mass(args["p"], t) for t in spec["snapshot_steps"]]
    vmax = max(m[:graph.size].max() for m in masses)
    for ax,t,m in zip(axes,spec["snapshot_steps"],masses,strict=True):
        im=ax.imshow(m[:graph.size].reshape(graph.rows,graph.cols),extent=extent,cmap="Blues",vmin=0,vmax=vmax)
        ax.set(title=f"t={t}, {str(times[t])[11:23]} UTC\nspecial mass={m[graph.size:].sum():.3g}",xlabel="East of CSP (m)")
    axes[0].set_ylabel("North of CSP (m)")
    fig.colorbar(im,ax=list(axes),shrink=.7,label="Unconditional cell mass")
    fig.suptitle("Historical real forcing | Unobserved target prior, no detection conditioning or renormalization")
    fig.savefig(output/"probability_snapshots.png",dpi=150)

    fig=Figure(figsize=(12,4.6),layout="constrained")
    axes=fig.subplots(1,2,sharey=True)
    seconds=np.arange(len(times))*cfg["step_s"]
    for ax in axes:
        ax.plot(seconds,rows[0]["M_0_to_T"],color=colors[0],label="ParallelTrack",lw=2)
        ax.set(xlabel="Seconds from CST (t=0: no detection)",ylabel="Undetected mass M(t)",ylim=(0,1.02))
        ax.grid(alpha=.2)
    for i,row in enumerate(rows[1:],1):
        ax=axes[0] if row["search_completed"] else axes[1]
        ax.plot(seconds,row["M_0_to_T"],color=colors[i],ls="-" if row["search_completed"] else "--",
                label=label(row),lw=1.2)
    axes[0].set_title("Completed searches (uncertified) + PT")
    axes[1].set_title("Budget stops: all four incumbents equal PT")
    for ax in axes: ax.legend(fontsize=8)
    fig.savefig(output/"survival_curves.png",dpi=150)

    fig=Figure(figsize=(13,4.8),layout="constrained")
    axes=fig.subplots(1,3)
    names=["PT" if r["heuristic"] is None else
           ("paper" if r["heuristic"] == "paper_greedy" else "mass_lb") + f"\n{r['epsilon']:.2f}"
           for r in rows]
    xpos=np.arange(len(rows))
    for ax,metric,title in zip(axes,("total_wall_s","expanded","J"),("Planning + warm start (s)","Search expansions (PT: N/A)","J (hollow bars: aborted incumbent)"),strict=True):
        for i,row in enumerate(rows):
            value=row.get(metric)
            if value is not None:
                ax.bar(i,value,edgecolor=colors[i],color=colors[i] if row["search_status"]=="completed" else "white",
                       hatch="///" if row["search_status"]!="completed" else None)
        ax.set(xticks=xpos,xticklabels=names,title=title,xlabel="Method / epsilon (paper = paper_greedy)")
        ax.tick_params(axis="x",labelsize=8)
        ax.grid(axis="y",alpha=.2)
    axes[0].set_yscale("log")
    fig.suptitle("Same historical input | 5000 expansions / OPEN 20000 / 30 s\n"
                 "All stops: max_expansions; hollow J belongs to ParallelTrack, not a search improvement")
    fig.savefig(output/"runtime_expansions.png",dpi=150)

    fig=Figure(figsize=(12,8),layout="constrained")
    axes=fig.subplots(2,3,sharex=True,sharey=True)
    for i,(kind,cloud) in enumerate(clouds.items()):
        for j,(tag,x,y) in enumerate((("Incident",cloud["raw_x"][0],cloud["raw_y"][0]),
                                      ("CST",cloud["x"][0],cloud["y"][0]),("End",cloud["x"][-1],cloud["y"][-1]))):
            ax=axes[i,j]
            ax.scatter(x,y,s=5,alpha=.35,color="#167a90" if i==0 else "#b56c25")
            if j==1:
                ax.plot(cloud["raw_x"][:,::25],cloud["raw_y"][:,::25],lw=.4,alpha=.3,color="#555")
            ax.plot(0,0,"+",color="black")
            ax.set(title=kind+" | "+tag,xlabel="East of CSP (m)",ylabel="North of CSP (m)",aspect="equal")
    fig.suptitle("Environment INPUT contrast only | identical mission parameters\n"
                 "CST panels include 20 ID-spaced native trajectories; dots include all 500 positions")
    fig.savefig(output/"environment_inputs.png",dpi=150)

    lines=["# B6 · Lake Ontario 同数据基线对照", "", "状态：passed。范围为 B6，未进入后续阶段。", "",
           "B3 冻结的同一 500 粒子归档，T=49、q=.78、seed=41、17×17 格、格宽 185.2 m、步长 9.26 s。",
           "事故 2025-08-26 14:45 UTC；CST 15:45 UTC；搜索终点 15:52:33.740 UTC。起点为 CSP 格 144，第 0 帧不探测。",
           "环境标签 historical_real_forcing_allwater：HRRR f00 + LOOFS 18 UTC nowcast 的事后重建，采用全水域岸线策略，并保留特殊格质量。", "",
           "## 相同真实输入的结果", "",
           "| 方法 | ε | J | Pd(T) | M(T) | 搜索/构造秒 | PT初始解秒 | 展开 | 状态/原因 | incumbent | 离散认证 |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['algorithm']} | {row['epsilon']} | {row['J']:.10f} | {row['Pd_T']:.8f} | {row['M_T']:.8f} | {row['planner_wall_s']:.6f} | {row['warm_start_s']:.6f} | {row['expanded']} | {row['stop_reason'] or row['search_status']} | {row['incumbent_source']} | {row['discrete_model_certified']} |")
    lines += ["", "PT 为正常构造的基线，不计入搜索完成率。6 次搜索中 2 次完成、4 次展开限额中止；中止路线全部来自 PT。",
              "paper_greedy 的两条完成路线均未认证；mass_lb 虽有模型内条件下界，本轮均未完成，因此未获得证书。",
              "J 是 t=1..T 的剩余质量累积，越小越好；Pd(T) 越大越好。ε=1.04 的 J 更小而终点 Pd 略低，不能把两指标混同。",
              "每条路径重新调用统一 score_path 检查起点、T 步四邻接合法性与 J/Pd/M，并用独立 ID 布尔掩码再次重放；逐步质量包含 land/outside/inactive/unknown，未重归一化。",
              "所有实际中止为 max_expansions；没有真实时间超限或 watchdog 中止。完整停止状态仍逐条保存。",
              "PT 不具有搜索扩展计数，因此 expanded/generated/pruned/peak_open 为 null；正常构造 PT 不表示其最优。",
              "时间由本机 Python/Windows 新子进程测量，planner_wall_s 包含求解器内部初始解评分；warm_start_s 单列 PT 构造成本。total_wall_s 为二者之和，不含归档校验、运动对象构造、独立重放或作图。", "",
              "![路径与顺序](paths.png)", "", "![剩余质量](survival_curves.png)", "", "![效率与状态](runtime_expansions.png)", "",
              "## real / synthetic 环境输入对照", "",
              "本轮算法表只含 historical_real。旧 Stage 7 的 constant_synthetic 仅作输入对照，没有混入算法排名或修改旧结果。两个归档的任务参数、seed、N、UTC 与网格相同。",
              "旧常量风为 (4,0) m/s，流为 (0.15,0.05) m/s。下面历史统计来自 B2 的 LKP/CSP 两位置、四时刻抽样，不代表全湖或粒子加权平均。", "",
              "| 历史场 | 分量最小值 m/s | 分量均值 m/s | 分量最大值 m/s | 速率范围 m/s |",
              "|---|---|---|---|---|"]
    for name in ("wind","current"):
        stat=env["historical_real"][name+"_site_event_stats"]
        lines.append("| "+name+" | "+" | ".join(str(stat[k]) for k in ("east_north_min_m_s","east_north_mean_m_s","east_north_max_m_s","speed_range_m_s"))+" |")
    lines += ["", "environment_comparison.json 保存两个输入在 CST/终点的质心、距离分位数与有效定位质量；environment_mass.csv 保存全部 50 帧的特殊格质量。本次两输入四类特殊格均为 0，该事实不取消特殊格保留机制。",
              "![输入轨迹与位置对照](environment_inputs.png)", "", "![规划期间未观测先验](probability_snapshots.png)", "",
              "## 可验证事实与复现边界", "",
              "该实验是使用论文任务参数的真实历史环境重建。原作者精确模式运行 cycle、原始粒子、地图、手工 ParallelTrack 及真实完整实验未逐点复现。",
              "论文的 ε 保证、本地实现和本轮数值事实分别记录。本轮无任何 ε 最优证书；原动态 toy 反例继续保留，未用完成搜索替代可采纳性证明。",
              "J_over_PT 仅按本地动态 PT 归一化，不称为 percent of optimum；本轮未修改或重填原 Table II C++ / M1 Pro 秒数，也未将本地时间当作跨机器速度对照。",
              "可选 ACO_inspired 本轮未执行；没有 ACO_original 声明。", "",
              "## 产物与复跑", "",
              "run_manifest.json 保存原始风流 SHA、粒子/配置/代码指纹、机器与命令。metrics.csv/runs.json 保存结果，step_metrics.csv 保存 350 行逐步 UTC/访问格/质量/累积 J。",
              "b6_workers/ 保留每次搜索的请求参数和原始输出。输出目录存在 B6 结果时拒绝覆盖，复跑须指定新的 --output-dir。",
              "本轮已停止；后续阶段、其他场景导入及工程集成均未执行。"]
    (output/"comparison.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
