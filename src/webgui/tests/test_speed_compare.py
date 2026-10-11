import pytest

from Utils import speed_compare as sc


def test_pace_bounds():
    assert sc._pace_bounds(">3:09") == (189, None)
    assert sc._pace_bounds("3:03–3:08") == (183, 188)
    assert sc._pace_bounds("<2:54") == (None, 174)
    assert sc._pace_bounds("") == (None, None)


def test_zone_times_counts_below_inside_and_above():
    zones = {"z1": {"label": "Easy", "low_bpm": 100, "high_bpm": 119}, "z2": {"label": "Z2", "low_bpm": 120, "high_bpm": 139}}
    rows = sc._zone_times([(90, 10), (110, 20), (119.5, 5), (130, 30), (150, 15), (None, 99)], zones, "low_bpm", "high_bpm", "bpm")
    by = {r["zone"]: r["seconds"] for r in rows}
    assert by == {"unter Z1": 10, "Z1 Easy": 25, "Z2": 30, "über Z5": 15}
    assert sum(r["pct"] for r in rows) == pytest.approx(100, abs=0.2)


def test_value_at_interpolates_and_clamps():
    series = [(0.0, 0.0, 100.0), (100.0, 10.0, 110.0), (200.0, 30.0, 110.0)]
    assert sc.value_at(series, 50.0) == pytest.approx(5.0)
    assert sc.value_at(series, 150.0) == pytest.approx(20.0)
    assert sc.value_at(series, 999.0) == 30.0 and sc.value_at(series, -5.0) == 0.0
    assert sc.value_at(series, 50.0, 2) == pytest.approx(105.0)


def test_segments_speed_and_slope():
    real = [(float(d), d / 2.0, 1000.0 + d * 0.05) for d in range(0, 2001, 10)]     # 2 m/s, 5 % Steigung
    sim = [(float(d), d / 4.0, 40, 50) for d in range(0, 2001, 4)]                   # 4 m/s
    rows = sc.segments(sim, real, 500.0, 0.0, 2000.0)
    assert len(rows) == 4
    a, length, slope, v_real, v_sim, power, cadence = rows[1]
    assert (a, length) == (500.0, 500.0)
    assert slope == pytest.approx(5.0) and v_real == pytest.approx(7.2) and v_sim == pytest.approx(14.4)
    assert power == 40 and cadence == 50
    # ohne Zeitstempel im GPX gibt es kein Original-Tempo
    untimed = [(d, None, e) for d, _, e in real]
    assert sc.segments(sim, untimed, 500.0, 0.0, 2000.0)[0][3] is None
