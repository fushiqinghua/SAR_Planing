"""Native OPeNDAP transport for the same official ESPC-D-V02 annual ice dataset."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from urllib.parse import quote

import numpy as np

from h2_acquire import _fetch, _row_identity, _write_once
from h2_hycom import CATALOG, VARIABLES, requests_for


DAP = "https://tds.hycom.org/thredds/dodsC/ESPC-D-V02/ice/2025"
DAS = DAP + ".das"
TIME_AXIS = DAP + ".ascii?time"
# These inclusive native indices give the same coordinates as the H2 NCSS box.
Y, X = (3538, 3600), (3350, 3394)
NT, NY, NX = 8760, 63, 45
VARIABLE_NAMES = tuple(name for name, _, _ in VARIABLES)
CF_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


def time_axis(data):
    """Use the archived provider coordinate, never assume a midnight first index."""
    header, delimiter, values = data.decode("ascii").partition(f"\ntime[{NT}]\n")
    if not delimiter or f"Float64 time[time = {NT}];" not in header or "ESPC-D-V02/ice/2025" not in header:
        raise ValueError("Unexpected HYCOM OPeNDAP time-axis product or shape")
    values = np.array([float(value) for value in values.strip().split(",")], dtype=float)
    rounded = np.rint(values)
    if (values.shape != (NT,) or not np.isfinite(values).all()
            or not np.allclose(values, rounded, rtol=0, atol=1e-6 / 3600)
            or not np.all(np.diff(rounded) > 0)):
        raise ValueError("HYCOM OPeNDAP time axis is not a strictly ordered native hourly coordinate")
    return rounded


def _slice(start, stop):
    return f"[{start}:1:{stop}]"


def dap_url(times, axis):
    hours = [(datetime.fromisoformat(value) - CF_EPOCH).total_seconds() / 3600 for value in times]
    i = int(np.searchsorted(axis, hours[0]))
    j = i + len(times) - 1
    if not np.array_equal(hours, axis[i:j + 1]):
        raise ValueError("HYCOM DAP requests require consecutive native hours")
    t, y, x = _slice(i, j), _slice(*Y), _slice(*X)
    members = [f"time{t}", f"lat{y}", f"lon{x}"]
    members.extend(f"{key}.{key}{t}{y}{x}" for key in VARIABLE_NAMES)
    return DAP + ".dods?" + quote(",".join(members), safe=",.:")


def attributes(data):
    """Read the declared field encodings and check the official CF identities."""
    text = data.decode("ascii")

    def group(name):
        match = re.search(rf"(?m)^    {name} \{{\n(.*?)^    \}}", text, flags=re.S)
        if match is None:
            raise ValueError(f"HYCOM DAP lacks the {name} metadata group")
        return match[1]

    def field(body, kind, name):
        match = re.search(rf"(?m)^        {kind} {name} ([^\n;]+);$", body)
        if match is None:
            raise ValueError(f"HYCOM DAP lacks the expected CF attribute {name}")
        return match[1].strip('"')

    global_attrs = group("NC_GLOBAL")
    if ("HYCOM" not in field(global_attrs, "String", "source")
            or "ESPC-D V02" not in field(global_attrs, "String", "generating_model")
            or field(group("lon"), "String", "units") != "degrees_east"
            or field(group("lat"), "String", "units") != "degrees_north"
            or field(group("time"), "String", "units") != "hours since 2000-01-01 00:00:00"
            or field(group("time"), "String", "calendar") != "gregorian"):
        raise ValueError("HYCOM DAP source identity, coordinates or time basis changed")
    result = {}
    for name, standard, units in VARIABLES:
        body = group(name)
        if (field(body, "String", "standard_name") != standard or field(body, "String", "units") != units
                or "_Unsigned" in body):
            raise ValueError(f"HYCOM DAP direction, units or signed encoding differ for {name}")
        missing = int(field(body, "Int16", "_FillValue"))
        if int(field(body, "Int16", "missing_value")) != missing:
            raise ValueError(f"HYCOM DAP missing-value encodings differ for {name}")
        scale, add = (np.float32(field(body, "Float32", key)) for key in ("scale_factor", "add_offset"))
        if not np.isfinite([scale, add]).all() or scale <= 0:
            raise ValueError(f"Invalid CF packing on HYCOM DAP {name}")
        result[name] = dict(fill=missing, scale=scale, add=add)
    return result


def packed_product(payload, ntime):
    """Read the exact six projected DAP2 arrays including their XDR count fields."""
    head, delimiter, data = payload.partition(b"\nData:\n")
    dds = "Dataset { Float64 lat[lat = 63]; Float64 lon[lon = 45]; "
    dds += f"Float64 time[time = {ntime}]; "
    dds += " ".join(
        f"Structure {{ Int16 {name}[time = {ntime}][lat = 63][lon = 45]; }} {name};"
        for name in VARIABLE_NAMES
    )
    dds += " } ESPC-D-V02/ice/2025;"
    if not delimiter or " ".join(head.decode("ascii").split()) != dds:
        raise ValueError("Unexpected targeted HYCOM DAP2 dataset, field order or shape")
    cursor = 0
    arrays = {}
    counts = dict(lat=NY, lon=NX, time=ntime)
    for name in (*counts, *VARIABLE_NAMES):
        count = counts.get(name, ntime * NY * NX)
        dtype = np.dtype(">f8" if name in counts else ">i4")
        extent = cursor + 8 + count * dtype.itemsize
        if extent > len(data) or np.frombuffer(data, ">u4", count=2, offset=cursor).tolist() != [count, count]:
            raise ValueError(f"HYCOM DAP2 count or byte length differs for {name}")
        array = np.frombuffer(data, dtype, count=count, offset=cursor + 8)
        if name in counts:
            arrays[name] = array.astype(np.float64)
        else:
            if np.any((array < -32768) | (array > 32767)):
                raise ValueError(f"HYCOM DAP {name} exceeds its signed int16 declaration")
            arrays[name] = array.astype(np.int16).reshape(ntime, NY, NX)
        cursor = extent
    if cursor != len(data):
        raise ValueError("Extra bytes after targeted HYCOM DAP2 arrays")
    return arrays


def unpack(array, encoding):
    numeric = array.astype(np.float32) * encoding["scale"] + encoding["add"]
    return np.where(array == encoding["fill"], np.nan, numeric).astype(np.float64)


def acquire_hycom_dap(root, raw, block, attempts):
    raw.mkdir(parents=True, exist_ok=False)
    receipts = raw / "dap_request_receipts.jsonl"
    das, _ = _fetch(receipts, DAS, "hycom_dap_attributes", attempts, limit=64 * 1024, kind="dap")
    das_path = raw / "ESPC-D-V02_ice_2025.das"
    _write_once(das_path, das)
    metadata = _row_identity(root, das_path, das) | {"source_url": DAS}
    axis_bytes, _ = _fetch(receipts, TIME_AXIS, "hycom_dap_time_axis", attempts, limit=512 * 1024, kind="dap")
    axis_path = raw / "ESPC-D-V02_ice_2025.time.txt"
    _write_once(axis_path, axis_bytes)
    axis_capture = _row_identity(root, axis_path, axis_bytes) | {"source_url": TIME_AXIS}
    axis = time_axis(axis_bytes)
    results = []
    for spec in requests_for(block):
        times = spec["valid_times_utc"]
        url = dap_url(times, axis)
        data, headers = _fetch(receipts, url, "hycom_dap_native_fields", attempts,
                               limit=2 * 1024 * 1024, kind="dap")
        path = raw / spec["filename"].replace(".nc", ".dods")
        _write_once(path, data)
        results.append(_row_identity(root, path, data) | dict(
            source_url=url, catalog_url=CATALOG, valid_times_utc=times, block_id=block["id"],
            product="ESPC-D-V02", http_status=200, http_headers=headers, metadata=metadata, time_axis=axis_capture,
            access="official_opendap_dap2",
        ))
    return results
