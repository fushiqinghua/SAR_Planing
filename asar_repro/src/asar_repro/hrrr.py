"""Decode the HRRR f00 10 m messages supplied for Lake Ontario."""

from datetime import datetime, timezone
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


def grib_sections(message):
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


def lambert_grid(grid):
    """Decode the CONUS grid geometry carried by template 3.30."""
    require(
        len(grid) == 81
        and int.from_bytes(grid[12:14], "big") == 30
        and grid[14] == 6
        and grid[46] & 8
        and grid[63:65] == bytes((0, 64)),
        "unsupported HRRR Lambert grid or vector basis",
    )
    nx, ny, lat1, lon1 = struct.unpack_from(">IIII", grid, 30)
    lad, lov, dx, dy = struct.unpack_from(">IIII", grid, 47)
    latin1, latin2 = struct.unpack_from(">II", grid, 65)
    require(
        (nx, ny) == (1799, 1059) and nx * ny == int.from_bytes(grid[6:10], "big"),
        "unexpected HRRR grid dimensions",
    )
    require(dx > 0 and dy > 0, "invalid HRRR grid spacing")
    proj = Proj(
        proj="lcc",
        R=6371229,
        lat_0=lad / 1e6,
        lon_0=lov / 1e6,
        lat_1=latin1 / 1e6,
        lat_2=latin2 / 1e6,
    )
    x0, y0 = proj(lon1 / 1e6, lat1 / 1e6)
    return proj, x0 + np.arange(nx) * dx / 1000, y0 + np.arange(ny) * dy / 1000


def f00_wind(data):
    """Return one verified valid UTC and the two native grid components."""
    pos = 0
    components = {}
    grid = reference = None
    while pos < len(data):
        length = int.from_bytes(data[pos + 8 : pos + 16], "big")
        require(length >= 20 and pos + length <= len(data), "truncated HRRR message")
        sec = grib_sections(data[pos : pos + length])
        pos += length
        product = sec[4]
        require(
            len(product) == 34
            and product[7:10] == bytes((0, 0, 2))
            and product[10] in (2, 3)
            and product[17:29] == bytes.fromhex("010000000067000000000aff"),
            "expected HRRR f00 wind at 10 m above ground",
        )
        date = datetime(*struct.unpack_from(">H5B", sec[1], 12), tzinfo=timezone.utc)
        if grid is None:
            grid, reference = sec[3], date
            projection, x, y = lambert_grid(grid)
        require(
            grid == sec[3] and date == reference and product[10] not in components,
            "inconsistent wind grid, time or component",
        )
        components[product[10]] = simple_values(sec[5], sec[7][5:], len(x) * len(y)).reshape(
            len(y), len(x)
        )
    require(set(components) == {2, 3}, "both HRRR wind components required")
    return reference, grid, projection, x, y, np.stack((components[2], components[3]), axis=-1)


def geographic_wind(proj, lon, lat, uv):
    """Rotate interpolated grid east/north using Lambert meridian convergence."""
    angle = np.deg2rad(proj.get_factors(lon, lat).meridian_convergence)
    c, s = np.cos(angle), np.sin(angle)
    u, v = uv.T
    return np.column_stack((c * u + s * v, -s * u + c * v))
