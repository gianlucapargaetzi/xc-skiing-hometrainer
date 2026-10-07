import xml.etree.ElementTree as ET

import numpy as np
import pytest

from Utils.force_profile import build_force_profile_absolute, build_target_torque_curve_absolute
from Utils.settings import MAX_TRAVEL_MM, Settings
from Utils.stroke_analysis import (
    StrokeAnalyzer,
    calculate_push_phase_energy_j,
    calculate_swing_efficiency_pct,
    time_weighted_mean,
)
from Utils.tcx_export import total_time_seconds, write_tcx
from Utils.zones import get_hr_zone_key, get_reference_zone_key, get_spm_zone_key

TARGETS = {
    "hr_zones": {
        "z1": {"low_bpm": 100}, "z2": {"low_bpm": 120}, "z3": {"low_bpm": 140},
        "z4": {"low_bpm": 160}, "z5": {"low_bpm": 175},
    },
    "skierg_spm_zones": {
        "z1": {"high_spm": 30}, "z2": {"high_spm": 36}, "z3": {"high_spm": 42}, "z4": {"high_spm": 50},
    },
}


# ---------------------- Zonen ----------------------
@pytest.mark.parametrize("hr, zone", [(90, None), (100, "z1"), (139, "z2"), (160, "z4"), (190, "z5"), ("x", None)])
def test_hr_zone(hr, zone):
    assert get_hr_zone_key(hr, TARGETS) == zone


@pytest.mark.parametrize("spm, zone", [(20, "z1"), (30, "z1"), (31, "z2"), (50, "z4"), (60, "z5")])
def test_spm_zone(spm, zone):
    assert get_spm_zone_key(spm, TARGETS) == zone


def test_reference_zone_falls_back_to_spm_without_hr():
    assert get_reference_zone_key(0, 45, TARGETS) == "z4"
    assert get_reference_zone_key(150, 45, TARGETS) == "z3"


# ---------------------- Kraftprofil ----------------------
def test_force_profile_zero_outside_swing_and_peak_inside():
    f = build_force_profile_absolute(MAX_TRAVEL_MM, swing_start_mm=650, swing_end_mm=1650)
    assert len(f) == MAX_TRAVEL_MM + 1
    assert f[:650].max() == 0.0
    assert f[1651:].max() == 0.0
    assert f.max() == pytest.approx(100.0)
    peak = int(np.argmax(f))
    assert 650 < peak < 1150  # Peak früh bis mittig


def test_target_torque_curve_respects_limits():
    y = build_target_torque_curve_absolute(MAX_TRAVEL_MM, 650, 1650, min_torque_pct_value=20,
                                           current_intensity_value=200, max_torque_limit_value=150)
    assert y.min() == pytest.approx(20)
    assert y.max() == pytest.approx(150)


# ---------------------- Auswertung ----------------------
def test_time_weighted_mean_ignores_uneven_sampling():
    # 0.8 s bei 0 W (wenige Messpunkte), Rampe 0.8..1.0 s, dann 1 s bei 100 W (viele Messpunkte)
    # Integral: 0 + 0.2 * 50 + 1.0 * 100 = 110 J über 2 s -> 55 W
    t = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0] + [1.0 + i * 0.05 for i in range(1, 21)]
    p = [0.0] * 5 + [100.0] * 21
    assert time_weighted_mean(p, t) == pytest.approx(55.0)
    assert np.mean(p) > 75  # einfaches Mittel wäre stark verzerrt


def test_time_weighted_mean_fallback():
    assert time_weighted_mean([10, 20], [0.0, 5.0]) == 15.0  # Lücke > 0.25 s
    assert time_weighted_mean([], []) == 0.0


def test_swing_efficiency():
    assert calculate_swing_efficiency_pct(2.0, 0.5) == pytest.approx(75.0)
    assert calculate_swing_efficiency_pct(0, 0.5) == 0.0
    assert calculate_swing_efficiency_pct(1.0, 5.0) == 0.0


