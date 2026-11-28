"""P2/H3 registration, original-byte provenance, and native decode regression tests."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import sys
from types import SimpleNamespace
from urllib.parse import unquote

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from h3_acquire import wind_requests
from h3_hycom_dap import CF_EPOCH, dap_url, packed_product, time_axis, unpack
from h3_protocol import REGISTRY, ROOT, choose_dates, read
from prepare_eight_neighbor_h3 import _audit_block, case_evidence, load_h3_input
from asar_repro.h3_forcing import load_h3_forcing, verify_file


@pytest.fixture
def blocks():
    return read(ROOT / REGISTRY)["blocks"]


def _eligible(blocks):
    return [dict(block_id=block["id"], status="eligible") for block in blocks if block["primary"]]


def test_h3_wind_inventory_uses_only_registered_native_products_and_cycles(blocks):
    lake, hudson = blocks[0], blocks[3]
    hrrr, gfs = wind_requests(lake), wind_requests(hudson)
    assert [(product, cycle.hour, lead) for product, _, cycle, lead in hrrr] == [
        ("HRRR", hour, 0) for hour in range(13, 18)
    ]
    assert all("hrrr.20250805/conus" in url and url.endswith("f00.grib2") for _, url, _, _ in hrrr)
    assert [(product, cycle.hour, lead) for product, _, cycle, lead in gfs] == [
        ("GFS", 18, lead) for lead in range(3, 34, 3)
    ]
    assert all("gfs.20250807/18/atmos/" in url for _, url, _, _ in gfs)


def test_registered_dates_are_selected_before_any_route_and_without_particle_bias(blocks):
    records = [dict(row, J=60, Pd=0, outside_mass=1) for row in _eligible(blocks)]
    chosen, replacements, waiting, exhausted = choose_dates(blocks, records)
    assert chosen == blocks[:6]
    assert not replacements and not waiting and not exhausted


def test_transport_failure_does_not_consume_or_open_a_fallback(blocks):
    records = _eligible(blocks)
    records[3]["status"] = "blocked"
    chosen, replacements, waiting, exhausted = choose_dates(blocks, records + [
        dict(block_id="hudson_h3_f1", status="eligible"),
    ])
    assert len(chosen) == 5 and not replacements and not exhausted
    assert waiting == ["hudson_h3_d1"]


def test_first_ineligible_fallback_opens_second_for_same_primary(blocks):
    records = _eligible(blocks)
    records[0]["status"] = "ineligible"
    first = dict(block_id="lake_h3_f1", status="ineligible")
    second = dict(block_id="lake_h3_f2", status="eligible")
    assert choose_dates(blocks, records)[2] == ["lake_h3_f1"]
    assert choose_dates(blocks, records + [second])[2] == ["lake_h3_f1"]
    assert choose_dates(blocks, records + [first])[2] == ["lake_h3_f2"]
    chosen, replacements, waiting, exhausted = choose_dates(blocks, records + [first, second])
    assert chosen[0]["id"] == "lake_h3_f2" and chosen[0]["seeds"] == [3801, 3802]
    assert replacements == {"lake_h3_f2": "lake_h3_d1"} and not waiting and not exhausted


def test_dates_exhaust_in_fixed_order_without_borrowing_from_other_region(blocks):
    records = _eligible(blocks)
    records[0]["status"] = "ineligible"
    chosen, replacements, waiting, exhausted = choose_dates(blocks, records + [
        dict(block_id=identity, status="ineligible") for identity in ("lake_h3_f1", "lake_h3_f2")
    ])
    assert len(chosen) == 5 and not replacements and not waiting
    assert exhausted == ["lake_h3_d1"]
    with pytest.raises(ValueError, match="Unexpected H3 qualification"):
        choose_dates(blocks, records + [records[0]])


@pytest.mark.parametrize(("status", "error", "expected"), [
    ("blocked", "socket timeout", "blocked"),
    ("ineligible", "registered nowcast object absent from archive", "ineligible"),
])
def test_acquisition_states_enter_qualification_with_distinct_meanings(tmp_path, blocks, monkeypatch,
                                                                    status, error, expected):
    import prepare_eight_neighbor_h3 as preparation

    monkeypatch.setattr(preparation, "_capture", lambda *_: (
        dict(status=status, reason="official_evidence", error=error), {},
    ))
    row = _audit_block(tmp_path, blocks[0], "fixture")
    assert row["status"] == expected and row["details"] == error


def test_raw_h3_bytes_cannot_be_replaced_by_h2_or_changed(tmp_path, blocks):
    block = blocks[0]
    original = b"verified fixture"
    checksum = sha256(original).hexdigest()
    good = Path("data/raw/h3") / block["id"] / "source.nc"
    bad = Path("data/raw/h2") / "lake_h2_d1/source.nc"
    for name in good, bad:
        (tmp_path / name).parent.mkdir(parents=True)
        (tmp_path / name).write_bytes(original)
    assert verify_file(tmp_path, block, good, checksum, len(original)) == tmp_path / good
    with pytest.raises(ValueError, match="outside"):
        verify_file(tmp_path, block, bad, checksum)
    (tmp_path / good).write_bytes(b"shifted fixture!")
    with pytest.raises(ValueError, match="SHA-256"):
        verify_file(tmp_path, block, good, checksum)
    with pytest.raises(ValueError, match="different date"):
        load_h3_forcing(tmp_path, block, dict(block_id=blocks[1]["id"],
                                            scene=block["scene"], date=block["date"]))


def test_reader_preserves_native_clock_and_qualifies_only_covered_water(blocks, monkeypatch, tmp_path):
    import asar_repro.h3_forcing as forcing

    block = blocks[0]
    native = forcing.expected_clock(block)[0]
    sources = [{"local_path": "fixture", "sha256": "a" * 64}]
    manifest = dict(block_id=block["id"], date=block["date"], scene=block["scene"],
                    wind=sources, current=sources)
    field = dict(times=native, metadata={}, values=np.zeros((5, 2, 2, 2)), sources=sources)
    wind = SimpleNamespace(role="wind", **field)
    current = SimpleNamespace(role="current", **field)
    wind.probe = current.probe = lambda *_: (np.zeros((2, 2)), np.array(["ok", "ok"]))
    monkeypatch.setattr(forcing, "_wind_inventory", lambda *_: None)
    monkeypatch.setattr(forcing, "_lake_inventory", lambda *_: None)
    monkeypatch.setattr(forcing, "_wind", lambda *_: wind)
    monkeypatch.setattr(forcing, "_current", lambda *_: current)
    _, report = load_h3_forcing(tmp_path, block, manifest)
    assert report["status"] == "eligible"
    assert report["native_window_utc"] == ["2025-08-05T14:45:00Z", "2025-08-05T15:53:00Z"]
    assert report["fields"]["current"]["native_valid_times_utc"][0] == "2025-08-05T13:00:00Z"
    current.probe = lambda *_: (np.zeros((2, 2)), np.array(["ok", "land"]))
    with pytest.raises(forcing.DataIneligible, match="unavailable at LKP/CSP"):
        load_h3_forcing(tmp_path, block, manifest)


def test_archive_seed_must_bind_h3_manifest_and_frozen_source(tmp_path, blocks):
    block = blocks[0]
    case = dict(id="lake_h3_d1_s3401", block_id=block["id"])
    (tmp_path / "method_lock.json").write_bytes(b"method lock")
    (tmp_path / "date_lock.json").write_bytes(b"date lock")
    expected = case_evidence(tmp_path, case, dict(block_id=block["id"], manifest_sha256="qualified source"))
    destination = tmp_path / "inputs" / case["id"]
    destination.mkdir(parents=True)
    (destination / "manifest.json").write_text('{"evidence":{"study":"h2"}}', encoding="utf-8")
    with pytest.raises(ValueError, match="outside the frozen H3"):
        load_h3_input(tmp_path, case, expected, "heading_square")


def test_dap_index_is_obtained_from_native_clock_with_noon_start():
    start = datetime(2025, 1, 1, 12, tzinfo=timezone.utc)
    hour = int((start - CF_EPOCH).total_seconds() // 3600)
    text = ("Dataset { Float64 time[time = 8760]; } ESPC-D-V02/ice/2025;\n---\ntime[8760]\n"
            + ", ".join(str(x) for x in range(hour, hour + 8760)))
    axis = time_axis(text.encode())
    expected = [start + timedelta(hours=index) for index in (28, 29, 30)]
    assert "time[28:1:30]" in unquote(dap_url([item.isoformat() for item in expected], axis))
    with pytest.raises(ValueError, match="consecutive"):
        dap_url([expected[0].isoformat(), expected[2].isoformat()], axis)
    with pytest.raises(ValueError, match="consecutive"):
        dap_url([(start - timedelta(hours=12)).isoformat()], axis)


def test_dap_native_packing_and_mask_are_checked_before_scale():
    parts = ["Float64 lat[lat = 63];", "Float64 lon[lon = 45];", "Float64 time[time = 1];"]
    for name in ("ssu", "ssv", "sic"):
        parts.append(f"Structure {{ Int16 {name}[time = 1][lat = 63][lon = 45]; }} {name};")
    header = f"Dataset {{ {' '.join(parts)} }} ESPC-D-V02/ice/2025;\nData:\n".encode()
    values = [np.arange(63, dtype=">f8"), np.arange(45, dtype=">f8"), np.array([12.0], dtype=">f8")]
    velocity = np.zeros(63 * 45, dtype=">i4")
    velocity[:3] = [-30000, 75, -63]
    values.extend([velocity, velocity, velocity])
    body = b"".join(np.array([x.size, x.size], dtype=">u4").tobytes() + x.tobytes() for x in values)
    fields = packed_product(header + body, 1)
    seen = unpack(fields["ssu"], dict(fill=-30000, scale=np.float32(.001), add=np.float32(0)))
    assert np.isnan(seen[0, 0, 0])
    np.testing.assert_allclose(seen[0, 0, 1:3], [.075, -.063], atol=1e-8)
    with pytest.raises(ValueError, match="count or byte length"):
        packed_product(header + body[:-1], 1)
    with pytest.raises(ValueError, match="Extra bytes"):
        packed_product(header + body + b"\x00", 1)
