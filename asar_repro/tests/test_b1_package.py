"""Regression checks for the manually delivered B1 data."""

from pathlib import Path
import struct
import sys

import numpy as np
import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inventory_historical as inv
from b1_hrrr import simple_values
from verify_lake_b1 import containing_faces, hourly_coverage


def test_simple_packing_bit_order_scales_and_truncation():
    # 3-bit integers 1, 7, 2 straddle bytes. E=-1, D=-1, R=-2.
    header = bytes(5) + struct.pack(">IHfHHBB", 3, 0, -2, 0x8001, 0x8001, 3, 0)
    payload = bytes([0b00111101, 0])
    np.testing.assert_array_equal(simple_values(header, payload, 3), [-15, 15, -10])
    with pytest.raises(ValueError, match="length"):
        simple_values(header, payload[:-1], 3)


def test_unstructured_domain_is_not_its_bounding_box():
    tri = np.array([[0, 1, 2]])
    x = np.array([0.0, 1.0, 0.0])
    y = np.array([0.0, 0.0, 1.0])
    faces = containing_faces(x, y, tri, np.array([[0.2, 0.1], [0.9, 0.9], [-0.2, 0.1]]))
    np.testing.assert_array_equal(faces, [0, -1, -1])


def test_hourly_brackets_cannot_hide_missing_or_duplicate_hour():
    times = [f"2025-08-26T{h}:00:00Z" for h in range(13, 18)]
    bounds = times[::4]
    assert len(hourly_coverage(times, bounds)) == 5
    for wrong in (times[:2] + times[3:], times[:2] + [times[1]] + times[3:]):
        with pytest.raises(ValueError, match="hourly"):
            hourly_coverage(wrong, bounds)


def test_inventory_rechecks_real_package_with_archive_offline(monkeypatch):
    raw = inv.ROOT / "data/raw/historical"
    if not (raw / inv.LAKE_PACKAGE).exists():
        pytest.skip("local B1 data package absent")
    spec = yaml.safe_load((inv.ROOT / "configs/stage7_scenarios.yaml").read_bytes())
    monkeypatch.setattr(inv, "probe", lambda item: dict(url=item[1], status="probe_failed"))
    cases = inv.inventory(spec, raw)
    lake = next(c for c in cases if c["scenario"] == "lake_ontario")
    assert lake["pair_status"] == "verified" and lake["available_at_cst"] is False
    assert len(lake["wind"]["local_files"]) == len(lake["current"]["local_files"]) == 5
    assert lake["wind"]["valid_time_range_utc"] == lake["current"]["valid_time_range_utc"]
    assert lake["wind"]["vector_basis"] == "grid_relative"
    assert all(row["full_object_sha256"] is None for row in lake["wind"]["local_files"])
    assert all(row["full_object_sha256"] == row["sha256"] for row in lake["current"]["local_files"])
    assert all(
        g == dict(total=289, wet=221, outside_mesh=68, dry=0)
        for g in lake["current"]["spatial_coverage"]["grid_centres_by_hour"]
    )
