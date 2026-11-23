"""Offline B1 checks. Every file and HTTP response in this module is synthetic."""

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import sys
from pathlib import Path
from urllib.error import URLError

import numpy as np
import pytest
import xarray as xr
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_lake_b1 as fetch
import inventory_historical as inv

SPEC = yaml.safe_load((inv.ROOT / "configs/stage7_scenarios.yaml").read_bytes())


@pytest.mark.parametrize(
    ("name", "expected_end"),
    [
        ("lake_ontario", "2025-08-26T15:52:33.740Z"),
        ("bay_of_fundy", "2025-02-14T09:33:57.200Z"),
        ("salish_sea", "2025-08-24T12:41:14.560Z"),
        ("arctic_ocean", "2025-08-30T00:46:18.000Z"),
    ],
)
def test_utc_window_includes_predrift_and_all_search_steps(name, expected_end):
    case = SPEC["scenarios"][name]
    (start, end), (lo, hi) = inv.windows(SPEC, case)
    assert inv.utc_datetime(start) == inv.utc_datetime(case["incident_utc"])
    assert end == expected_end
    assert lo < start < case["cst_utc"] < end < hi
    if name == "lake_ontario":
        assert [lo, hi] == ["2025-08-26T13:00:00.000Z", "2025-08-26T17:00:00.000Z"]


def test_metadata_alone_does_not_verify_any_source(tmp_path, monkeypatch):
    monkeypatch.setattr(inv, "probe", lambda item: dict(status="metadata_received", url=item[1]))
    cases = inv.inventory(SPEC, tmp_path)
    assert len(cases) == 4
    for c in cases:
        assert c["pair_status"] == "blocked_pending_file_verification"
        for role in ("wind", "current"):
            assert c[role]["status"] == "unverified"
            assert (
                c[role]["probes"]
                and c[role]["resolved_source"] is None
                and c[role]["sha256"] is None
            )


def test_access_error_is_logged(monkeypatch):
    def blocked(*args, **kwargs):
        raise URLError(PermissionError("offline test"))

    monkeypatch.setattr(inv.socket, "getaddrinfo", lambda *a, **kw: [])
    monkeypatch.setattr(inv, "urlopen", blocked)
    row = inv.probe(("idx", "https://example.invalid/wind.idx"))
    assert row["status"] == "probe_failed" and "offline test" in row["error"]
    assert "http_status" not in row and "evidence" not in row


def test_local_header_and_receipt_need_physical_review(tmp_path):
    directory = tmp_path / "wind"
    directory.mkdir()
    path = directory / "synthetic.nc"
    ds = xr.Dataset(
        {"u": ("time", [5.0], {"units": "m/s"})},
        coords={"time": np.array(["2000-01-01"], dtype="datetime64[ns]")},
    )
    ds.to_netcdf(path, engine="scipy")
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    receipt = {"wind": [dict(local_path=path.name, subset_sha256=sha, url="synthetic://fixture")]}
    (tmp_path / "acquisition_test.json").write_text(json.dumps(receipt), encoding="utf-8")
    row = inv.source("synthetic", "test", directory, [])
    f = row["local_files"][0]
    assert f["sha256"] == sha and f["acquisition"]["url"] == "synthetic://fixture"
    assert f["variables"]["u"]["units"] == "m/s"
    assert f["native_coordinate_ranges"]["time"][0].startswith("2000")
    assert row["status"] == "local_files_pending_review" and row["valid_time_range_utc"] is None
    receipt["wind"][0]["subset_sha256"] = "different"
    (tmp_path / "acquisition_test.json").write_text(json.dumps(receipt), encoding="utf-8")
    assert "acquisition" not in inv.source("synthetic", "test", directory, [])["local_files"][0]


def test_corrupt_file_cannot_count_as_reviewable_pair(tmp_path, monkeypatch):
    monkeypatch.setattr(inv, "probe", lambda item: {"status": "probe_failed"})
    for role in ("wind", "current"):
        folder = tmp_path / "lake_ontario" / role
        folder.mkdir(parents=True)
        (folder / "bad.nc").write_bytes(b"invalid")
    case = inv.inventory(SPEC, tmp_path)[0]
    assert case["wind"]["status"] == "local_files_unreadable"
    assert case["pair_status"] == "blocked_pending_file_verification"


def wind_index():
    return (
        "1:0:d=2025082612:TMP:2 m above ground:1 hour fcst:\n"
        "2:30:d=2025082612:UGRD:10 m above ground:1 hour fcst:\n"
        "3:50:d=2025082612:VGRD:10 m above ground:1 hour fcst:\n"
        "4:70:d=2025082612:UGRD:80 m above ground:1 hour fcst:\n"
    )


def test_wind_range_requires_complete_pair_and_message_end():
    assert fetch.selected_ranges(wind_index()) == {"UGRD": (30, 49), "VGRD": (50, 69)}
    with pytest.raises(ValueError, match="both"):
        fetch.selected_ranges(wind_index().replace("VGRD", "TMP"))
    with pytest.raises(ValueError, match="unbounded"):
        fetch.selected_ranges("\n".join(wind_index().splitlines()[:-1]))


