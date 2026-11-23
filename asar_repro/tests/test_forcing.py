"""Offline CF and mask checks for the B2 forcing stage."""

from datetime import timedelta
import json

import numpy as np
from netCDF4 import Dataset
from pyproj import Proj
import pytest

from asar_repro.forcing import (
    CF_NAMES,
    VARIABLES,
    FaceMesh,
    HistoricalForcing,
    SurfaceField,
    load_cf_surface,
    load_historical_forcing,
    utc_datetime,
)
from asar_repro.historical_reader import build_opendrift_readers
from asar_repro.hrrr import geographic_wind


START = utc_datetime("2025-08-26T13:00:00Z")
HOUR = timedelta(hours=1)


@pytest.fixture
def cf_file(tmp_path):
    path = tmp_path / "synthetic.nc"
    with Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.forcing_kind = "synthetic_cf"
        for name, size, data, units in [
            ("time", 4, np.arange(4), "hours since 2025-08-26 13:00:00"),
            ("lat", 3, [45, 44, 43], "degrees_north"),
            ("lon", 3, [179, 180, -179], "degrees_east"),
        ]:
            ds.createDimension(name, size)
            var = ds.createVariable(name, "f8", (name,))
            var[:], var.units = data, units
        ds["time"].time_zone = "UTC"
        for name, value, units in [
            (CF_NAMES["wind"][0], 1, "m/s"),
            (CF_NAMES["wind"][1], -2, "m/s"),
            (CF_NAMES["current"][0], 20, "cm/s"),
            (CF_NAMES["current"][1], 10, "cm s-1"),
        ]:
            var = ds.createVariable(name, "f8", ("time", "lat", "lon"), fill_value=-9999.0)
            var[:], var.standard_name, var.units = value, name, units
    return path


def test_cf_values_and_opendrift_api(cf_file):
    wind, current = (load_cf_surface(cf_file, role) for role in VARIABLES)
    bundle = HistoricalForcing(wind, current, (START, START + 3 * HOUR), "synthetic_cf")
    for reader, role, expected in zip(
        build_opendrift_readers(bundle), VARIABLES, ([1, -2], [0.2, 0.1])
    ):
        assert reader.variables == list(VARIABLES[role])
        data, _ = reader.get_variables_interpolated(
            reader.variables,
            time=START.replace(tzinfo=None),
            lon=np.array([-179.5]),
            lat=np.array([44.5]),
            z=np.zeros(1),
        )
        np.testing.assert_allclose([data[v][0] for v in reader.variables], expected)


def test_reversed_latitude_dateline_and_time_interpolation(cf_file):
    with Dataset(cf_file, "a") as ds:
        ds["eastward_wind"][:] = (
            np.arange(4)[:, None, None]
            + 2 * ds["lat"][:][None, :, None]
            + np.arange(3)[None, None, :]
        )
    wind = load_cf_surface(cf_file, "wind")
    # Native longitude offset 1.5, latitude 44.5, time offset 0.5.
    np.testing.assert_allclose(
        wind.sample(START + HOUR / 2, [-179.5, 180.5], 44.5), [[91, -2], [91, -2]]
    )
    for time, lon, lat, status in [
        (START, -178, 44, "outside_grid"),
        (START - HOUR, 180, 44, "outside_time"),
        (START, 180, 91, "invalid_position"),
    ]:
        uv, state = wind.probe(time, lon, lat)
        assert state.tolist() == [status] and np.isnan(uv).all()
        with pytest.raises(ValueError, match=status):
            wind.sample(time, lon, lat)


def test_fill_value_masks_only_positive_weight_corners(cf_file):
    with Dataset(cf_file, "a") as ds:
        ds["northward_wind"][1, 1, 1] = -9999
    w = load_cf_surface(cf_file, "wind")
    np.testing.assert_array_equal(w.sample(START, 180, 44), [[1, -2]])
    assert w.probe(START + HOUR / 2, 180, 44)[1][0] == "missing_component"
    assert w.probe(START + HOUR, 180.5, 44.5)[1][0] == "missing_component"
    np.testing.assert_array_equal(w.sample(START + HOUR, -179, 44), [[1, -2]])


@pytest.mark.parametrize(
    ("field", "message"),
    [("units", "units"), ("utc", "UTC"), ("gap", "gap"), ("duplicate", "UTC time")],
)
def test_invalid_cf_metadata(cf_file, field, message):
    with Dataset(cf_file, "a") as ds:
        if field == "units":
            ds["eastward_wind"].units = "knots"
        elif field == "utc":
            ds["time"].delncattr("time_zone")
        elif field == "gap":
            ds["time"][:] = [0, 1, 3, 4]
        else:
            ds["time"][:] = [0, 1, 1, 2]
    with pytest.raises(ValueError, match=message):
        load_cf_surface(cf_file, "wind")


