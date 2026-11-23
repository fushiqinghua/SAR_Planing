"""Expose the audited surface samplers through the local OpenDrift reader API."""

from datetime import timezone

import numpy as np
from opendrift.readers.basereader.continuous import ContinuousReader

from .forcing import VARIABLES


class SurfaceReader(ContinuousReader):
    def __init__(self, field):
        self.field = field
        self.name = f"asar_{field.role}"
        self.variables = list(VARIABLES[field.role])
        self.proj4 = "+proj=latlong +datum=WGS84"
        self.xmin, self.xmax = -180, 180
        self.ymin, self.ymax = -90, 90
        # OpenDrift passes naive UTC datetimes on this interface.
        self.start_time = field.times[0].replace(tzinfo=None)
        self.end_time = field.times[-1].replace(tzinfo=None)
        self.time_step = None
        super().__init__()
        self.variables = list(VARIABLES[field.role])
        self.derived_variables.clear()

    def get_variables(self, variables, time=None, x=None, y=None, z=None):
        if z is not None and np.any(np.asarray(z) != 0):
            raise ValueError("historical reader only supplies surface values")
        utc = time.replace(tzinfo=timezone.utc) if time.tzinfo is None else time
        uv, _ = self.field.probe(utc, x, y)
        mapping = dict(zip(VARIABLES[self.field.role], uv.T))
        return dict(time=time, x=x, y=y, z=z, **{name: mapping[name] for name in variables})

    def _get_variables_interpolated_(
        self, variables, profiles, profiles_depth, time, reader_x, reader_y, z
    ):
        if profiles:
            raise ValueError("historical surface reader has no vertical profiles")
        return self.get_variables(variables, time, reader_x, reader_y, z), None


def build_opendrift_readers(bundle):
    """Provide disjoint wind and current variable lists with geographic directions."""
    return SurfaceReader(bundle.wind), SurfaceReader(bundle.current)


def attach_historical_readers(model, bundle):
    """Configure a fresh surface model for strict velocities and explicit all-water coastline."""
    if model.env.readers:
        raise ValueError("historical wind and current require a fresh reader registry")
    if bundle.shoreline_policy != "allwater":
        raise ValueError("unknown shoreline policy")
    for names in VARIABLES.values():
        for variable in names:
            model.set_config(f"environment:fallback:{variable}", None)
            model.set_config(f"environment:constant:{variable}", None)
    model.set_config("general:use_auto_landmask", False)
    model.set_config("environment:fallback:land_binary_mask", 0)
    model.set_config("environment:constant:land_binary_mask", None)
    readers = build_opendrift_readers(bundle)
    model.add_reader(list(readers))
    return readers
