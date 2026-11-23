"""Strict decoder for the delivered GFS 3.0/4.0/5.3 messages; no model changes.

NOAA specifications:
https://www.nco.ncep.noaa.gov/pmb/docs/grib2/grib2_doc/grib2_temp5-3.shtml
https://www.nco.ncep.noaa.gov/pmb/docs/grib2/grib2_doc/grib2_temp7-3.shtml
Only general group splitting, no missing values/bitmap, and order 1/2 are supported.
Every delivered component is cross-checked against its independent ecCodes record.
"""

from datetime import datetime, timedelta, timezone
import struct

import numpy as np

from asar_repro.hrrr import grib_sections, require


def signed(value, bits):
    sign = 1 << (bits - 1)
    return -(value & (sign - 1)) if value & sign else value


class Bits:
    def __init__(self, data):
        self.bits = np.unpackbits(np.frombuffer(data, dtype=np.uint8))
        self.offset = 0

    def take(self, count, width):
        require(count >= 0 and 0 <= width <= 32, "unsupported bit count or width")
        end = self.offset + count * width
        require(end <= len(self.bits), "truncated complex packing")
        if width:
            values = self.bits[self.offset:end].reshape(count, width) @ (
                1 << np.arange(width - 1, -1, -1, dtype=np.int64)
            )
        else:
            values = np.zeros(count, dtype=np.int64)
        self.offset = end
        return values

    def align(self):
        end = (self.offset + 7) // 8 * 8
        require(not self.bits[self.offset:end].any(), "nonzero GRIB padding")
        self.offset = end


def complex_values(section, payload, count):
    require(len(section) == 49, "expected template 5.3 length")
    n, template, ref, binary, decimal, width, kind = struct.unpack(">IHfHHBB", section[5:21])
    require((n, template, kind) == (count, 3, 0), "unsupported complex packing identity")
    require(section[21:23] == b"\x01\x00", "unsupported splitting or missing-value management")
    groups = int.from_bytes(section[31:35], "big")
    wref, wbits = section[35:37]
    lref = int.from_bytes(section[37:41], "big")
    increment = section[41]
    last = int.from_bytes(section[42:46], "big")
    lbits, order, octets = section[46:49]
    require(0 < groups <= count and order in (1, 2) and 1 <= octets <= 4,
            "unsupported group count or differencing order")
    require(count > order and len(payload) >= (order + 1) * octets, "truncated descriptors")
    initial = [int.from_bytes(payload[i * octets:(i + 1) * octets], "big") for i in range(order)]
    minimum = signed(int.from_bytes(payload[order * octets:(order + 1) * octets], "big"), 8 * octets)
    stream = Bits(payload[(order + 1) * octets:])
    references = stream.take(groups, width)
    stream.align()
    widths = stream.take(groups, wbits) + wref
    stream.align()
    lengths = stream.take(groups, lbits) * increment + lref
    stream.align()
    lengths[-1] = last
    require(np.all(lengths > 0) and lengths.sum() == count, "group lengths do not match field")
    packed = np.empty(count, dtype=np.int64)
    offset = 0
    for base, length, size in zip(references, lengths, widths, strict=True):
        packed[offset:offset + length] = base + stream.take(int(length), int(size))
        offset += length
    stream.align()
    require(stream.offset == len(stream.bits), "extra bytes after complex field")
    values = np.empty(count, dtype=np.int64)
    values[:order] = initial
    if order == 1:
        values[1:] = initial[0] + np.cumsum(packed[1:] + minimum)
    else:
        first_diff = initial[1] - initial[0] + np.cumsum(packed[2:] + minimum)
        values[2:] = initial[1] + np.cumsum(first_diff)
    require(np.all(values >= 0) and np.isfinite(ref), "invalid recovered scaled field")
    return (ref + np.ldexp(values.astype(float), signed(binary, 16))) * 10.0 ** -signed(decimal, 16)


def regular_grid(grid):
    require(len(grid) == 72 and int.from_bytes(grid[12:14], "big") == 0,
            "expected regular latitude/longitude GFS grid")
    nx, ny, basic, subdivisions = struct.unpack_from(">IIII", grid, 30)
    require(basic == 0 and subdivisions in (0, 0xFFFFFFFF), "unsupported GFS angular unit")
    lat1, lon1 = struct.unpack_from(">II", grid, 46)
    lat2, lon2, dx, dy = struct.unpack_from(">IIII", grid, 55)
    require(grid[54] & 8 == 0 and grid[71] == 0, "expected geographic vectors and standard scan")
    require(nx >= 2 and ny >= 2 and nx * ny == int.from_bytes(grid[6:10], "big"), "GFS dimensions")
    lon = lon1 / 1e6 + np.arange(nx) * dx / 1e6
    lat = signed(lat1, 32) / 1e6 - np.arange(ny) * dy / 1e6
    require(dx > 0 and dy > 0 and np.isclose(lat[-1], signed(lat2, 32) / 1e6)
            and np.isclose(lon[-1], lon2 / 1e6), "GFS grid endpoint mismatch")
    return lon, lat


def decode(data):
    offset = 0
    grid = cycle = lead = None
    components = {}
    while offset < len(data):
        size = int.from_bytes(data[offset + 8:offset + 16], "big")
        require(size >= 20 and offset + size <= len(data), "truncated GFS message")
        sec = grib_sections(data[offset:offset + size])
        offset += size
        p = sec[4]
        require(len(p) == 34 and p[7:10] == b"\x00\x00\x02" and p[10] in (2, 3)
                and p[17] == 1 and p[22:29] == bytes.fromhex("67000000000aff"),
                "expected GFS 10 m U/V and forecast hours")
        t = datetime(*struct.unpack_from(">H5B", sec[1], 12), tzinfo=timezone.utc)
        hours = int.from_bytes(p[18:22], "big")
        if grid is None:
            grid, cycle, lead = sec[3], t, hours
            lon, lat = regular_grid(grid)
        require(grid == sec[3] and cycle == t and lead == hours and p[10] not in components,
                "inconsistent GFS component/grid/time")
        components[p[10]] = complex_values(sec[5], sec[7][5:], len(lon) * len(lat)).reshape(len(lat), len(lon))
    require(set(components) == {2, 3}, "both GFS components required")
    return dict(cycle=cycle, valid=cycle + timedelta(hours=lead), lead_hours=lead,
                lon=lon, lat=lat, uv=np.stack([components[2], components[3]], axis=-1))
