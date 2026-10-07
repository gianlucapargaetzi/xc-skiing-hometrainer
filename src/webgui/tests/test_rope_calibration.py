import math

import pytest

from Utils.rope_calibration import (
    BASE_MAX_PCT, SPEED_LIMIT_RPM, RopeCalibration, fit_mass_friction, release_acceleration,
)

RATED_NM, DRUM_R, DIST_PER_REV = 2.88, 0.0265, 166.0
MASS, FRICTION = 0.8, 2.5          # «wahre» Mechanik der Simulation
DT = 0.02                          # 50 Hz


def make(recovery=10.0, pull=5.0, speed=3000.0):
    return RopeCalibration(rated_torque_nm=RATED_NM, drum_radius_m=DRUM_R, dist_per_rev_mm=DIST_PER_REV,
                           current_pull_pct=pull, current_recovery_pct=recovery, current_speed_rpm=speed)


class Sim:
    """Seil + Hand: Freilauf mit Physik; bei Stössen folgt das Seil der Hand (Sinus-Hin- und Rückweg)."""

    def __init__(self, cal):
        self.cal, self.t, self.x, self.v = cal, 0.0, 0.0, 0.0

    def tick(self, x=None):
        if x is not None:
            self.v, self.x = (x - self.x) / DT, x
        self.t += DT
        self.cal.add(self.t, self.x)

    def free_run(self):
        for i in range(25):                        # herausziehen
            self.tick(0.7 * (i + 1) / 25)
        for _ in range(15):                        # still halten
            self.tick(0.7)
        self.v = 0.0
        for _ in range(200):                       # loslassen
            torque, speed = self.cal.command(False, 0.0)
            f = torque / 100 * RATED_NM / DRUM_R - FRICTION
            self.v = max(-speed * DIST_PER_REV / 1000 / 60, self.v - f / MASS * DT)
            self.x = max(0.0, self.x + self.v * DT)
            self.t += DT
            self.cal.add(self.t, self.x)
            if self.x <= 0.0:
                break
        for _ in range(10):
            self.tick(0.0)

    def stroke(self, length=0.9, pull_s=0.5, back_s=0.7):
        n1, n2 = int(pull_s / DT), int(back_s / DT)
        for i in range(n1):
            self.tick(length * (1 - math.cos(math.pi * (i + 1) / n1)) / 2)
        for i in range(n2):
            self.tick(length * (1 + math.cos(math.pi * (i + 1) / n2)) / 2)
        for _ in range(5):
            self.tick(0.0)


def run_until(cal, sim, groups, stars=4, limit=400):
    for _ in range(limit):
        if cal.state == "done" or cal.step is None or cal.step.group not in groups:
            return
        if cal.state == "rating":
            cal.rate(stars)
            continue
        sim.free_run() if cal.step.group == "free" else sim.stroke()


def test_release_acceleration_from_parabola():
    pts = [(i * DT, 0.7 - 0.5 * 6.0 * (i * DT) ** 2) for i in range(8)]
    assert release_acceleration(pts) == pytest.approx(6.0, rel=1e-6)


def test_fit_mass_friction_line():
    pts = [((f - 2.0) / 0.9, f) for f in (5.0, 7.0, 9.0) for _ in range(2)]
    m, f0 = fit_mass_friction(pts)
    assert m == pytest.approx(0.9) and f0 == pytest.approx(2.0)


def test_full_run_measures_mechanics_and_respects_limits():
    cal = make()
    sim = Sim(cal)
    run_until(cal, sim, {"free"})
    run_until(cal, sim, {"load"})
    # nach Freilauf + Belastung: Mechanik gemessen, Stufen angelegt
    assert cal.model_measured
    assert cal.mass_kg == pytest.approx(MASS, rel=0.25)
    assert cal.friction_n == pytest.approx(FRICTION, abs=1.5)
    assert any(s.group == "rec" for s in cal.steps) and any(s.group == "pull" for s in cal.steps)
    run_until(cal, sim, {"rec", "pull", "check"})
    assert cal.state == "done"
    rec = cal.result["recommended"]
    assert 5 <= rec["recovery_pct"] <= BASE_MAX_PCT and rec["pull_pct"] <= BASE_MAX_PCT
    assert 1200 <= rec["speed_rpm"] <= SPEED_LIMIT_RPM
    # Rückholgeschwindigkeit der Simulation: Sinus 0.9 m in 0.7 s -> Spitze ≈ 2.0 m/s -> × 1.3 ≈ 950 rpm -> min. 1200
    assert rec["speed_rpm"] == 1200
    summary = cal.summary()
    assert summary["state"] == "done" and summary["stages"][0]["acc_m_s2"] > 0


def test_commands_never_exceed_limits():
    cal = make(recovery=55.0, pull=50.0, speed=4000.0)   # Profilwerte über den Grenzen
    for st in cal.steps:
        st.recovery_pct, st.pull_pct, st.speed_rpm = 60.0, 60.0, 5000.0
    torque, speed = cal.command(False, 0.0)
    assert torque <= BASE_MAX_PCT and speed <= SPEED_LIMIT_RPM
    torque, speed = cal.command(True, 0.0)              # Zug ohne Stosskraft-Anteil
    assert torque <= BASE_MAX_PCT
    cal.index = len(cal.steps)                          # Ende ohne Ergebnis -> begrenzte Profilwerte
    assert cal.command(False, 0.0) == (BASE_MAX_PCT, SPEED_LIMIT_RPM)


def test_skip_and_repeat():
    cal = make()
    first = cal.step
    cal.skip()
    assert cal.step is not first
    sim = Sim(cal)
    sim.free_run()
    assert cal.step.done == 1
    cal.repeat()
    assert cal.step.done == 0 and cal.step.events == []
