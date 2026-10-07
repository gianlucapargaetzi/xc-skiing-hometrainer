import pytest

fitdecode = pytest.importorskip("fitdecode")

from Utils.fit_export import FitRecorder, FitSample, fit_crc


def _decode(path):
    msgs = {}
    with fitdecode.FitReader(str(path), check_crc=fitdecode.CrcCheck.RAISE) as fit:
        for frame in fit:
            if isinstance(frame, fitdecode.FitDataMessage):
                msgs.setdefault(frame.name, []).append({f.name: f.value for f in frame.fields})
    return msgs


def _recorder(with_gps: bool, seconds=130, per_km_laps=False):
    rec = FitRecorder()
    t0 = 1_791_300_000.0
    for i in range(seconds):
        d = i * 4.0  # 4 m/s
        rec.add(FitSample(t=t0 + i, distance_m=d, speed_m_s=4.0, heart_rate=140 + i % 10, cadence=50, power=60 + i % 5,
                          lat=46.7978 + i * 1e-5 if with_gps else None, lon=9.8318 if with_gps else None,
                          altitude_m=1540 + i * 0.1 if with_gps else None, grade_percent=2.5 if with_gps else None),
                lap_key=int(d // 200) if per_km_laps else None, lap_trigger=2)
    return rec


def test_crc_known_value():
    assert fit_crc(b"") == 0
    assert fit_crc(bytes([0x0E, 0x20])) != 0


def test_indoor_file_without_gps(tmp_path):
    path = tmp_path / "indoor.fit"
    _recorder(with_gps=False).write(str(path))
    m = _decode(path)
    s = m["session"][0]
    assert s["sport"] == "cross_country_skiing" and s["sub_sport"] == "generic"   # Strava: Skilanglauf
    assert len(m["record"]) == 130
    r = m["record"][10]
    assert r["heart_rate"] == 140 and r["cadence"] == 50 and r["power"] == 60
    assert r["distance"] == pytest.approx(40.0) and r.get("position_lat") is None   # keine GPS-Daten
    assert s["total_distance"] == pytest.approx(516.0) and s["total_timer_time"] == pytest.approx(129.0)
    assert s["avg_power"] == 62 and s["max_heart_rate"] == 149
    assert len(m["lap"]) == 1 and m["activity"][0]["num_sessions"] == 1


def test_route_file_with_gps_and_laps(tmp_path):
    path = tmp_path / "route.fit"
    _recorder(with_gps=True, per_km_laps=True).write(str(path))
    m = _decode(path)
    r = m["record"][100]
    deg = 180.0 / 2 ** 31                                   # fitdecode liefert Semicircles
    assert r["position_lat"] * deg == pytest.approx(46.7978 + 100e-5, abs=1e-6)
    assert r["position_long"] * deg == pytest.approx(9.8318, abs=1e-6)
    assert r["altitude"] == pytest.approx(1550.0, abs=0.3) and r["grade"] == pytest.approx(2.5)
    laps = m["lap"]
    assert len(laps) == 3                                   # 0–200 m, 200–400 m, Rest
    assert laps[0]["total_distance"] == pytest.approx(200.0)
    assert sum(l["total_distance"] for l in laps) == pytest.approx(516.0)
    assert m["session"][0]["num_laps"] == 3


def test_empty_recorder_raises(tmp_path):
    with pytest.raises(ValueError):
        FitRecorder().write(str(tmp_path / "x.fit"))