@pytest.mark.parametrize("honor_range", [True, False])
def test_wind_acquisition_rejects_full_object_or_saves_exact_messages(
    tmp_path, monkeypatch, honor_range
):
    msg = b"GRIB" + bytes([0, 0, 0, 2]) + (20).to_bytes(8, "big") + b"7777"

    def server(req, timeout):
        if isinstance(req, str):
            return BytesIO(wind_index().encode("ascii"))
        r = BytesIO(msg)
        r.status = 206 if honor_range else 200
        r.headers = {"Content-Range": req.headers["Range"].replace("=", " ") + "/100"}
        return r

    monkeypatch.setattr(fetch, "urlopen", server)
    if honor_range:
        result = fetch.fetch_wind("https://example.invalid/wind", tmp_path)
        target = tmp_path / result["local_path"]
        assert target.read_bytes() == msg * 2
        assert result["subset_sha256"] == hashlib.sha256(msg * 2).hexdigest()
        assert result["full_object_sha256"] is None
        fetch.fetch_wind("https://example.invalid/wind", tmp_path)
        target.write_bytes(b"existing")
        with pytest.raises(ValueError, match="already exist"):
            fetch.fetch_wind("https://example.invalid/wind", tmp_path)
        assert target.read_bytes() == b"existing"
    else:
        with pytest.raises(ValueError, match="range"):
            fetch.fetch_wind("https://example.invalid/wind", tmp_path)
        assert not list(tmp_path.iterdir())


def test_current_selection_rejects_incomplete_cycles_and_station_files():
    cycle = datetime(2025, 8, 26, 12, tzinfo=timezone.utc)
    keys = {f"loofs/loofs.fields.f{h:03}.20250826.t12z.nc": 10 for h in (1, 2, 4)}
    keys["loofs/loofs.fields.f003.20250826.t00z.nc"] = 1
    keys["loofs/glofs.loofs.stations.forecast.20250826.t12z.nc"] = 1
    with pytest.raises(ValueError, match="no listed"):
        fetch.select_current(keys, cycle, [1, 2, 3])
    whole = "loofs/glofs.loofs.fields.forecast.20250826.t12z.nc"
    keys[whole] = 100
    assert fetch.select_current(keys, cycle, [1, 2, 3]) == [whole]
    keys["loofs/loofs.fields.f003.20250826.t12z.nc"] = 10
    assert len(fetch.select_current(keys, cycle, [1, 2, 3])) == 3


def test_current_pages_date_filters_and_alternate_layouts(monkeypatch):
    from urllib.parse import parse_qs, urlsplit

    date = datetime(2025, 8, 26, 12, tzinfo=timezone.utc)
    seen = []

    def list_page(url, timeout):
        params = parse_qs(urlsplit(url).query)
        prefix = params["prefix"][0]
        seen.append(params)
        body = ""
        if prefix == "loofs/netcdf/202508/" and "continuation-token" not in params:
            body = "<NextContinuationToken>next</NextContinuationToken>"
        if prefix == "loofs/netcdf/202508/" and "continuation-token" in params:
            for day in (25, 26):
                key = f"{prefix}nos.loofs.2ds.f001.202508{day}.t12z.nc"
                body += f"<Contents><Key>{key}</Key><Size>20</Size></Contents>"
        if prefix == "laofs/netcdf/2025/08/26/":
            body = (
                f"<Contents><Key>{prefix}laofs.t12z.fields.f001.nc</Key><Size>15</Size></Contents>"
            )
        return BytesIO(f"<ListBucketResult>{body}</ListBucketResult>".encode())

    monkeypatch.setattr(fetch, "urlopen", list_page)
    keys = fetch.current_keys(date)
    assert len(seen) == 5 and len(keys) == 2
    assert fetch.select_current(keys, date, [1]) == [
        "laofs/netcdf/2025/08/26/laofs.t12z.fields.f001.nc"
    ]


def test_current_size_limit_and_short_transfer_do_not_publish(tmp_path, monkeypatch):
    cycle = datetime(2025, 8, 26, 12, tzinfo=timezone.utc)
    key = "loofs/glofs.loofs.fields.forecast.20250826.t12z.nc"
    monkeypatch.setattr(fetch, "current_keys", lambda date: {key: 100})

    def unavailable(*args, **kwargs):
        pytest.fail("byte limit must be enforced before transfer")

    monkeypatch.setattr(fetch, "urlopen", unavailable)
    with pytest.raises(ValueError, match="byte budget"):
        list(fetch.fetch_current(tmp_path, cycle, [1], 99))
    monkeypatch.setattr(fetch, "urlopen", lambda *a, **kw: BytesIO(b"short"))
    with pytest.raises(ValueError, match="size differs"):
        list(fetch.fetch_current(tmp_path, cycle, [1], 100))
    assert not list(tmp_path.iterdir())
