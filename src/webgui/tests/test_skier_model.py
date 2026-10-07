import math
import textwrap

import pytest

from IntensityController.IntervallIntensityController import IntervallParser
from Utils.skier_model import (
    StrokeForcePlanner,
    stroke_peak_force_n,
    RopeSpeedEstimator,
    Terrain,
    VirtualSkier,
    estimate_rated_torque_nm,
    force_to_torque_pct,
    intensity_to_slope_percent,
)

FLAT = Terrain(slope_percent=0.0, mu=0.03)


def _run(skier, seconds, terrain, dt=0.02, **kw):
    for _ in range(int(seconds / dt)):
        skier.step(dt, terrain, **kw)
    return skier.speed_m_s


# ---------------------- virtueller Skifahrer ----------------------
def test_constant_power_reaches_power_balance_speed():
    skier = VirtualSkier(mass_kg=78, cda_m2=0.45)
    v = _run(skier, 120, FLAT, propulsive_power_w=200)
    assert v == pytest.approx(skier.steady_state_speed(200, FLAT), rel=0.02)
    assert 5.5 < v < 6.5  # realistisch für 200 W im Flachen
    assert v * skier.resistance_force_n(v, FLAT) == pytest.approx(200, rel=0.05)


def test_uphill_is_slower():
    skier = VirtualSkier(mass_kg=78)
    assert skier.steady_state_speed(200, Terrain(3.0, 0.03)) < skier.steady_state_speed(200, FLAT) - 1.5


def test_start_from_rest_with_force_and_power():
    assert _run(VirtualSkier(78), 1, FLAT, propulsive_force_n=200) > 1.0
    assert _run(VirtualSkier(78), 1, FLAT, propulsive_power_w=200) > 1.0


def test_no_push_flat_and_uphill_stays_at_rest():
    assert _run(VirtualSkier(78), 5, FLAT) == 0.0
    assert _run(VirtualSkier(78), 5, Terrain(5.0, 0.03)) == 0.0  # kein Rückwärtsrollen


def test_downhill_glides_to_terminal_speed():
    skier = VirtualSkier(mass_kg=78, cda_m2=0.45)
    terrain = Terrain(-5.0, 0.03)
    v = _run(skier, 120, terrain)
    theta = math.atan(-0.05)
    expected = math.sqrt(78 * 9.81 * (-math.sin(theta) - 0.03 * math.cos(theta)) / (0.5 * 1.2 * 0.45))
    assert v == pytest.approx(expected, rel=0.02)


def test_large_dt_is_limited_and_distance_integrates():
    skier = VirtualSkier(78)
    skier.speed_m_s = 5.0
    skier.step(10.0, FLAT)  # Aussetzer: nur MAX_DT_S wird integriert
    assert skier.distance_m == pytest.approx(0.5, abs=0.05)


# ---------------------- Stosskraft (Skifahrer-Modus) ----------------------
def test_stroke_peak_force_balances_resistance():
    # Flach, 4 m/s: Widerstand ~19 N; Stoss 0.45 s von 1.25 s; Profilmittel 0.5
    f = stroke_peak_force_n(19.0, cycle_s=1.25, push_s=0.45, profile_mean=0.5, max_force_n=500)
    assert f == pytest.approx(19.0 * (1.25 / 0.45) / 0.5)
    # Kraftstoss im Stoss (Mittel × Dauer) gleicht Widerstand × Zykluszeit aus
    assert f * 0.5 * 0.45 == pytest.approx(19.0 * 1.25)


def test_stroke_peak_force_limits():
    assert stroke_peak_force_n(-5.0, 1.2, 0.45, 0.5) == 0.0                   # bergab: kein Stosswiderstand
    assert stroke_peak_force_n(80.0, 1.2, 0.45, 0.5, max_force_n=150) == 150  # Begrenzung
    # extremes Verhältnis Zyklus/Stoss wird begrenzt
    assert stroke_peak_force_n(10.0, 10.0, 0.1, 1.0, max_force_n=999) == pytest.approx(40.0)


def test_planner_ramps_up_gently_and_is_step_limited():
    planner = StrokeForcePlanner(profile_mean=0.5, max_force_n=150, max_step_n=20)
    assert planner.peak_force_n == 0.0
    peaks = [planner.update(40.0, cycle_s=1.2, push_s=0.45) for _ in range(10)]
    assert peaks[:3] == [20.0, 40.0, 60.0]
    assert all(b - a <= 20.0 + 1e-9 for a, b in zip(peaks, peaks[1:]))
    assert peaks[-1] == 150.0  # Ziel wäre 213 N -> begrenzt


