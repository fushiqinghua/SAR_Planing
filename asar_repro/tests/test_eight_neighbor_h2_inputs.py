"""Local H2 time, native decoding, qualification and mass invariants."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from netCDF4 import Dataset
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from h2_protocol import DEFAULT_CONFIG, choose_blocks, instances_for, read, registered_blocks
from asar_repro.h2_forcing import (
    DataIneligible, _hycom_vectors, _source_file, expected_clock, mission_config,
)
from asar_repro.h2_inputs import _validate_ledger
from asar_repro.historical_drift import axes, utc_label
from asar_repro.physical_followup_data import _sha


@pytest.fixture
def registration():
    config = read(DEFAULT_CONFIG)
    return config, registered_blocks(config)


def test_native_axis_includes_tail_with_registered_seed_and_real_times(registration):
    _, blocks = registration
    by_id = {row["id"]: row for row in blocks}
    lake = by_id["lake_h2_d1"]
    hudson = by_id["hudson_h2_d1"]
    times, current, cycles, leads = expected_clock(lake)
    assert times == current == cycles
    assert [time.hour for time in current] == [13, 14, 15, 16, 17]
    assert leads == (0,) * 5
    times, current, cycles, leads = expected_clock(hudson)
    assert len(times) == 11 and len(current) == 31
    assert set(cycles) == {datetime(2025, 8, 14, 18, tzinfo=timezone.utc)}
    assert current[-1] - current[0] == timedelta(hours=30)
    assert leads == tuple(range(3, 34, 3))
    for block, tail in ((lake, "2025-08-12T15:53:00Z"), (hudson, "2025-08-16T00:48:00Z")):
        case, = instances_for([dict(block, seeds=block["seeds"][:1])])
        cfg = mission_config(case)
        native, observation = axes(cfg)
        assert utc_label(native[-1]) == tail
        assert native[-1] > observation[-1]
        assert cfg["seed"] == case["seed"] and cfg["particles"] == 500
        assert cfg["audit_q"] == 0.78 and cfg["forcing_kind"] == "historical_real"


def test_backup_sequence_requires_completed_primary_qualification(registration):
    config, blocks = registration
    primary = [dict(block_id=block["id"], status="eligible") for block in blocks if block["primary"]]
    selected, replacements, waiting = choose_blocks(config, primary)
    assert len(selected) == 6 and not replacements and not waiting
    primary[0]["status"] = "blocked"
    selected, replacements, waiting = choose_blocks(config, primary + [
        dict(block_id="lake_h2_alt1", status="eligible"),
    ])
    assert len(selected) == 5 and not replacements and waiting == ["lake_h2_d1"]
    primary[0]["status"] = "ineligible"
    selected, replacements, waiting = choose_blocks(config, primary + [
        dict(block_id="lake_h2_alt1", status="ineligible"),
        dict(block_id="lake_h2_alt2", status="eligible"),
    ])
    assert len(selected) == 6 and not waiting
    assert replacements == {"lake_h2_alt2": "lake_h2_d1"}
    assert instances_for([selected[2]])[0]["seed"] == 3501


def test_duplicate_audits_are_not_a_six_date_chain(registration):
    config, _ = registration
    item = dict(block_id="lake_h2_d1", status="eligible")
    with pytest.raises(ValueError, match="Duplicate"):
        choose_blocks(config, [item, item])


def _packed_fixture(path, *, mismatch=False, direction_flip=False, empty=False):
    mappings = (
        ("ssu", "eastward_sea_water_velocity", "m/s"),
        ("ssv", "northward_sea_water_velocity", "m/s"),
        ("sic", "sea_ice_area_fraction", "1"),
    )
    with Dataset(path, "w") as dataset:
        for name, size in zip(("time", "lat", "lon"), (2, 2, 2), strict=True):
            dataset.createDimension(name, size)
        for name, direction, units in mappings:
            variable = dataset.createVariable(name, "i2", ("time", "lat", "lon"), fill_value=-32768)
            variable.standard_name = ("northward_sea_water_velocity" if name == "ssu" and direction_flip
                                      else direction)
            variable.units = units
            variable.scale_factor = 0.02
            variable.add_offset = 0 if name == "sic" else 0.5
            # Write raw integer values so the native CF decode is independently checkable.
            variable.set_auto_maskandscale(False)
            if name == "sic":
                payload = [[[0, 0], [-32768, -32768]], [[0, 10], [0, -32768]]]
            else:
                payload = [[[25, 10], [1, -32768]], [[25, 10], [1, -32768]]]
                if mismatch and name == "ssu":
                    payload[0][0][0] = -32768
                if empty:
                    payload[0] = [[-32768, -32768], [-32768, -32768]]
            variable[:] = payload


def test_cf_unpack_is_once_and_unknown_nonzero_ice_count_only_at_water(tmp_path):
    path = tmp_path / "packing.nc"
    _packed_fixture(path)
    with Dataset(path) as dataset:
        uv, ice = _hycom_vectors(dataset)
    assert uv.shape == (2, 2, 2, 2)
    np.testing.assert_allclose(uv[0, 0, :, 0], [1.0, 0.7])
    assert np.isnan(uv[0, 1, 1]).all()
    assert ice == dict(wet_counts=[3, 3], unknown_ice_counts=[1, 0], nonzero_ice_counts=[0, 1])


@pytest.mark.parametrize(
    ("case", "message"), [
        ("mismatch", "masks disagree"),
        ("direction_flip", "direction or units"),
        ("empty", "no finite paired water currents"),
    ],
)
def test_invalid_native_vectors_block_qualification(tmp_path, case, message):
    path = tmp_path / "invalid.nc"
    _packed_fixture(path, **{case: True})
    with Dataset(path) as dataset, pytest.raises(DataIneligible, match=message):
        _hycom_vectors(dataset)


def test_input_hash_and_qualified_raw_path_are_required(tmp_path):
    location = tmp_path / "data/raw/h2/lake_h2_d1"
    location.mkdir(parents=True)
    obj = location / "native.nc"
    obj.write_bytes(b"original bytes")
    row = dict(local_path=obj.relative_to(tmp_path).as_posix(), sha256=_sha(obj), bytes=obj.stat().st_size)
    block = {"id": "lake_h2_d1"}
    assert _source_file(tmp_path, block, row) == obj
    obj.write_bytes(b"modified bytes")
    with pytest.raises(ValueError, match="SHA-256"):
        _source_file(tmp_path, block, row)
    row["local_path"] = "data/raw/historical/native.nc"
    with pytest.raises(ValueError, match="escaped"):
        _source_file(tmp_path, block, row)


def test_mass_verification_preserves_outside_unknown_and_land():
    cfg = dict(budget=0, particles=8, grid_rows_cols=[2, 2])
    row = dict(step=0, max_error=0, prior_total=1, Pd=0, M=1, particles=8)
    categories = {"searchable": .5, "land": .125, "outside": .125, "inactive": .125, "unknown": .125}
    for prefix in ("prior", "posterior"):
        row.update({f"{prefix}_{name}": mass for name, mass in categories.items()})
    data = {"raw_cell_ids": np.zeros((1, 8), dtype=int), "raw_lon": np.zeros((1, 8))}
    _validate_ledger([row], cfg, data)
    row["posterior_unknown"] = 0
    with pytest.raises(ValueError, match="mass not preserved"):
        _validate_ledger([row], cfg, data)
