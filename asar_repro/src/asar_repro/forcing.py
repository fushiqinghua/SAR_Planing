"""Strict surface velocity sampling for CF fixtures and Lake Ontario archives."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import json
import re

from netCDF4 import Dataset, num2date
import numpy as np
from pyproj import Proj
from shapely import STRtree, points as shapely_points, polygons

from .hrrr import f00_wind, geographic_wind, require
from .opendrift_adapter import utc_datetime
from .scenarios import digest


VARIABLES = {
    "wind": ("x_wind", "y_wind"),
    "current": ("x_sea_water_velocity", "y_sea_water_velocity"),
}
CF_NAMES = {
    "wind": ("eastward_wind", "northward_wind"),
    "current": ("eastward_sea_water_velocity", "northward_sea_water_velocity"),
}


def numeric(var):
    return np.ma.asarray(var, dtype=float).filled(np.nan)


def longitude(lon):
    return (lon + 180) % 360 - 180


def dates(var):
    units = getattr(var, "units", "")
    offset_in_units = re.search(r"(?:Z|UTC|[+-]\d\d:?\d\d)$", units)
    require(
        getattr(var, "time_zone", None) == "UTC" or offset_in_units,
        "time coordinate must explicitly specify UTC or its offset",
    )
    require(
        getattr(var, "calendar", "standard") in {"standard", "gregorian", "proleptic_gregorian"},
        "expected Gregorian calendar",
    )
    values = numeric(var[:])
    require(values.ndim == 1 and np.isfinite(values).all(), "invalid time coordinate")
    return tuple(
        datetime.fromisoformat(t.isoformat()).replace(tzinfo=timezone.utc)
        for t in num2date(values, units, calendar=getattr(var, "calendar", "standard"))
    )


def component(var, name, dims, index):
    require(
        getattr(var, "standard_name", "").lower() == name and var.dimensions == dims,
        f"invalid {name} variable mapping or dimensions",
    )
    units = getattr(var, "units", "")
    scale = {"m/s": 1, "m s-1": 1, "m s**-1": 1, "meters s-1": 1, "cm/s": 0.01, "cm s-1": 0.01}
    require(units in scale, f"unsupported velocity units for {name}: {units!r}")
    return numeric(var[index]) * scale[units]


def increasing_axis(axis, name):
    require(
        axis.ndim == 1 and axis.size >= 2 and np.isfinite(axis).all() and (np.diff(axis) > 0).all(),
        f"{name} must be a strictly increasing axis",
    )


class Rectilinear:
    def __init__(self, x, y, projection=None):
        increasing_axis(x, "x")
        increasing_axis(y, "y")
        self.x, self.y, self.projection = x, y, projection

    def locate(self, lon, lat):
        if self.projection is None:
            center = (self.x[0] + self.x[-1]) / 2
            x, y = center + longitude(lon - center), lat
        else:
            x, y = self.projection(lon, lat)
        inside = (x >= self.x[0]) & (x <= self.x[-1]) & (y >= self.y[0]) & (y <= self.y[-1])
        i = np.clip(np.searchsorted(self.x, x) - 1, 0, len(self.x) - 2)
        j = np.clip(np.searchsorted(self.y, y) - 1, 0, len(self.y) - 2)
        # Avoid using NaN or unbounded coordinates to compute interpolation weights.
        a = np.where(inside, (x - self.x[i]) / (self.x[i + 1] - self.x[i]), 0)
        b = np.where(inside, (y - self.y[j]) / (self.y[j + 1] - self.y[j]), 0)
        return i, j, a, b, inside

    def sample(self, values, location):
        i, j, a, b, inside = location
        corners = values[np.stack((j, j, j + 1, j + 1)), np.stack((i, i + 1, i, i + 1))]
        weights = np.stack(((1 - a) * (1 - b), a * (1 - b), (1 - a) * b, a * b))
        uv = np.sum(np.where(weights[..., None] > 0, corners, 0) * weights[..., None], axis=0)
        status = np.where(inside, "ok", "outside_grid")
        return uv, status


class FaceMesh:
    def __init__(self, xy, connectivity, projection):
        self.projection = projection
        self.tree = STRtree(polygons(xy[connectivity]))
        self.face_count = len(connectivity)

    def locate(self, lon, lat):
        x, y = self.projection(lon, lat)
        point_ids, face_ids = self.tree.query(shapely_points(x, y), predicate="intersects")
        face = np.full(len(lon), self.face_count, dtype=int)
        # Deterministic shared-edge policy. Use the lowest native element ID.
        np.minimum.at(face, point_ids, face_ids)
        return face

    def sample(self, values, face):
        valid = face < self.face_count
        index = np.where(valid, face, 0)
        status = np.where(valid, np.where(values[index, 2] == 1, "ok", "dry"), "outside_mesh")
        return values[index, :2], status


@dataclass
class SurfaceField:
    role: str
    times: tuple
    grid: Rectilinear | FaceMesh
    values: np.ndarray
    sources: list
    metadata: dict
    max_gap_s: float = 3600

    def __post_init__(self):
        self.seconds = np.array([utc_datetime(t).timestamp() for t in self.times])
        increasing_axis(self.seconds, "valid UTC time")
        require(
            np.isfinite(self.max_gap_s)
            and self.max_gap_s > 0
            and np.max(np.diff(self.seconds)) <= self.max_gap_s,
            "forcing has an excessive time gap",
        )
        require(len(self.values) == len(self.times), "values/time length mismatch")

    def probe(self, time, lon, lat):
        """Return m/s east/north and per-point status. Invalid vectors are NaN."""
        lon, lat = np.broadcast_arrays(
            np.atleast_1d(np.asarray(lon, dtype=float)), np.atleast_1d(np.asarray(lat, dtype=float))
        )
        require(lon.ndim == 1, "query positions must be scalars or 1D")
        now = utc_datetime(time).timestamp()
        uv = np.full((len(lon), 2), np.nan)
        status = np.full(len(lon), "outside_time", dtype="U24")
        if not self.seconds[0] <= now <= self.seconds[-1]:
            return uv, status
        valid = np.isfinite(lon) & np.isfinite(lat) & (np.abs(lat) <= 90)
        status[:] = "invalid_position"
        if not valid.any():
            return uv, status
        index = int(np.searchsorted(self.seconds, now))
        lon, lat = longitude(lon[valid]), lat[valid]
        location = self.grid.locate(lon, lat)
        values, state = self.grid.sample(self.values[index], location)
        if now != self.seconds[index]:
            earlier, prev = self.grid.sample(self.values[index - 1], location)
            ratio = (now - self.seconds[index - 1]) / (
                self.seconds[index] - self.seconds[index - 1]
            )
            values = (1 - ratio) * earlier + ratio * values
            state = np.where(prev == "ok", state, prev)
        if self.metadata.get("vector_basis") == "grid_relative":
            values = geographic_wind(self.grid.projection, lon, lat, values)
        state = np.where(
            (state == "ok") & ~np.isfinite(values).all(axis=1), "missing_component", state
        )
        uv[valid] = np.where((state == "ok")[:, None], values, np.nan)
        status[valid] = state
        return uv, status

    def sample(self, time, lon, lat):
        uv, status = self.probe(time, lon, lat)
        require(
            np.all(status == "ok"),
            f"{self.role} unavailable: {np.unique(status[status!='ok']).tolist()}",
        )
        return uv


@dataclass
class HistoricalForcing:
    wind: SurfaceField
    current: SurfaceField
    window: tuple
    forcing_kind: str
    shoreline_policy: str = "allwater"

    def __post_init__(self):
        require(
            self.forcing_kind in {"synthetic_cf", "historical_real"}, "unsupported forcing kind"
        )
        start, end = map(utc_datetime, self.window)
        require(start <= end, "invalid UTC window")
        for field in (self.wind, self.current):
            require(
                field.times[0] <= start <= end <= field.times[-1],
                f"{field.role} lacks required UTC coverage",
            )
            if self.forcing_kind == "historical_real":
                require(
                    field.sources
                    and all(
                        re.fullmatch(r"[0-9a-f]{64}", s.get("sha256") or "") for s in field.sources
                    ),
                    "missing historical source SHA-256",
                )


def load_cf_surface(path, role, variable_names=None, max_gap_s=3600):
    """Read explicitly synthetic geographic CF surface input with decoded CF masks."""
    variable_names = CF_NAMES[role] if variable_names is None else variable_names
    with Dataset("cf.nc", memory=Path(path).read_bytes()) as ds:
        require(
            getattr(ds, "forcing_kind", None) == "synthetic_cf",
            "CF fixture must declare synthetic_cf",
        )
        require(
            set(variable_names) | {"lon", "lat", "time"} <= ds.variables.keys(),
            "missing CF coordinate or velocity variable",
        )
        for actual, native in (("lat", "degrees_north"), ("lon", "degrees_east")):
            require(
                getattr(ds[actual], "units", None) == native and ds[actual].dimensions == (actual,),
                f"invalid CF {actual} coordinate",
            )
        times = dates(ds["time"])
        lat = numeric(ds["lat"][:])
        lon = np.rad2deg(np.unwrap(np.deg2rad(numeric(ds["lon"][:]))))
        require(
            lat.size >= 2 and lon.size >= 2,
            "CF horizontal grid requires at least two points per axis",
        )
        uv = np.stack(
            [
                component(ds[v], n, ("time", "lat", "lon"), slice(None))
                for v, n in zip(variable_names, CF_NAMES[role], strict=True)
            ],
            axis=-1,
        )
    if lon[0] > lon[-1]:
        lon, uv = lon[::-1], uv[:, :, ::-1]
    if lat[0] > lat[-1]:
        lat, uv = lat[::-1], uv[:, ::-1]
    require(lon[-1] - lon[0] < 360 and np.max(np.abs(lat)) <= 90, "invalid CF geographic bounds")
    return SurfaceField(
        role,
        times,
        Rectilinear(lon, lat),
        uv,
        [],
        {"vector_basis": "geographic_east_north", "native_variables": list(variable_names)},
        max_gap_s,
    )


def _archived_bytes(root, row):
    # Validate exactly the bytes passed to the decoder.
    data = (root / row["local_path"]).read_bytes()
    require(
        row.get("sha256") == hashlib.sha256(data).hexdigest(),
        f"historical source SHA-256 mismatch: {row['local_path']}",
    )
    return data


def _wind(root, files):
    times, fields = [], []
    grid = None
    for row in files:
        time, key, proj, x, y, uv = f00_wind(_archived_bytes(root, row))
        require(grid is None or grid == key, "HRRR grid changed across valid times")
        require(
            time == utc_datetime(row["valid_utc"]) == utc_datetime(row["run_cycle_utc"]),
            "HRRR valid UTC does not match manifest",
        )
        grid = key
        times.append(time)
        fields.append(uv)
    return SurfaceField(
        "wind",
        tuple(times),
        Rectilinear(x, y, proj),
        np.stack(fields),
        files,
        {
            "vector_basis": "grid_relative",
            "native_variables": ["UGRD", "VGRD"],
            "height_m": 10,
            "spatial_method": "bilinear in native Lambert grid, then rotate at query",
        },
    )


def _current(root, files):
    times, fields, depth = [], [], []
    xy = None
    for row in files:
        with Dataset("loofs.nc", memory=_archived_bytes(root, row)) as ds:
            (time,) = dates(ds["time"])
            require(
                time == utc_datetime(row["valid_utc"])
                and ds.title == "LOOFS"
                and ds.source.startswith("FVCOM"),
                "LOOFS identity or valid UTC differs",
            )
            coords = np.column_stack((numeric(ds["x"][:]), numeric(ds["y"][:])))
            faces = np.ma.asarray(ds["nv"][:])
            require(
                faces.shape[0] == 3
                and not np.ma.getmaskarray(faces).any()
                and faces.min() >= 1
                and faces.max() <= len(coords),
                "invalid LOOFS face connectivity",
            )
            tri = np.asarray(faces.T, dtype=int) - 1
            if xy is None:
                xy, connectivity = coords, tri
                proj = Proj(ds.CoordinateProjection)
                lon, lat = longitude(numeric(ds["lon"][:])), numeric(ds["lat"][:])
                calculated = np.column_stack(proj(lon, lat))
                residual = float(np.max(np.linalg.norm(xy - calculated, axis=1)))
                require(residual < 1, "LOOFS projection does not match node coordinates")
                mesh = FaceMesh(xy, connectivity, proj)
                bounds = [float(lon.min()), float(lon.max()), float(lat.min()), float(lat.max())]
                projection = ds.CoordinateProjection
            require(
                np.array_equal(xy, coords)
                and np.array_equal(connectivity, tri)
                and projection == ds.CoordinateProjection,
                "LOOFS grid changed between times",
            )
            sigma = numeric(ds["siglay"][:])
            require(
                ds["siglay"].positive == "up"
                and np.all(np.diff(sigma, axis=0) < 0)
                and np.allclose(sigma[0], -0.025),
                "LOOFS top sigma layer mismatch",
            )
            h, eta = numeric(ds["h"][:]), numeric(ds["zeta"][0, :])
            depth_m = -sigma[0] * (h + eta)
            require(
                np.isfinite(depth_m).all() and np.all(depth_m >= 0), "invalid FVCOM top-layer depth"
            )
            depth.append(depth_m)
            mask = numeric(ds["wet_cells"][0, :])
            require(np.isin(mask, [0, 1]).all(), "invalid FVCOM wet/dry mask")
            dims = ("time", "siglay", "nele")
            require(
                all(getattr(ds[k], "location", None) == "face" for k in ("u", "v")),
                "FVCOM velocities must be face-centred",
            )
            fields.append(
                np.column_stack(
                    [
                        component(ds[k], n, dims, (0, 0, slice(None)))
                        for k, n in zip(("u", "v"), CF_NAMES["current"])
                    ]
                    + [mask]
                )
            )
            times.append(time)
    return SurfaceField(
        "current",
        tuple(times),
        mesh,
        np.stack(fields),
        files,
        {
            "vector_basis": "geographic_east_north",
            "native_variables": ["u", "v"],
            "spatial_method": "constant on containing native FVCOM face",
            "sigma_index": 0,
            "sigma": float(sigma[0, 0]),
            "top_layer_center_depth_m": [float(np.min(depth)), float(np.max(depth))],
            "lon_lat_bounds": bounds,
            "projection": projection,
            "node_projection_residual_m": residual,
        },
    )


def load_historical_forcing(manifest, root, *, start_utc=None, end_utc=None):
    """Load Lake Ontario using the B1 manifest and revalidate native bytes every run."""
    doc = json.loads(Path(manifest).read_bytes())
    root = Path(root)
    require(
        digest(root / "configs/stage7_scenarios.yaml") == doc["config_sha256"],
        "mission config SHA-256 mismatch",
    )
    case = next(c for c in doc["scenarios"] if c["scenario"] == "lake_ontario")
    require(
        case["pair_status"] == "verified"
        and case["forcing_kind"] == "historical_real"
        and case["verification_scope"] == "B1_raw_files",
        "Lake Ontario B1 verification required",
    )
    sources = {}
    for role in VARIABLES:
        files = case[role]["local_files"]
        require(
            files and all(re.fullmatch(r"[0-9a-f]{64}", r.get("sha256") or "") for r in files),
            f"missing historical source SHA-256 for {role}",
        )
        sources[role] = sorted(files, key=lambda r: utc_datetime(r["valid_utc"]))
    start, end = case["requested_window_utc"]
    return HistoricalForcing(
        _wind(root, sources["wind"]),
        _current(root, sources["current"]),
        (start if start_utc is None else start_utc, end if end_utc is None else end_utc),
        "historical_real",
    )
