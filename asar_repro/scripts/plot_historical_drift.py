"""Static scientific figures for the historical particle archive."""

from collections import Counter

from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
import numpy as np

from asar_repro.historical_drift import utc_label
from asar_repro.opendrift_adapter import utc_datetime


def plot_drift(folder, grid, data, bundle, cfg):
    half_x, half_y = np.array([grid.graph.cols, grid.graph.rows]) * grid.width_m / 2
    x, y = np.meshgrid(
        np.linspace(-half_x - 300, half_x + 300, 161), np.linspace(-half_y - 300, half_y + 300, 161)
    )
    lon, lat = grid.projection.transform(x.ravel(), y.ravel(), direction="INVERSE")
    incident = data["raw_time_utc"][0]
    cst, end = data["time_utc"][[0, -1]]
    phases = [
        ("Incident", incident, data["raw_lon"][0], data["raw_lat"][0], data["raw_cell_ids"][0]),
        ("Search start", cst, data["lon"][0], data["lat"][0], data["cell_ids"][0]),
        ("Search end", end, data["lon"][-1], data["lat"][-1], data["cell_ids"][-1]),
    ]
    colors = dict(
        searchable="#005c76",
        outside="#bd481e",
        land="#a97411",
        inactive="#9a578c",
        unknown="#606060",
    )
    figure = Figure(figsize=(13, 4.8), layout="constrained")
    axes = figure.subplots(1, 3, sharex=True, sharey=True)
    for ax, (phase, time, plon, plat, cells) in zip(axes, phases):
        _, wet = bundle.current.probe(utc_datetime(utc_label(time)), lon, lat)
        ax.contourf(x, y, (wet == "ok").reshape(x.shape), levels=[0.5, 1.5], colors=["#ddecf3"])
        ax.add_patch(
            Rectangle((-half_x, -half_y), 2 * half_x, 2 * half_y, fill=False, color="#536472", lw=1)
        )
        px, py = grid.projection.transform(plon, plat)
        labels = np.full(len(cells), "searchable", dtype="U12")
        for name, cell in grid.special.items():
            labels[cells == cell] = name
        count = Counter(labels.tolist())
        for name in colors:
            mask = labels == name
            ax.scatter(px[mask], py[mask], c=colors[name], s=8, alpha=0.48, rasterized=True)
        ax.scatter(0, 0, marker="+", color="#ab240d", s=50)
        ax.text(28, 35, "CSP", color="#ab240d", fontsize=8)
        ax.set(
            title=f"{phase} · {utc_label(time)[11:-1]} UTC",
            xlabel="East of CSP (m)",
            aspect="equal",
        )
        ax.text(
            0.02,
            0.97,
            "· ".join(f"{n} {k}" for k, n in count.items()),
            transform=ax.transAxes,
            va="top",
            fontsize=8,
        )
    axes[0].set_ylabel("North of CSP (m)")
    figure.suptitle(
        f"Lake Ontario · HRRR + LOOFS · {cfg['object_key']} · {cfg['particles']} particles"
        "\nBlue shading shows where LOOFS supplies valid surface current"
    )
    figure.savefig(folder / "particles.png", dpi=150)

    figure = Figure(figsize=(9, 4.8), layout="constrained")
    axes = figure.subplots(1, 2, sharex=True, sharey=True)
    sx, sy = np.meshgrid(np.linspace(-half_x, half_x, 9), np.linspace(-half_y, half_y, 9))
    slon, slat = grid.projection.transform(sx.ravel(), sy.ravel(), direction="INVERSE")
    t = utc_datetime(utc_label(cst))
    _, wet = bundle.current.probe(t, lon, lat)
    for ax, field, title, scale, key, color in [
        (axes[0], bundle.wind, "10 m wind (HRRR)", 0.025, 5, "#18516b"),
        (axes[1], bundle.current, "Top-layer current (LOOFS)", 0.0011, 0.25, "#176e63"),
    ]:
        values, status = field.probe(t, slon, slat)
        valid = status == "ok"
        ax.contourf(x, y, (wet == "ok").reshape(x.shape), levels=[0.5, 1.5], colors=["#ddecf3"])
        arrows = ax.quiver(
            sx.ravel()[valid],
            sy.ravel()[valid],
            *values[valid].T,
            angles="xy",
            scale_units="xy",
            scale=scale,
            color=color,
            width=0.004,
        )
        ax.quiverkey(arrows, 0.65, 0.05, key, f"{key:g} m/s", labelpos="E")
        ax.scatter(0, 0, marker="+", color="#ab240d", s=40)
        ax.set(
            title=title,
            aspect="equal",
            xlabel="East of CSP (m)",
            ylim=(-half_y - 620, half_y + 300),
        )
    axes[0].set_ylabel("North of CSP (m)")
    figure.suptitle(f"Historical forcing at CST · {utc_label(cst)}")
    figure.savefig(folder / "forcing_snapshot.png", dpi=150)


def plot_time_coverage(folder, data, bundle):
    figure = Figure(figsize=(10, 5), layout="constrained")
    overview, detail = figure.subplots(2, 1)
    incident = data["raw_time_utc"][0]
    cst = data["time_utc"][0]

    def seconds(t, reference):
        return (t - reference) / np.timedelta64(1, "s")

    fields = [bundle.wind, bundle.current]
    for i, field in enumerate(fields):
        dates = np.array(
            [utc_label(np.datetime64(t.replace(tzinfo=None), "ns"))[:-1] for t in field.times],
            dtype="datetime64[ns]",
        )
        overview.plot(
            seconds(dates, incident) / 3600,
            np.full(len(dates), i),
            "o-",
            color=["#18516b", "#176e63"][i],
        )
    interval = seconds(data["time_utc"][[0, -1]], incident) / 3600
    overview.axvspan(0, interval[0], color="#c4d2dc", alpha=0.6, label="Pre-drift")
    overview.axvspan(*interval, color="#d78e66", alpha=0.55, label="Search")
    overview.set(
        yticks=[0, 1],
        yticklabels=["HRRR", "LOOFS"],
        xlabel="Hours from incident (UTC)",
        ylim=(-0.2, 1.5),
    )
    overview.legend(loc="upper left", ncol=2, frameon=False)
    native = data["raw_time_utc"][data["raw_time_utc"] >= cst]
    for i, ts in enumerate([native, data["time_utc"]]):
        detail.plot(
            seconds(ts, cst),
            np.full(len(ts), i),
            "|",
            markersize=13,
            color=["#18516b", "#bf5726"][i],
        )
    detail.set(
        yticks=[0, 1],
        yticklabels=["Leeway (30 s)", "Planning (9.26 s)"],
        xlabel="Seconds from CST",
        ylim=(-0.6, 1.6),
    )
    figure.suptitle("Forcing coverage and trajectory sampling")
    figure.savefig(folder / "time_coverage.png", dpi=150)
