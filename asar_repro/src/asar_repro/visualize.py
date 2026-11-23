"""Stage 4 figures from recorded posterior masses on a common color scale."""

import matplotlib as mpl
import numpy as np
from matplotlib.figure import Figure


LABELS = {"asar": "A^SAR", "greedy": "邻居贪心", "serpentine": "动态蛇形"}
STYLE = {"font.family": "sans-serif",
         "font.sans-serif": ["Microsoft YaHei", "Noto Sans CJK SC", "SimHei", "DejaVu Sans"],
         "axes.unicode_minus": False, "savefig.facecolor": "white"}


def plot_frames(grid, config, paths, scores, vmax, filename):
    frames = config["frames"]
    with mpl.rc_context(STYLE):
        fig = Figure(figsize=(2.15 * len(frames) + 1.6, 8.1))
        axes = fig.subplots(3, len(frames), squeeze=False)
        fig.subplots_adjust(left=.13, right=.98, top=.83, bottom=.13, wspace=.12, hspace=.23)
        title = "静态目标" if config["motion"]["kind"] == "static" else "动态目标"
        fig.text(.035, .95, f"{title}的未探测概率与搜索路径", fontsize=19, weight="bold")
        fig.text(.035, .902, f'{config["source"]}   |   {grid.rows} × {grid.cols}   ·   '
                 f'T={config["budget"]}   ·   q={config["q"]:g}   ·   A^SAR ε={config["asar"]["epsilon"]:.2f}'
                 f'   ·   seed={config["seed"]}', fontsize=10)
        norm = mpl.colors.Normalize(vmin=0, vmax=vmax)
        for i, method in enumerate(LABELS):
            score = scores[method]
            path = np.array([grid.coordinates(v) for v in paths[method]])
            for j, t in enumerate(frames):
                ax = axes[i, j]
                im = ax.imshow(score.beliefs[t].reshape(grid.rows, grid.cols),
                               cmap="Blues", norm=norm, interpolation="nearest", origin="upper")
                ax.set(xticks=[], yticks=[])
                ax.set_xticks(np.arange(grid.cols + 1) - .5, minor=True)
                ax.set_yticks(np.arange(grid.rows + 1) - .5, minor=True)
                ax.grid(which="minor", color="#94a3b8", alpha=.25, linewidth=.45)
                ax.tick_params(which="minor", length=0)
                for spine in ax.spines.values():
                    spine.set_edgecolor("#9aaabc")
                ax.plot(path[:t+1, 1], path[:t+1, 0], color="#c0460f", lw=1.7)
                ax.plot(path[0, 1], path[0, 0], "o", ms=7, mfc="white", mec="#383838")
                ax.plot(path[t, 1], path[t, 0], "D", ms=3.7, mfc="#cd4412", mec="#60240b", mew=.5)
                ax.set_xlabel(f"M = {score.survival[t]:.3f}", fontsize=9, labelpad=1.0)
                if i == 0:
                    ax.set_title(f"t = {t}", fontsize=11)
            box = axes[i, 0].get_position()
            fig.text(.108, (box.y0 + box.y1)/2, f"{LABELS[method]}\nJ = {score.J:.3f}",
                     ha="right", va="center", fontsize=10, linespacing=1.6)
        bar = fig.colorbar(im, cax=fig.add_axes([.16, .056, .28, .013]), orientation="horizontal")
        bar.ax.tick_params(labelsize=8)
        fig.text(.16, .079, "单格未探测概率质量（两场景共用色标）", fontsize=9)
        fig.text(.52, .059, "○  起点      ◆  当前格      橙线  已执行路径", fontsize=10)
        fig.savefig(filename, dpi=160)


def plot_order(config, controls, reunion, filename):
    with mpl.rc_context(STYLE):
        fig = Figure(figsize=(9, 4.8))
        ax = fig.subplots()
        fig.subplots_adjust(left=.105, right=.97, bottom=.17, top=.76)
        fig.text(.055, .92, "相同访问次数，交换两段搜索的先后顺序", fontsize=17, weight="bold")
        fig.text(.055, .84, f'按论文思想重建 · 静态目标   |   T={config["budget"]}  ·  '
                 f'q={config["q"]:g}  ·  seed={config["seed"]}  ·  ε 不适用（给定路径）', fontsize=10)
        for key, label, color in [("east_first", "先向东往返", "#b44919"),
                                  ("north_first", "先向北往返", "#286188")]:
            score = controls[key]
            ax.step(range(len(score.survival)), score.survival, where="pre", color=color, lw=2,
                    label=f"{label}    J = {score.J:.3f}")
        ax.axvline(reunion, ls=":", color="#64748b")
        ax.text(reunion + .4, .96, "两段均完成，后续路径相同", fontsize=9, color="#485568")
        ax.set(xlabel="搜索步 t", ylabel="未探测总质量 M", xlim=(0, config["budget"]), ylim=(0, 1.03))
        ax.grid(axis="y", lw=.5, color="#d6dbe1")
        ax.legend(loc="lower left", frameon=False, fontsize=10)
        fig.savefig(filename, dpi=160)
