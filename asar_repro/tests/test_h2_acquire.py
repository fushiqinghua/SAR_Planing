"""Offline tests of the fixed H2 NOAA acquisition paths and transfer receipts."""
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import pytest


SPEC = importlib.util.spec_from_file_location(
    "h2_noaa_acquisition", Path(__file__).resolve().parents[1] / "scripts/h2_acquire.py"
)
acquire = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acquire)


def inventory(cycle="2025091218", lead=3):
    forecast = "anl" if lead == 0 else f"{lead} hour fcst"
    return (
        f"1:0:d={cycle}:UGRD:10 m above ground:{forecast}:\n"
        f"2:20:d={cycle}:VGRD:10 m above ground:{forecast}:\n"
        f"3:40:d={cycle}:TMP:surface:{forecast}:\n"
    ).encode()


def listing(prefix, lags=(1, 2, 3, 4, 5), *, duplicate=False, truncated="false"):
    rows = [
        f"<Contents><Key>{prefix}{lag:03}.nc</Key><Size>16</Size>"
        '<ETag>"netcdf"</ETag><LastModified>2025-09-09T20:45:49Z</LastModified></Contents>'
        for lag in lags
    ]
    if duplicate:
        rows.append(rows[0])
    return (
        '<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"<Name>noaa-nos-ofs-pds</Name><Prefix>{prefix}</Prefix><IsTruncated>{truncated}</IsTruncated>"
        + "".join(rows) + "</ListBucketResult>"
    ).encode()


def test_wind_index_extracts_original_ranges():
    cycle = datetime(2025, 9, 12, 18, tzinfo=timezone.utc)
    rows = acquire.parse_wind_index(inventory(), cycle, 3)
    assert [(r["variable"], r["start"], r["end_inclusive"]) for r in rows] == [
        ("UGRD", 0, 19), ("VGRD", 20, 39)
    ]
    assert rows[0]["index_line"].endswith(":3 hour fcst:")


@pytest.mark.parametrize("idx", [
    inventory(cycle="2025091118"),
    inventory(lead=6),
    inventory().replace(b"VGRD:10 m", b"VGRD:20 m"),
    inventory().replace(b"3:40", b"3:20"),
    inventory().replace(b"VGRD:10 m", b"UGRD:10 m"),
    inventory().splitlines()[0] + b"\n",
    b"<!doctype html>",
])
def test_wind_index_rejects_unproved_messages(idx):
    with pytest.raises(acquire.AcquisitionError):
        acquire.parse_wind_index(idx, datetime(2025, 9, 12, 18, tzinfo=timezone.utc), 3)


@pytest.mark.parametrize("status, headers, error", [
    (200, {"content-length": "20"}, "Expected HTTP 206"),
    (206, {"content-range": "bytes 0-20/40", "etag": '"a"'}, "Content-Range"),
    (206, {"content-range": "bytes 0-19/19", "etag": '"a"'}, "Content-Range"),
    (206, {"content-type": "text/html", "etag": '"a"'}, "HTML"),
    (206, {"content-type": "text/plain", "etag": '"b"'}, "ETag"),
    (206, {"content-range": "bytes 0-19/40", "content-length": "19", "etag": '"a"'}, "Content-Length"),
    (206, {"content-encoding": "gzip", "etag": '"a"'}, "encoding"),
])
def test_malformed_range_response_is_rejected(status, headers, error):
    with pytest.raises(acquire.AcquisitionError, match=error):
        acquire._verify_headers(status, headers, byte_range=(0, 19), size=20, etag='"a"')


def test_listed_objects_match_requested_prefix_and_count():
    prefix = "loofs/netcdf/2025/09/09/loofs.t18z.20250909.fields.n"
    keys = [f"{prefix}{i:03}.nc" for i in range(1, 6)]
    objects = acquire.parse_loofs_listing(listing(prefix, (0, 1, 2, 3, 4, 5, 6)), prefix, keys)
    assert list(objects) == keys
    assert objects[keys[0]]["size"] == 16
    with pytest.raises(acquire.AcquisitionError, match="absent") as failure:
        acquire.parse_loofs_listing(listing(prefix, (1, 2, 3, 4)), prefix, keys)
    assert failure.value.reason == "source_missing"
    with pytest.raises(acquire.AcquisitionError, match="Invalid or duplicate"):
        acquire.parse_loofs_listing(listing(prefix, duplicate=True), prefix, keys)
    with pytest.raises(acquire.AcquisitionError, match="did not confirm"):
        acquire.parse_loofs_listing(listing(prefix, truncated="true"), prefix, keys)


class Response(io.BytesIO):
    def __init__(self, url, data, status, headers):
        super().__init__(data)
        self.url, self.status = url, status
        self.headers = {"Content-Length": str(len(data)), **headers}

    def geturl(self):
        return self.url