def test_push_phase_energy_only_inside_swing():
    pos = [500, 700, 900, 1700, 1800]
    power = [-100, -100, -100, -100, -100]
    t = [0.0, 0.1, 0.2, 0.3, 0.4]
    # Intervall-Mittelpunkte: 600 (aus), 800 (ein), 1300 (ein), 1750 (aus) -> 2 x 0.1 s x 100 W
    assert calculate_push_phase_energy_j(pos, power, t, 650, 1650) == pytest.approx(20.0)


def _simulate_strokes(analyzer, n_strokes, cycle_s=1.2, dt=0.02, push_fraction=0.4, power_w=300.0, t0=1000.0):
    """Zug: speed < 0 und Leistung (negativ gemeldet), Rückholung: speed > 0, Leistung 0."""
    results = []
    t = t0
    distance = 0.0
    steps = int(round(cycle_s / dt))
    for _ in range(n_strokes):
        for i in range(steps):
            in_push = i < steps * push_fraction
            speed = -50.0 if in_push else 50.0
            raw_power = -power_w if in_push else 0.0
            pos = 700 + 900 * (i / steps) if in_push else 1600 - 900 * (i / steps)
            if analyzer.add_sample(t, pos, speed, raw_power, 60, 80):
                results.append(analyzer.close_cycle(t, 150, TARGETS, distance))
            t += dt
            distance += 5.0 * dt  # konstant 5 m/s
    return results


def test_stroke_analyzer_cadence_power_and_efficiency():
    analyzer = StrokeAnalyzer(swing_start_mm=650, swing_end_mm=1650)
    results = _simulate_strokes(analyzer, n_strokes=5)

    # Richtungswechsel zu Beginn von Zug 2..5; der erste startet nur die Zeitmessung
    assert len(results) == 4
    assert results[0] is None
    strokes = [r for r in results if r is not None]
    assert len(strokes) == 3
    for s in strokes:
        assert s.cadence_spm == 50  # 60 / 1.2 s
        assert s.duration_s == pytest.approx(1.2)
        assert s.mean_power_w == pytest.approx(120.0, rel=0.1)  # 300 W * 40 %
        assert s.swing_efficiency_pct == pytest.approx(40.0, abs=5.0)

    assert analyzer.stroke_count == 3
    for s in strokes:
        assert s.distance_m == pytest.approx(6.0, abs=0.15)  # 5 m/s * 1.2 s
        assert s.pace_s500 == 100
    assert analyzer.total_distance_m == pytest.approx(strokes[-1].total_distance_m)
    assert strokes[-1].timestamp.tzinfo is not None


def test_stroke_record_timestamp_is_utc_iso():
    analyzer = StrokeAnalyzer(650, 1650)
    stroke = [r for r in _simulate_strokes(analyzer, 3, t0=0.0) if r][0]
    rec = stroke.to_record()
    # t0 = 0 -> Epoch, der Zeitstempel muss also 1970-01-01T00:00:0x UTC sein
    assert rec["timestamp"].startswith("1970-01-01T00:00:0")
    assert rec["timestamp"].endswith("Z")


# ---------------------- TCX ----------------------
def test_tcx_total_time_is_duration(tmp_path):
    records = [
        {"timestamp": "2026-10-06T10:00:00.000Z", "distance": 0.0, "power": 100, "heart_rate": 120, "cadence_spm": 40},
        {"timestamp": "2026-10-06T10:00:30.500Z", "distance": 50.0, "power": 110, "heart_rate": 125, "cadence_spm": 42},
    ]
    assert total_time_seconds(records) == pytest.approx(30.5)

    out = tmp_path / "t.tcx"
    write_tcx(records, filename=str(out))
    ns = {"t": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}
    root = ET.parse(out).getroot()
    assert root.find(".//t:Lap/t:TotalTimeSeconds", ns).text == "30.5"
    assert len(root.findall(".//t:Trackpoint", ns)) == 2


# ---------------------- Settings ----------------------
def _config(top=2100, pole=1450, swing=1000):
    return {
        "hardware": {"pulli_diameter": 60, "rope_diameter": 4, "top_position": top,
                     "pole_length": pole, "swing_length": swing},
        "swing_torque": {"swing_start_max_torque_pml": 100, "swing_end_max_torque_pml": 400},
        "control": {"min_torque_calib_pct": 5, "min_speed_calib": 100, "min_torque_pct": 20,
                    "CurrentLimit": 10, "pull_speed": 300},
        "user": {"weight_kg": 78, "mu": 0.02, "s_s": 1.1, "slope_percent": 0},
        "drive": {"host": "1.2.3.4", "port": 502, "unit_id": 1},
    }