def test_planner_follows_terrain_change_stepwise():
    planner = StrokeForcePlanner(profile_mean=0.5, max_force_n=150, max_step_n=20)
    for _ in range(20):
        planner.update(20.0, 1.2, 0.45)
    flat = planner.peak_force_n
    planner.update(-10.0, 1.2, 0.45)           # plötzlich bergab
    assert planner.peak_force_n == pytest.approx(flat - 20.0)
    for _ in range(20):
        planner.update(-10.0, 1.2, 0.45)
    assert planner.peak_force_n == 0.0


def test_planner_ignores_implausible_rhythm():
    planner = StrokeForcePlanner(profile_mean=0.5)
    planner.update(20.0, cycle_s=50.0, push_s=0.0)  # Pause / Fehlmessung
    assert planner.cycle_s == 1.2 and planner.push_s == 0.45


def test_closed_loop_with_simulated_athlete_is_stable():
    """Athlet bringt pro Stoss die geplante Kraft bei konstanter Handgeschwindigkeit auf.
    Tempo und Stosskraft müssen sich auf einen Gleichgewichtswert einpendeln (kein Aufschaukeln)."""
    skier = VirtualSkier(78, cda_m2=0.45)
    planner = StrokeForcePlanner(profile_mean=0.55, max_force_n=150, max_step_n=20)
    terrain = FLAT
    dt, cycle, push, hand = 0.02, 1.2, 0.45, 2.5
    peaks = []
    for _ in range(120):
        for i in range(int(cycle / dt)):
            power = planner.peak_force_n * 0.55 * hand if i * dt < push else 0.0
            skier.step(dt, terrain, propulsive_power_w=power)
        peaks.append(planner.update(skier.resistance_force_n(skier.speed_m_s, terrain), cycle, push))
    tail = peaks[-20:]
    assert max(tail) - min(tail) < 2.0           # eingeschwungen
    assert 2.0 < skier.speed_m_s < 6.0           # plausibles Tempo


def test_force_to_torque_pct():
    assert force_to_torque_pct(100, drum_radius_m=0.0265, rated_torque_nm=5.3) == pytest.approx(50.0)
    assert force_to_torque_pct(100, 0.0265, 0) == 0.0


def test_estimate_rated_torque_roundtrip():
    # 50 % von 5 Nm bei 3 m/s an 26.5 mm Radius
    omega = 3.0 / 0.0265
    power = 2.5 * omega
    assert estimate_rated_torque_nm(power, 50, 3.0, 0.0265) == pytest.approx(5.0)
    assert estimate_rated_torque_nm(0, 50, 3.0, 0.0265) is None


def test_intensity_to_slope():
    assert intensity_to_slope_percent(100, 0.0, 0.1) == 0.0
    assert intensity_to_slope_percent(160, 0.0, 0.1) == pytest.approx(6.0)
    assert intensity_to_slope_percent(70, 1.0, 0.1) == pytest.approx(-2.0)
    assert intensity_to_slope_percent(0, 1.0, 0.1) == 1.0  # Controller inaktiv


def test_rope_speed_estimator():
    est = RopeSpeedEstimator(dist_per_rev_mm=167, alpha=1.0)
    counts_per_m = 65536 / 0.167
    est.update(0.00, 1_000_000)
    v = est.update(0.02, 1_000_000 - int(0.06 * counts_per_m))  # 6 cm Zug in 20 ms
    assert v == pytest.approx(3.0, rel=0.01)
    assert est.update(0.04, None) == pytest.approx(3.0, rel=0.01)   # Lesefehler: Wert halten
    assert est.update(0.06, 0) == RopeSpeedEstimator.MAX_PLAUSIBLE_M_S  # Ausreisser begrenzt


# ---------------------- Intervalldatei mit Steigung ----------------------
def test_interval_file_slopes(tmp_path):
    f = tmp_path / "t.xciv"
    f.write_text(textwrap.dedent("""
        warmup:
          type: duration_block
          duration: 10
          intensity_start: 70
          intensity_end: 70
        flat_no_slope:
          type: duration_block
          duration: 5
          intensity_start: 80
          intensity_end: 80
        hill:
          type: interval_block
          on_duration: 4
          off_duration: 3
          block_amount: 2
          on_intensity: 160
          off_intensity: 70
          on_slope: 6
          off_slope: 0
        climb:
          type: duration_block
          duration: 11
          intensity_start: 100
          intensity_end: 100
          slope_start: 0
          slope_end: 10
    """))
    p = IntervallParser(str(f))
    assert p.length() == 10 + 5 + 14 + 11
    assert p.getSlope(0) is None and p.getSlope(14) is None   # ohne Angabe
    assert p.getSlope(15) == 6.0 and p.getSlope(19) == 0.0    # on / off
    assert p.getSlope(29) == 0.0 and p.getSlope(39) == 10.0   # Rampe
    assert p.getSlope(34) == pytest.approx(5.0)
    assert len(p.slopeList) == p.length()
