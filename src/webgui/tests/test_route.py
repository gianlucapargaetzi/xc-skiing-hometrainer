import math

import pytest

from Utils.route import Route, haversine_m, list_route_files, resolve_route_file

GPX = """<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
 <trk><name>Test</name><trkseg>
{points}
 </trkseg></trk>
</gpx>"""


def _write_gpx(path, n=401, step_m=10.0, climb_from=2000.0, slope=0.05):
    """Gerade Strecke nach Norden: 2 km flach, danach 5 % Steigung."""
    lat0, lon0 = 46.70, 9.80
    dlat = step_m / 111_195.0
    pts = []
    for i in range(n):
        d = i * step_m
        ele = 1500.0 + max(0.0, d - climb_from) * slope
        pts.append(f'  <trkpt lat="{lat0 + i * dlat:.7f}" lon="{lon0:.7f}"><ele>{ele:.2f}</ele></trkpt>')
        if i == 5:  # doppelter Punkt (Stillstand) wird ignoriert
            pts.append(pts[-1])
    path.write_text(GPX.format(points="\n".join(pts)))
    return path


def test_haversine():
    assert haversine_m(46.0, 9.0, 46.001, 9.0) == pytest.approx(111.2, rel=0.01)


def test_route_length_slope_and_position(tmp_path):
    r = Route.from_gpx(_write_gpx(tmp_path / "test.gpx"))
    assert r.name == "test"
    assert r.length_m == pytest.approx(4000, rel=0.01)
    assert r.slope_at(1000) == pytest.approx(0.0, abs=0.1)
    assert r.slope_at(3000) == pytest.approx(5.0, abs=0.2)
    assert r.elevation_gain_m == pytest.approx(100, rel=0.05)

    p = r.position_at(1000)
    assert not p.finished
    assert p.bearing_deg == pytest.approx(0.0, abs=1.0)  # nach Norden
    assert haversine_m(46.70, 9.80, p.lat, p.lon) == pytest.approx(1000, rel=0.01)

    end = r.position_at(5000)
    assert end.finished and end.slope_percent == 0.0
    assert end.distance_m == pytest.approx(r.length_m)


def test_geojson_payload(tmp_path):
    r = Route.from_gpx(_write_gpx(tmp_path / "test.gpx"))
    g = r.to_geojson_payload(max_points=100)
    assert len(g["coordinates"]) <= 102
    assert len(g["coordinates"]) == len(g["coordinate_distance_m"])
    assert g["coordinate_distance_m"][-1] == pytest.approx(r.length_m, abs=1)
    assert len(g["profile"]["distance_m"]) == len(g["profile"]["elevation_m"]) == len(g["profile"]["slope_percent"])
    assert g["bbox"][1] < g["bbox"][3]


def test_resolve_route_file_rejects_paths(tmp_path):
    _write_gpx(tmp_path / "a.gpx")
    (tmp_path / "b.txt").write_text("x")
    assert list_route_files(tmp_path) == ["a.gpx"]
    assert resolve_route_file(tmp_path, "a.gpx") is not None
    assert resolve_route_file(tmp_path, "../a.gpx") is not None  # nur der Dateiname zählt
    assert resolve_route_file(tmp_path, "/etc/passwd") is None
    assert resolve_route_file(tmp_path, "b.txt") is None
    assert resolve_route_file(tmp_path, "") is None


def test_gpx_without_elevation_is_rejected(tmp_path):
    f = tmp_path / "x.gpx"
    f.write_text(GPX.format(points='  <trkpt lat="46.7" lon="9.8"></trkpt>'))
    with pytest.raises(ValueError):
        Route.from_gpx(f)


def test_route_section(tmp_path):
    r = Route.from_gpx(_write_gpx(tmp_path / "test.gpx"))
    assert r.section() == (0.0, pytest.approx(r.length_m))
    start, end = r.section(1.0, 3.0)
    assert (start, end) == (1000.0, 3000.0)
    assert r.section(None, 99) == (0.0, pytest.approx(r.length_m))  # Ziel hinter dem Ende -> Streckenende
    with pytest.raises(ValueError):
        r.section(2.0, 2.1)   # kürzer als 200 m
    with pytest.raises(ValueError):
        r.section(3.0, 1.0)

    p = r.section_position(start, end, 500.0)
    assert p.distance_m == pytest.approx(1500.0) and not p.finished
    p = r.section_position(start, end, 2500.0)
    assert p.finished and p.distance_m == pytest.approx(3000.0) and p.slope_percent == 0.0
    # Steigung im Abschnitt kommt von der richtigen Stelle (ab 2 km: 5 %)
    assert r.section_position(start, end, 1500.0).slope_percent == pytest.approx(5.0, abs=0.2)