def test_settings_geometry():
    s = Settings.from_config(_config(), TARGETS)
    assert s.swing_start_mm == 650
    assert s.swing_end_mm == 1650
    assert s.dist_per_rev == round(64 * 3.14159)
    s.validate_geometry()


def test_settings_invalid_geometry():
    s = Settings.from_config(_config(top=2400, pole=1000, swing=1500), TARGETS)
    with pytest.raises(ValueError):
        s.validate_geometry()


def test_settings_tuning_defaults_and_mass():
    cfg = _config()
    s = Settings.from_config(cfg, TARGETS)
    assert s.power_scale == 1.0 and s.equipment_kg == 0.0
    assert s.feel_mu == cfg["user"]["mu"]  # ohne Angabe: gleiches Gefühl wie Tempo
    cfg["simulation"] = {"power_scale": 2.1, "equipment_kg": 3, "feel_mu": 0.02}
    cfg["user"]["mu"] = 0.037
    s = Settings.from_config(cfg, TARGETS)
    assert s.system_mass_kg == 81 and s.feel_mu == 0.02 and s.mu == 0.037
    s.validate_geometry()


# ---------------------- Technik (Double Poling / Diagonal / Auto) ----------------------
import importlib.util as _ilu
import sys as _sys


def _technique_funcs():
    """diagonal_target_weight/technique_factors aus x-ski.py lesen, ohne das Programm zu starten."""
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "x-ski.py").read_text()
    tree = ast.parse(src)
    keep = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ("diagonal_target_weight", "technique_factors")]
    ns = {"Settings": Settings}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "x-ski-technique", "exec"), ns)
    return ns["diagonal_target_weight"], ns["technique_factors"]


def test_auto_technique_blends_over_slope_band():
    w, _ = _technique_funcs()
    # Profil des Athleten: Schwelle 3.5 %, Hysterese 1 % -> Übergang von 2.0 % bis 4.0 %
    assert w("auto", 1.9, 3.5, 1.0) == 0.0
    assert w("auto", 3.0, 3.5, 1.0) == pytest.approx(0.5)
    assert w("auto", 4.0, 3.5, 1.0) == 1.0 and w("auto", 9.0, 3.5, 1.0) == 1.0
    assert w("dp", 12, 3.5, 1.0) == 0.0
    assert w("diagonal", -3, 3.5, 1.0) == 1.0


def test_technique_threshold_from_user_profile():
    cfg = _config()
    assert Settings.from_config(cfg, TARGETS).diagonal_from_slope_percent == 5.0
    cfg["simulation"] = {"diagonal_from_slope_percent": 4.0}          # ältere Konfiguration
    assert Settings.from_config(cfg, TARGETS).diagonal_from_slope_percent == 4.0
    cfg["user"].update(diagonal_from_slope_percent=3.5, diagonal_hysteresis_percent=1.0)  # Userprofil gewinnt
    s = Settings.from_config(cfg, TARGETS)
    assert (s.diagonal_from_slope_percent, s.diagonal_hysteresis_percent) == (3.5, 1.0)
    s.validate_geometry()
    cfg["user"]["diagonal_hysteresis_percent"] = 4.0                  # Hysterese grösser als Schwelle
    with pytest.raises(ValueError):
        Settings.from_config(cfg, TARGETS).validate_geometry()


def test_technique_factors_blend_arm_relief_and_power():
    _, fac = _technique_funcs()
    s = Settings.from_config(_config(), TARGETS)
    assert fac(s, 0.0) == (1.0, 1.0)
    arm, boost = fac(s, 1.0)
    assert arm == pytest.approx(0.4) and boost == pytest.approx(s.diagonal_power_factor)
    arm, _ = fac(s, 0.5)
    assert arm == pytest.approx(0.7)                     # halber Übergang: Armkraft zwischen DP und Diagonal