def test_mapped_variables_window_and_empty_file(cf_file, tmp_path):
    with pytest.raises(ValueError, match="mapping"):
        load_cf_surface(cf_file, "wind", CF_NAMES["wind"][::-1])
    with pytest.raises(ValueError, match="missing CF"):
        load_cf_surface(cf_file, "wind", ("bad", "northward_wind"))
    empty = tmp_path / "empty.nc"
    empty.touch()
    with pytest.raises((OSError, ValueError)):
        load_cf_surface(empty, "wind")
    wind, current = (load_cf_surface(cf_file, role) for role in VARIABLES)
    with pytest.raises(ValueError, match="lacks required UTC"):
        HistoricalForcing(wind, current, (START, START + 4 * HOUR), "synthetic_cf")
    with pytest.raises(ValueError, match="source SHA-256"):
        HistoricalForcing(wind, current, (START, START + HOUR), "historical_real")


def test_real_manifest_without_sha_fails_before_loading(tmp_path):
    from asar_repro.scenarios import digest

    config = tmp_path / "configs/stage7_scenarios.yaml"
    config.parent.mkdir()
    config.write_text("fixture")
    manifest = tmp_path / "historical.json"
    manifest.write_text(
        json.dumps(
            {
                "config_sha256": digest(config),
                "scenarios": [
                    {
                        "scenario": "lake_ontario",
                        "pair_status": "verified",
                        "forcing_kind": "historical_real",
                        "verification_scope": "B1_raw_files",
                        "wind": {"local_files": [{"local_path": "fake"}]},
                    }
                ],
            }
        )
    )
    with pytest.raises(ValueError, match="source SHA-256"):
        load_historical_forcing(manifest, tmp_path)
    content = json.loads(manifest.read_text())
    row = dict(local_path="fake", sha256="0" * 64, valid_utc=START.isoformat())
    lake = content["scenarios"][0]
    lake.update(
        wind=dict(local_files=[row]),
        current=dict(local_files=[row]),
        requested_window_utc=[START.isoformat(), (START + HOUR).isoformat()],
    )
    manifest.write_text(json.dumps(content))
    (tmp_path / "fake").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="source SHA-256 mismatch"):
        load_historical_forcing(manifest, tmp_path)


def test_native_face_status_and_wet_time_bracket():
    xy = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    mesh = FaceMesh(xy, np.array([[0, 1, 2]]), lambda lon, lat: (lon, lat))
    field = SurfaceField(
        "current", (START, START + HOUR), mesh, np.array([[[0.2, 0.1, 1]], [[2, 3, 0]]]), [], {}
    )
    uv, status = field.probe(START, [0.1, 0.9], [0.1, 0.9])
    assert status.tolist() == ["ok", "outside_mesh"]
    np.testing.assert_array_equal(uv[0], [0.2, 0.1])
    assert field.probe(START + HOUR / 2, 0.1, 0.1)[1][0] == "dry"


def test_lambert_rotation_against_tangent_cone_formula():
    proj = Proj(proj="lcc", R=6371229, lat_0=38.5, lon_0=-97.5, lat_1=38.5, lat_2=38.5)
    lon = np.array([-97.5, -76.5, -118.5])
    angle = np.deg2rad(lon + 97.5) * np.sin(np.deg2rad(38.5))
    u, v = geographic_wind(proj, lon, np.full(3, 44.21), np.tile([1, 0], (3, 1))).T
    np.testing.assert_allclose(u, np.cos(angle), atol=1e-9)
    np.testing.assert_allclose(v, -np.sin(angle), atol=1e-9)


def test_masked_open_drift_environment_has_no_velocity_fallback(cf_file):
    from opendrift.models.leeway import Leeway
    from asar_repro.historical_reader import attach_historical_readers

    wind, current = (load_cf_surface(cf_file, role) for role in VARIABLES)
    bundle = HistoricalForcing(wind, current, (START, START + HOUR), "synthetic_cf")
    model = Leeway(loglevel=50)
    model.set_config("environment:fallback:x_wind", 42)
    readers = attach_historical_readers(model, bundle)
    model.env.finalize()
    names = [v for reader in readers for v in reader.variables]
    data, _, missing = model.env.get_environment(
        names,
        START.replace(tzinfo=None),
        np.array([180.0, 175.0]),
        np.array([44.0, 44.0]),
        np.zeros(2),
    )
    assert model.get_config("environment:fallback:x_wind") is None
    assert missing.tolist() == [False, True]
    np.testing.assert_allclose([data[name][0] for name in names], [1, -2, 0.2, 0.1])
    assert all(np.isnan(data[name][1]) for name in names)
