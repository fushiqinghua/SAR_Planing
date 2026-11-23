"""Offline constant Leeway generation and ID-preserving absolute UTC resampling."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np


def utc_datetime(value):
    dt = datetime.fromisoformat(value) if isinstance(value, str) else value
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("an explicit UTC offset is required")
    return dt.astimezone(timezone.utc)


def planning_times(cst, budget, step_s):
    ns = Decimal(str(step_s)) * 10**9
    if budget < 0 or not ns.is_finite() or ns <= 0 or ns != ns.to_integral_value():
        raise ValueError("invalid planning budget or nanosecond step")
    start = np.datetime64(utc_datetime(cst).replace(tzinfo=None), "ns")
    return start + np.arange(budget + 1) * np.timedelta64(int(ns), "ns")


def run_constant(config):
    """Return the unmodified dataset and installed Leeway object provenance."""
    if config["forcing_kind"] != "constant_synthetic":
        raise ValueError("only explicit constant_synthetic forcing is supported")
    fields = config["forcing"]
    required = {"x_wind", "y_wind", "x_sea_water_velocity", "y_sea_water_velocity", "land_binary_mask"}
    if set(fields) != required or not all(np.isfinite(v) for v in fields.values()):
        raise ValueError("explicit finite constant wind, current and land mask required")
    if fields["land_binary_mask"] != 0:
        raise ValueError("this synthetic generator requires the declared all-water mask")
    from opendrift.models.leeway import Leeway
    from opendrift.readers.reader_constant import Reader

    incident = utc_datetime(config["incident_utc"])
    times = planning_times(config["cst_utc"], config["budget"], config["step_s"])
    initial = np.datetime64(incident.replace(tzinfo=None), "ns")
    dt, output = config["integration_s"], config["output_s"]
    if dt <= 0 or output <= 0 or output % dt or times[0] < initial:
        raise ValueError("require incident <= CST and output interval divisible by integration step")
    span_ns = int((times[-1] - initial).astype("timedelta64[ns]").astype(np.int64))
    interval_ns = output * 10**9
    intervals = (span_ns + interval_ns - 1) // interval_ns
    # This OpenDrift version seeds/uses NumPy's process-global legacy RNG.
    state = np.random.get_state()
    try:
        model = Leeway(seed=config["seed"], loglevel=30)
        matches = [i for i, props in model.leewayprop.items() if props["OBJKEY"] == config["object_key"]]
        if len(matches) != 1:
            raise ValueError("unknown or ambiguous local Leeway object key")
        obj = matches[0]
        model.set_config("general:use_auto_landmask", False)
        model.set_config("seed:ocean_only", False)
        model.add_reader(Reader(dict(fields)))
        lon, lat = config["lkp_lon_lat"]
        model.seed_elements(lon=lon, lat=lat, number=config["particles"], radius=config["radius_m"],
                            time=incident.replace(tzinfo=None), object_type=obj)
        ds = model.run(duration=timedelta(seconds=intervals * output), time_step=dt,
                       time_step_output=output, export_variables=["lon", "lat", "status", "land_binary_mask"])
        if ds.sizes["trajectory"] != config["particles"]:
            raise ValueError("Leeway returned a different number of trajectory IDs than seeded")
        return ds, {"number": obj, "key": model.leewayprop[obj]["OBJKEY"],
                    "description": model.leewayprop[obj]["Description"]}
    finally:
        np.random.set_state(state)


@dataclass
class Frames:
    ids: np.ndarray
    time_utc: np.ndarray
    lon: np.ndarray
    lat: np.ndarray
    status: np.ndarray
    land: np.ndarray
    flags: dict

    @classmethod
    def from_dataset(cls, ds):
        if not {"trajectory", "time"} <= set(ds.coords):
            raise ValueError("explicit trajectory IDs and absolute time coordinates are required")
        ids = ds.trajectory.values.copy()
        if ds.trajectory.dims != ("trajectory",) or ds.time.dims != ("time",):
            raise ValueError("invalid trajectory/time coordinate dimensions")
        if not np.issubdtype(ds.time.dtype, np.datetime64):
            raise ValueError("decode source UTC dates before adapting the dataset")
        times = ds.time.values.astype("datetime64[ns]")
        if not ids.size or np.unique(ids).size != ids.size:
            raise ValueError("trajectory IDs must be unique")
        if not times.size or np.isnat(times).any() or (np.diff(times) <= np.timedelta64(0, "ns")).any():
            raise ValueError("source UTC time must increase strictly")
        arrays = [ds[k].transpose("time", "trajectory").values.copy()
                  for k in ("lon", "lat", "status", "land_binary_mask")]
        attrs = ds.status.attrs
        flags = dict(zip(map(int, attrs["flag_values"]), attrs["flag_meanings"].split(), strict=True))
        status = arrays[2]
        if "active" not in flags.values() or not np.isin(status[np.isfinite(status)], list(flags)).all():
            raise ValueError("status flags must identify all observed codes and active")
        return cls(ids, times, *arrays, flags)

    def resample(self, utc_times):
        """Interpolate positions at UTC instants; keep ambiguous transitions unsearchable."""
        t = np.asarray(utc_times, dtype="datetime64[ns]")
        source = self.time_utc
        if (t.ndim != 1 or not len(t) or np.isnat(t).any() or np.any(t[1:] <= t[:-1])
                or t[0] < source[0] or t[-1] > source[-1]):
            raise ValueError("requested UTC times must increase and lie within source coverage")
        hi = np.searchsorted(source, t)
        exact = source[hi] == t
        lo = np.where(exact, hi, hi - 1)
        fraction = np.zeros(len(t))
        between = ~exact
        fraction[between] = (t[between] - source[lo[between]]) / (source[hi[between]] - source[lo[between]])
        # OpenDrift writes a terminal status once, then NaN. Carry only
        # terminal codes through these trailing blanks, never active positions.
        status = self.status.astype(float, copy=True)
        active = next(code for code, label in self.flags.items() if label == "active")
        for i in range(1, len(status)):
            prev = status[i - 1]
            held = np.isnan(status[i]) & np.isfinite(prev) & (prev != active)
            status[i, held] = prev[held]
        aligned_status = np.where(status[lo] == status[hi], status[lo], np.nan)
        land = np.where(self.land[lo] == self.land[hi], self.land[lo], np.nan)
        valid = (status[lo] == status[hi]) & (self.land[lo] == self.land[hi])
        lon0, lon1 = self.lon[lo].astype(float), self.lon[hi].astype(float)
        delta = (lon1 - lon0 + 180.) % 360. - 180.
        lon = (lon0 + fraction[:, None] * delta + 180.) % 360. - 180.
        lat0, lat1 = self.lat[lo].astype(float), self.lat[hi].astype(float)
        lat = lat0 + fraction[:, None] * (lat1 - lat0)
        lon = np.where(exact[:, None], lon0, np.where(valid, lon, np.nan))
        lat = np.where(exact[:, None], self.lat[lo], np.where(valid, lat, np.nan))
        return Frames(self.ids.copy(), t, lon, lat, aligned_status, land, self.flags.copy())
