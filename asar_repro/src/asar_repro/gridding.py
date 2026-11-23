"""Metric grid mapping and per-particle unconditional undetected mass."""

from dataclasses import dataclass, field

import numpy as np
from pyproj import CRS, Transformer

from .grid import GridGraph, integer


@dataclass
class ParticleGrid:
    graph: GridGraph
    center_lon_lat: tuple
    width_m: float
    projection: Transformer = field(init=False)

    def __post_init__(self):
        if not np.isfinite(self.width_m) or self.width_m <= 0:
            raise ValueError("cell width must be positive and finite")
        lon, lat = self.center_lon_lat
        crs = CRS.from_proj4(f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m")
        self.projection = Transformer.from_crs("EPSG:4326", crs, always_xy=True)

    @property
    def special(self):
        return {name: self.graph.size + i for i, name in enumerate(("land", "outside", "inactive", "unknown"))}

    def assign(self, frames):
        x, y = self.projection.transform(frames.lon, frames.lat)
        col = np.floor(x / self.width_m + self.graph.cols / 2)
        from_south = np.floor(y / self.width_m + self.graph.rows / 2)
        inside = (col >= 0) & (col < self.graph.cols) & (from_south >= 0) & (from_south < self.graph.rows)
        valid = np.isfinite(x) & np.isfinite(y)
        sp = self.special
        cells = np.full(frames.lon.shape, sp["unknown"], dtype=np.int32)
        for code, name in frames.flags.items():
            mask = frames.status == code
            if name == "active":
                wet = mask & (frames.land == 0) & valid
                cells[wet & ~inside] = sp["outside"]
                water = wet & inside
                cells[water] = ((self.graph.rows - 1 - from_south[water]) * self.graph.cols + col[water])
                cells[mask & (frames.land == 1)] = sp["land"]
            elif name in ("stranded", "outside"):
                cells[mask] = sp["land" if name == "stranded" else "outside"]
            else:
                cells[mask] = sp["inactive"]
        return cells


def particle_step(grid, cells, weights, vertex=None, q=0.0):
    """Return fresh ID-aligned posterior weights and cell totals including special bins."""
    cells, weights = np.asarray(cells), np.asarray(weights, dtype=np.float64)
    n_bins = grid.graph.size + len(grid.special)
    if (cells.ndim != 1 or weights.shape != cells.shape or cells.dtype.kind not in "iu"
            or np.any(cells < 0) or np.any(cells >= n_bins)):
        raise ValueError("invalid particle cell IDs or mismatched weights")
    if not np.all(np.isfinite(weights)) or np.any(weights < 0) or weights.sum() > 1 + 1e-12:
        raise ValueError("invalid undetected weights")
    if not np.isfinite(q) or not 0 <= q <= 1:
        raise ValueError("q must be a finite probability")
    posterior = weights.copy()
    if vertex is not None:
        vertex = integer(vertex, "visited vertex")
        grid.graph.coordinates(vertex)
        posterior[cells == vertex] *= 1 - q
    return posterior, np.bincount(cells, weights=posterior, minlength=n_bins)
