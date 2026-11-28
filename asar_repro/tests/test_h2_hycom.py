"""Independent toy NetCDF4 and acquisition receipts for the H2 HYCOM contract."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

from netCDF4 import Dataset
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import h2_hycom as h2


BLOCK = {"id": "hudson_h2_d1", "scene": "arctic_ocean", "date": "2025-08-15",
         "seeds": [4101, 4102], "primary": True}


def test_preregistered_exact_native_request_window():
    specs = h2.requests_for(BLOCK)
    assert [len(s["valid_times_utc"]) for s in specs] == [3, 24, 4]
    stamps = [datetime.fromisoformat(stamp) for spec in specs for stamp in spec["valid_times_utc"]]
    assert stamps[0] == datetime(2025, 8, 14, 21, tzinfo=timezone.utc)
    assert stamps[-1] == datetime(2025, 8, 16, 3, tzinfo=timezone.utc)
    assert all(b-a == timedelta(hours=1) for a, b in zip(stamps, stamps[1:]))
    for spec in specs:
        url = urlparse(spec["source_url"])
        assert url.netloc == "ncss.hycom.org"
        assert url.path == "/thredds/ncss/grid/ESPC-D-V02/ice/2025"
        assert parse_qs(url.query)["var"] == ["ssu", "ssv", "sic"]
        assert all(parse_qs(url.query)[k] == [v] for k, v in h2.BOX.items())
        assert parse_qs(url.query)["horizStride"] == ["1"]


def make_chunk(path, times, *, ice=None, different_masks=False):
    start = datetime(2000, 1, 1, tzinfo=timezone.utc)
    with Dataset(path, "w", format="NETCDF4") as ds:
        ds.generating_model = "ESPC-D V02"
        ds.source = "HYCOM native toy"
        ds.createDimension("time", len(times))
        ds.createDimension("lat", 63)
        ds.createDimension("lon", 45)
        t = ds.createVariable("time", "f8", ("time",))
        t.units = "hours since 2000-01-01T00:00:00Z"
        t[:] = [(datetime.fromisoformat(v)-start).total_seconds()/3600 for v in times]
        lat = ds.createVariable("lat", "f8", ("lat",))
        lat.units = "degrees_north"
        lat[:] = 61.52 + .04*np.arange(63)
        lon = ds.createVariable("lon", "f8", ("lon",))
        lon.units = "degrees_east"
        lon[:] = 268 + .08*np.arange(45)
        for name, standard, units in h2.VARIABLES:
            v = ds.createVariable(name, "i2", ("time", "lat", "lon"), fill_value=-30000)
            v.standard_name, v.units = standard, units
            v.scale_factor = np.float32(.0001 if name == "sic" else .001)
            v.add_offset = np.float32(0)
            v.set_auto_maskandscale(False)
            raw = np.full((len(times), 63, 45), 0 if name == "sic" else 200, dtype=np.int16)
            raw[:, 0, 0] = -30000
            if name == "sic" and ice is not None:
                raw[0, 1, 1] = ice
            if name == "ssv" and different_masks:
                raw[0, 2, 2] = -30000
            v[:] = raw
    return path.read_bytes()


@pytest.mark.parametrize("ice,nonzero,unknown", [(None, 0, 0), (1, 1, 0), (-30000, 0, 1)])
def test_decoded_ice_and_wet_mask_are_not_replaced(tmp_path, ice, nonzero, unknown):
    times = h2.requests_for(BLOCK)[0]["valid_times_utc"]
    data = make_chunk(tmp_path / "surface.nc", times, ice=ice)
    if nonzero or unknown:
        with pytest.raises(h2.HycomDataError, match="nonzero or unknown") as exc:
            h2.inspect_hycom(data, times)
        audit = exc.value.audit
    else:
        audit = h2.inspect_hycom(data, times)
        assert audit["ice_max_wet"] == 0
    assert audit["known_wet_samples"] == 3*(63*45-1)
    assert audit["nonzero_ice_wet_samples"] == nonzero
    assert audit["unknown_ice_wet_samples"] == unknown
    assert all(x["unpacking_count"] == 1 and x["mask_preserved"] for x in audit["encoding"].values())


def test_rejects_wrong_valid_time_and_unmatched_vector_masks(tmp_path):
    times = h2.requests_for(BLOCK)[0]["valid_times_utc"]
    data = make_chunk(tmp_path / "misaligned.nc", times, different_masks=True)
    with pytest.raises(h2.HycomDataError, match="valid hours"):
        h2.inspect_hycom(data, times[::-1])
    with pytest.raises(h2.HycomDataError, match="U/V masks"):
        h2.inspect_hycom(data, times)


def setup_project(tmp_path):
    config = tmp_path / "configs"
    config.mkdir()
    (config / "stage7_scenarios.yaml").write_text(
        "scenarios:\n  arctic_ocean:\n    lkp_lon_lat: [-90.6, 62.85]\n"
        "    csp_lon_lat: [-90.447, 62.786]\n", encoding="utf-8"
    )
    return tmp_path / "data/raw/h2/hudson_h2_d1"


def test_acquisition_keeps_every_native_chunk_and_rejection_evidence(tmp_path, monkeypatch):
    raw = setup_project(tmp_path)
    bodies = {
        spec["source_url"]: make_chunk(tmp_path / spec["filename"], spec["valid_times_utc"],
                                       ice=1 if i == 0 else None)
        for i, spec in enumerate(h2.requests_for(BLOCK))
    }
    monkeypatch.setattr(h2, "_download", lambda url: (bodies[url], {"Content-Type": "application/x-netcdf4"}))
    rows = h2.acquire_hycom(tmp_path, raw, BLOCK)
    assert [row["status"] for row in rows] == ["rejected_data", "accepted", "accepted"]
    assert rows[0]["audit"]["nonzero_ice_wet_samples"] == 1
    for row in rows:
        path = tmp_path / row["local_path"]
        assert path.read_bytes() == bodies[row["source_url"]]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
        saved = json.loads((tmp_path / row["receipt_path"]).read_text(encoding="utf-8"))
        assert saved == row
    monkeypatch.setattr(h2, "_download", lambda _url: pytest.fail("Existing receipt must prevent new retrieval"))
    assert h2.acquire_hycom(tmp_path, raw, BLOCK) == rows
    with (tmp_path / rows[0]["local_path"]).open("ab") as body:
        body.write(b"tampered")
    with pytest.raises(h2.HycomRequestError, match="bytes changed"):
        h2.acquire_hycom(tmp_path, raw, BLOCK)


def test_transport_retries_retain_evidence_and_do_not_reset_on_resume(tmp_path, monkeypatch):
    raw = setup_project(tmp_path)
    seen = []

    def failing(url):
        seen.append(url)
        raise TimeoutError("no network response")

    monkeypatch.setattr(h2, "_download", failing)
    monkeypatch.setattr(h2, "sleep", lambda _delay: None)
    for _ in range(2):
        with pytest.raises(h2.HycomRequestError, match="not resolved after 3"):
            h2.acquire_hycom(tmp_path, raw, BLOCK)
    assert len(seen) == 3 and len(set(seen)) == 1
    receipts = sorted((raw / "hycom").glob("*.json"))
    assert [json.loads(p.read_text())["status"] for p in receipts] == ["retryable_transport_error"]*3
    assert not list(raw.rglob("*.nc"))

