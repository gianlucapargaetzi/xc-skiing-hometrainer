# Utils/route.py – GPX-Strecke: Position, Höhe und Steigung entlang der gefahrenen Distanz

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, replace
from pathlib import Path
from typing import List, Optional

import numpy as np

EARTH_RADIUS_M = 6371000.0
GRID_STEP_M = 10.0          # Höhenprofil wird auf ein 10-m-Raster interpoliert
SMOOTH_WINDOW_M = 60.0      # GPS-Höhenrauschen glätten
SLOPE_BASE_M = 100.0        # Steigung über ±50 m (wie eine Langlauf-Steigungsangabe)
MAX_ABS_SLOPE_PERCENT = 25.0
MIN_SECTION_M = 200.0       # kürzester wählbarer Abschnitt


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


@dataclass
class RoutePosition:
    distance_m: float
    lat: float
    lon: float
    elevation_m: float
    slope_percent: float
    bearing_deg: float
    finished: bool


class Route:
    def __init__(self, name: str, lats, lons, elevations):
        if len(lats) < 2:
            raise ValueError("Die Strecke braucht mindestens zwei Punkte.")
        self.name = name

        # Doppelte Punkte (Stillstand in der Aufzeichnung) entfernen
        pts = [(lats[0], lons[0], elevations[0])]
        for la, lo, el in zip(lats[1:], lons[1:], elevations[1:]):
            if haversine_m(pts[-1][0], pts[-1][1], la, lo) >= 0.5:
                pts.append((la, lo, el))
        if len(pts) < 2:
            raise ValueError("Die Strecke hat keine Ausdehnung.")

        self._lat = np.array([p[0] for p in pts])
        self._lon = np.array([p[1] for p in pts])
        ele = np.array([p[2] for p in pts])
        seg = [haversine_m(a[0], a[1], b[0], b[1]) for a, b in zip(pts, pts[1:])]
        self._dist = np.concatenate([[0.0], np.cumsum(seg)])
        self.length_m = float(self._dist[-1])

        # Höhe auf festes Raster, geglättet; Steigung als zentrale Differenz über SLOPE_BASE_M
        self._grid = np.arange(0.0, self.length_m + GRID_STEP_M, GRID_STEP_M)
        ele_grid = np.interp(self._grid, self._dist, ele)
        n = max(1, int(round(SMOOTH_WINDOW_M / GRID_STEP_M)))
        if n > 1 and len(ele_grid) > n:
            kernel = np.ones(n) / n
            padded = np.pad(ele_grid, (n // 2, n - 1 - n // 2), mode="edge")
            ele_grid = np.convolve(padded, kernel, mode="valid")
        self._ele_grid = ele_grid
        half = max(1, int(round(SLOPE_BASE_M / 2 / GRID_STEP_M)))
        idx = np.arange(len(ele_grid))
        lo = np.clip(idx - half, 0, len(ele_grid) - 1)
        hi = np.clip(idx + half, 0, len(ele_grid) - 1)
        span = (hi - lo) * GRID_STEP_M
        slope = np.where(span > 0, (ele_grid[hi] - ele_grid[lo]) / np.maximum(span, 1e-9) * 100.0, 0.0)
        self._slope_grid = np.clip(slope, -MAX_ABS_SLOPE_PERCENT, MAX_ABS_SLOPE_PERCENT)

        self.elevation_gain_m = float(np.sum(np.clip(np.diff(ele_grid), 0, None)))
        self.elevation_loss_m = float(np.sum(np.clip(-np.diff(ele_grid), 0, None)))

    # ---------------------- Laden ----------------------
    @classmethod
    def from_gpx(cls, path) -> "Route":
        path = Path(path)
        root = ET.parse(path).getroot()
        ns = root.tag.split("}")[0].strip("{") if root.tag.startswith("{") else ""
        q = (lambda t: f"{{{ns}}}{t}") if ns else (lambda t: t)

        lats, lons, eles = [], [], []
        points = list(root.iter(q("trkpt"))) or list(root.iter(q("rtept")))
        for p in points:
            ele = p.find(q("ele"))
            if ele is None or ele.text is None:
                continue
            lats.append(float(p.get("lat")))
            lons.append(float(p.get("lon")))
            eles.append(float(ele.text))
        if not lats:
            raise ValueError(f"{path.name}: keine Trackpunkte mit Höhenangabe gefunden.")

        return cls(path.stem, lats, lons, eles)

    # ---------------------- Abfragen ----------------------
    def slope_at(self, distance_m: float) -> float:
        d = min(max(distance_m, 0.0), self.length_m)
        return float(np.interp(d, self._grid, self._slope_grid))

    def elevation_at(self, distance_m: float) -> float:
        d = min(max(distance_m, 0.0), self.length_m)
        return float(np.interp(d, self._grid, self._ele_grid))

    def position_at(self, distance_m: float) -> RoutePosition:
        finished = distance_m >= self.length_m
        d = min(max(distance_m, 0.0), self.length_m)
        lat = float(np.interp(d, self._dist, self._lat))
        lon = float(np.interp(d, self._dist, self._lon))
        # Blickrichtung über die nächsten ~30 m (ruhiger als von Punkt zu Punkt)
        ahead = min(d + 30.0, self.length_m)
        back = max(ahead - 30.0, 0.0)
        bearing = bearing_deg(
            float(np.interp(back, self._dist, self._lat)), float(np.interp(back, self._dist, self._lon)),
            float(np.interp(ahead, self._dist, self._lat)), float(np.interp(ahead, self._dist, self._lon)),
        )
        return RoutePosition(d, lat, lon, self.elevation_at(d), 0.0 if finished else self.slope_at(d),
                             bearing, finished)

    def section(self, start_km=None, end_km=None):
        """Abschnitt [start_m, end_m] in Metern; ohne Angabe die ganze Strecke."""
        start_m = 0.0 if start_km is None else float(start_km) * 1000.0
        end_m = self.length_m if end_km is None else float(end_km) * 1000.0
        start_m = max(0.0, min(start_m, self.length_m))
        end_m = max(0.0, min(end_m, self.length_m))
        if end_m - start_m < MIN_SECTION_M:
            raise ValueError(f"Der Abschnitt muss mindestens {MIN_SECTION_M:.0f} m lang sein "
                             f"(Start {start_m / 1000:.2f} km, Ziel {end_m / 1000:.2f} km).")
        return start_m, end_m

    def section_position(self, start_m: float, end_m: float, driven_m: float) -> RoutePosition:
        """Position nach driven_m gefahrenen Metern ab start_m; Ziel ist end_m."""
        absolute = start_m + max(0.0, driven_m)
        finished = absolute >= end_m
        pos = self.position_at(min(absolute, end_m))
        return replace(pos, finished=finished, slope_percent=0.0 if finished else pos.slope_percent)

    def to_geojson_payload(self, max_points: int = 1500) -> dict:
        """Geometrie und Höhenprofil für die Karte (ausgedünnt)."""
        step = max(1, len(self._lat) // max_points)
        coords = [[round(float(lo), 6), round(float(la), 6)] for la, lo in zip(self._lat[::step], self._lon[::step])]
        if coords[-1] != [round(float(self._lon[-1]), 6), round(float(self._lat[-1]), 6)]:
            coords.append([round(float(self._lon[-1]), 6), round(float(self._lat[-1]), 6)])
        coord_dist = [round(float(x), 1) for x in self._dist[::step]]
        if len(coord_dist) < len(coords):
            coord_dist.append(round(self.length_m, 1))

        pstep = max(1, int(round(50.0 / GRID_STEP_M)))
        return {
            "name": self.name,
            "length_m": round(self.length_m, 1),
            "elevation_gain_m": round(self.elevation_gain_m),
            "elevation_loss_m": round(self.elevation_loss_m),
            "coordinates": coords,
            "coordinate_distance_m": coord_dist,
            "profile": {
                "distance_m": [round(float(x), 1) for x in self._grid[::pstep]],
                "elevation_m": [round(float(x), 1) for x in self._ele_grid[::pstep]],
                "slope_percent": [round(float(x), 1) for x in self._slope_grid[::pstep]],
            },
            "bbox": [float(self._lon.min()), float(self._lat.min()), float(self._lon.max()), float(self._lat.max())],
        }


def list_route_files(directory: Path) -> List[str]:
    if not directory.is_dir():
        return []
    return sorted(p.name for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".gpx")


def resolve_route_file(directory: Path, name: str) -> Optional[Path]:
    """Nur Dateinamen aus dem Streckenordner zulassen (kein Pfad von aussen)."""
    if not name:
        return None
    candidate = (directory / Path(name).name).resolve()
    if candidate.parent != directory.resolve() or candidate.suffix.lower() != ".gpx" or not candidate.is_file():
        return None
    return candidate
