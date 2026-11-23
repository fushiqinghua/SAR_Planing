"""Offline B1 inspection of the delivered HRRR messages (GRIB2 templates 3.30/4.0/5.0)."""

from datetime import datetime, timezone
import hashlib
import struct

import numpy as np
from pyproj import Proj


def require(ok, message):
    if not ok:
        raise ValueError(message)


def simple_values(section, payload, count):
    """Unpack GRIB2 template 5.0, Y = (R + X * 2**E) * 10**(-D)."""
    n, template, ref, binary, decimal, width, kind = struct.unpack(">IHfHHBB", section[5:])
    require((n, template, kind) == (count, 0, 0) and 1 <= width <= 16, "unsupported packing")
    require(len(payload) == (n * width + 7) // 8, "packed wind field length mismatch")

    def signed_magnitude(x):
        return -(x & 0x7FFF) if x & 0x8000 else x

    bits = np.unpackbits(np.frombuffer(payload, dtype="u1"), count=n * width).reshape(n, width)
    powers = np.left_shift(1, np.arange(width - 1, -1, -1, dtype=np.uint16))
    integers = bits @ powers
    return (ref + np.ldexp(integers.astype(float), signed_magnitude(binary))) * 10.0 ** (
        -signed_magnitude(decimal)
    )


def fields(message):
    require(
        message[:4] == b"GRIB"
        and message[6:8] == bytes((0, 2))
        and int.from_bytes(message[8:16], "big") == len(message)
        and message[-4:] == b"7777",
        "invalid GRIB2 message",
    )
    sections = {}
    p = 16
    for number in (1, 3, 4, 5, 6, 7):
        size, actual = struct.unpack_from(">IB", message, p)
        require(actual == number and 5 <= size <= len(message) - 4 - p, "invalid GRIB2 section")
        sections[number] = message[p : p + size]
        p += size
    require(p == len(message) - 4 and sections[6][5:] == b"\xff", "unexpected bitmap or section")
    return sections


def geometry(grid, points):
    require(
        len(grid) == 81
        and int.from_bytes(grid[12:14], "big") == 30
        and grid[14] == 6
        and grid[46] & 8
        and grid[63:65] == bytes((0, 64)),
        "unsupported Lambert grid or vector basis",
    )
    nx, ny, lat1, lon1 = struct.unpack_from(">IIII", grid, 30)
    lad, lov, dx, dy = struct.unpack_from(">IIII", grid, 47)
    latin1, latin2 = struct.unpack_from(">II", grid, 65)
    require(
        nx * ny == int.from_bytes(grid[6:10], "big") and (nx, ny) == (1799, 1059),
        "grid count mismatch",
    )
    proj = Proj(
        proj="lcc",
        R=6371229,
        lat_1=latin1 / 1e6,
        lat_2=latin2 / 1e6,
        lat_0=lad / 1e6,
        lon_0=lov / 1e6,
    )
    x0, y0 = proj(lon1 / 1e6, lat1 / 1e6)
    x, y = proj(points[:, 0], points[:, 1])
    col, row = (x - x0) / (dx / 1000), (y - y0) / (dy / 1000)
    require(
        np.all((col >= 0) & (col < nx - 1) & (row >= 0) & (row < ny - 1)), "point outside wind grid"
    )
    indices = np.rint(row).astype(int) * nx + np.rint(col).astype(int)
    # The latitude extremum on a Lambert grid need not be a corner.
    edge_col = np.r_[np.arange(nx), np.arange(nx), np.zeros(ny), np.full(ny, nx - 1)]
    edge_row = np.r_[np.zeros(nx), np.full(nx, ny - 1), np.arange(ny), np.arange(ny)]
    lon, lat = proj(x0 + edge_col * dx / 1000, y0 + edge_row * dy / 1000, inverse=True)
    return indices, dict(
        Nx=nx,
        Ny=ny,
        grid_type="Lambert conformal",
        radius_m=6371229,
        latitude_origin=lad / 1e6,
        central_longitude=lov / 1e6,
        standard_parallels=[latin1 / 1e6, latin2 / 1e6],
        first_lon_lat=[lon1 / 1e6, lat1 / 1e6],
        spacing_m=[dx / 1000, dy / 1000],
        uvRelativeToGrid=1,
        scan_mode=64,
        lon_lat_bounds=[float(lon.min()), float(lon.max()), float(lat.min()), float(lat.max())],
    )


def stats(values):
    require(np.isfinite(values).all() and np.ptp(values) > 0, "missing or spatially constant field")
    return dict(
        count=values.size,
        min=float(values.min()),
        max=float(values.max()),
        mean=float(values.mean(dtype=float)),
        std=float(values.std(dtype=float)),
        missing_count=0,
    )


def wind(path, receipt, index_ranges, points, reference):
    data = path.read_bytes()
    used = 0
    records = {}
    for item in receipt["byte_ranges"]:
        name, start, end = item["variable"], item["start"], item["end_inclusive"]
        require(index_ranges[name] == (start, end), "wind byte range differs from index")
        msg = data[used : used + end - start + 1]
        used += len(msg)
        require(hashlib.sha256(msg).hexdigest() == item["sha256"], "wind message hash mismatch")
        sec = fields(msg)
        year, mo, day, hour, minute, second = struct.unpack_from(">H5B", sec[1], 12)
        valid = datetime(year, mo, day, hour, minute, second, tzinfo=timezone.utc).isoformat()
        require(
            valid == datetime.fromisoformat(receipt["run_cycle_utc"]).isoformat(),
            "wind reference time mismatch",
        )
        product = sec[4]
        param = {"UGRD": 2, "VGRD": 3}[name]
        require(
            product[7:11] == bytes((0, 0, 2, param))
            and product[17:29] == bytes.fromhex("010000000067000000000aff"),
            "expected f00 10 m above ground wind",
        )
        indices, grid = geometry(sec[3], points)
        values = simple_values(sec[5], sec[7][5:], grid["Nx"] * grid["Ny"])
        summary = stats(values)
        ref = next(
            r
            for r in reference["records"]
            if r["metadata"]["shortName"] == {2: "10u", 3: "10v"}[param]
        )
        require(ref["valid_time_utc"] == valid, "ecCodes time disagreement")
        for k in ("min", "max", "mean", "std"):
            require(
                np.isclose(summary[k], ref["statistics"][k], rtol=1e-10, atol=1e-10),
                f"ecCodes {k} disagreement",
            )
        samples = {}
        for label, j in zip(("LKP", "CSP"), indices[:2]):
            sample = ref["point_samples"][label]
            require(
                int(j) == sample["flat_index"]
                and values[j] == sample["grid_relative_component_m_s"],
                "independent wind location or sample differs from ecCodes",
            )
            samples[label] = dict(flat_index=int(j), grid_relative_m_s=float(values[j]))
        records[name] = dict(statistics=summary, points=samples)
    require(
        used == len(data) and set(records) == {"UGRD", "VGRD"}, "incomplete wind component pair"
    )
    return dict(
        valid_utc=valid, grid=grid, units="m/s", components=records, sites_inside_grid=len(points)
    )