def test_request_attempts_are_kept_and_payload_is_not_assumed(monkeypatch, tmp_path):
    attempts = []

    def interrupted(request, timeout):
        attempts.append(request.full_url)
        raise URLError("temporary outage")

    monkeypatch.setattr(acquire, "urlopen", interrupted)
    receipts = tmp_path / "receipts.jsonl"
    with pytest.raises(acquire.AcquisitionError, match="temporary outage"):
        acquire._fetch(receipts, "https://archive.test/file", "wind_index", 3,
                       limit=100, kind="index")
    assert len(attempts) == 3 and len(set(attempts)) == 1
    rows = [json.loads(line) for line in receipts.read_text().splitlines()]
    assert [row["attempt"] for row in rows] == [1, 2, 3]
    assert all(row["outcome"] == "failed" and row["reason"] == "network" for row in rows)

    def html_ok(request, timeout):
        return Response(request.full_url, b"<!doctype html>failure", 200, {"Content-Type": "text/plain"})

    monkeypatch.setattr(acquire, "urlopen", html_ok)
    with pytest.raises(acquire.AcquisitionError, match="HTML"):
        acquire._fetch(receipts, "https://archive.test/file", "wind_index", 3,
                       limit=100, kind="index")
    assert len(receipts.read_text().splitlines()) == 4


def test_noaa_uses_registered_wind_schedule_and_listed_lake_objects(monkeypatch, tmp_path_factory):
    # Full provider basenames plus a sandbox TEMP path need a short fixture directory on Windows.
    tmp_path = tmp_path_factory.mktemp("noaa")
    grib = b"GRIB\x00\x00\x00\x02" + (20).to_bytes(8, "big") + b"7777"
    netcdf = b"\x89HDF\r\n\x1a\n" + b"\x00" * 8
    seen = []

    def fixture(request, timeout):
        url = request.full_url
        parsed = urlsplit(url)
        seen.append(url)
        if parsed.path == "/":
            prefix = parse_qs(parsed.query)["prefix"][0]
            return Response(url, listing(prefix), 200, {"Content-Type": "application/xml"})
        if parsed.path.endswith(".nc"):
            assert request.get_header("If-match") == '"netcdf"'
            return Response(url, netcdf, 200, {"ETag": '"netcdf"'})
        if parsed.path.endswith(".idx"):
            parts = parsed.path.split("/")
            day = parts[1].split(".")[1]
            if "hrrr" in parts[1]:
                cycle = parts[-1].split(".")[1][1:3]
                lead = 0
            else:
                cycle = "18"
                lead = int(parts[-1].split(".")[-2][1:])
            return Response(url, inventory(day + cycle, lead), 200, {})
        requested = request.get_header("Range").removeprefix("bytes=")
        return Response(url, grib, 206, {"Content-Range": f"bytes {requested}/100", "ETag": '"wind"'})

    monkeypatch.setattr(acquire, "urlopen", fixture)
    raw = Path("data/raw/h2")
    lake = {"id": "lake_h2_d2", "scene": "lake_ontario", "date": "2025-09-09"}
    lake_sources = acquire.acquire_noaa(tmp_path, raw, lake)
    for file_number, row in enumerate(lake_sources["current"], 1):
        assert Path(row["local_path"]).name.endswith(f".fields.n{file_number:03}.nc")
    assert [row["valid_utc"][11:13] for row in lake_sources["wind"]] == ["13", "14", "15", "16", "17"]
    assert [row["lead_hours"] for row in lake_sources["current"]] == [-5, -4, -3, -2, -1]
    assert all(row["run_cycle_utc"] == "2025-09-09T18:00:00Z" for row in lake_sources["current"])
    assert len(seen) == 21
    assert len((tmp_path / lake_sources["receipts"][0]).read_text().splitlines()) == len(seen)
    assert acquire.acquire_noaa(tmp_path, raw, lake) == lake_sources
    assert len(seen) == 21, "verified existing sources should avoid unnecessary downloads"
    assert (tmp_path / lake_sources["wind"][0]["local_path"]).read_bytes() == grib + grib
    assert (tmp_path / lake_sources["current"][0]["local_path"]).read_bytes() == netcdf
    assert (tmp_path / lake_sources["wind"][0]["index_path"]).read_bytes() == inventory("2025090913", 0)
    (tmp_path / lake_sources["wind"][0]["index_path"]).write_bytes(b"mismatched")
    with pytest.raises(acquire.AcquisitionError, match="index SHA-256"):
        acquire.acquire_noaa(tmp_path, raw, lake)

    hudson = {"id": "hudson_h2_d2", "scene": "arctic_ocean", "date": "2025-09-12"}
    hudson_sources = acquire.acquire_noaa(tmp_path, raw, hudson)
    assert hudson_sources["current"] == []
    assert [n["lead_hours"] for n in hudson_sources["wind"]] == list(range(3, 34, 3))
    assert all(row["run_cycle_utc"] == "2025-09-11T18:00:00Z" for row in hudson_sources["wind"])
    assert hudson_sources["wind"][0]["valid_utc"] == "2025-09-11T21:00:00Z"
    assert hudson_sources["wind"][-1]["valid_utc"] == "2025-09-13T03:00:00Z"


def test_noaa_requires_a_dedicated_scope_and_bounded_attempts(tmp_path):
    lake = {"id": "lake_h2_d2", "scene": "lake_ontario", "date": "2025-09-09"}
    with pytest.raises(ValueError, match="data/raw/h2"):
        acquire.acquire_noaa(tmp_path, "data/raw/historical", lake)
    with pytest.raises(ValueError, match="one through three"):
        acquire.acquire_noaa(tmp_path, "data/raw/h2", lake, max_attempts=4)

