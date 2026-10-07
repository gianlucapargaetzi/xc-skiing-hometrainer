# Utils/rope_calibration.py – Seilzug-Kalibrierung: geführter Testablauf und Auswertung
#
# Ziel: Grundzug, Rückzugskraft und Rückzugs-Drehzahlgrenze aus Messwerten bestimmen.
# Gemessen wird nur die Seilposition (Encoder, ~50 Hz). Daraus:
#   1) Freilauf: Seil läuft ohne Hand zurück -> Beschleunigung bei 3 Drehmomenten
#      -> Gerade «Motorkraft = bewegte Masse × Beschleunigung + Reibung»
#   2) Stösse bei verschiedener Belastung -> wie schnell/ruckartig die Hände zurückkommen
#   3) Rückzugsstufen -> Seilspannung beim Zurückholen = Motorkraft − Reibung − Masse × Beschleunigung;
#      wird sie ~0, hängt das Seil durch (die Hand ist schneller als das Seil)
#   4) Grundzugstufen -> Gefühl (Bewertung 1–5)
#   5) Prüfung mit den vorgeschlagenen Werten
# Diese Klasse berührt die Hardware nicht: die Regelschleife fragt command() ab und meldet Messwerte mit add().

import math
import statistics
import threading
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

# Freilauf
FREE_LEVELS_PCT = (5.0, 7.0, 9.0)
FREE_REPS = 3
FREE_SPEED_RPM = 900          # Drehzahlgrenze im Freilauf (≈ 2.5 m/s): Griff fliegt nicht zu schnell hoch
FREE_MIN_OUT_M = 0.35         # so weit muss das Seil vor dem Loslassen draussen sein
# Stösse
LOAD_LEVELS_PCT = (40.0, 70.0, 100.0)
LOAD_STROKES = 10
STAGE_STROKES = 8
SPRINT_LOAD_PCT = 30.0
SPRINT_STROKES = 12
STAGE_LOAD_PCT = 70.0
PULL_LEVELS_PCT = (3.0, 5.0, 8.0)
CHECK_STROKES = 8
MIN_STROKE_M = 0.30           # kürzere Bewegungen zählen nicht als Stoss
MOVE_M_S = 0.05               # Schwelle Zug / Rückzug
# Auswertung
TENSION_MARGIN_N = 3.0        # so viel Spannung soll beim Zurückholen mindestens bleiben
SLACK_N = 1.0                 # darunter gilt das Seil als durchhängend
SPEED_MARGIN = 1.3            # Drehzahlgrenze = schnellste Rückholgeschwindigkeit × Reserve
# Harte Grenzen (Vorgabe Nutzer 2026-10-07, Rückzug-Grenze auf 40 % angehoben): Grundzug und Rückzug nie über
# 40 %, Drehzahl nie über 3000 rpm.
# Gilt für jeden Testschritt und jede Empfehlung; die Stosskraft (Belastung) kommt wie im Training dazu.
BASE_MAX_PCT = 40.0
SPEED_LIMIT_RPM = 3000.0
SPEED_MIN_RPM, SPEED_MAX_RPM = 1200, SPEED_LIMIT_RPM
RECOVERY_MIN_PCT, RECOVERY_MAX_PCT = 5, BASE_MAX_PCT
FALLBACK_MASS_KG, FALLBACK_FRICTION_N = 1.0, 2.0


@dataclass
class Step:
    group: str                # free | load | rec | pull | check
    title: str
    instruction: str
    pull_pct: float           # Grundzug beim Ziehen
    recovery_pct: float       # Rückzugskraft
    speed_rpm: float          # Drehzahlgrenze
    load_pct: float           # Stossintensität wie im Belastungsprofil (0 = keine Stosskraft)
    count: int                # Anzahl Freiläufe bzw. Stösse
    rate: bool = False        # danach Gefühl bewerten
    level: float = 0.0        # der in dieser Stufe veränderte Wert
    done: int = 0
    rating: Optional[int] = None
    events: list = field(default_factory=list)   # Freiläufe bzw. Stösse dieser Stufe


@dataclass
class StrokeStats:
    length_m: float
    pull_peak_m_s: float
    return_peak_m_s: float    # schnellste Rückholgeschwindigkeit (Hände nach oben)
    return_acc_m_s2: float    # grösste Beschleunigung der Hände nach oben (95 %-Wert im Stoss)
    min_tension_n: float      # kleinste geschätzte Seilspannung beim Zurückholen
    slack: bool
    limit_hit: bool           # Rückholgeschwindigkeit an der Drehzahlgrenze


def torque_pct_to_force_n(pct: float, drum_radius_m: float, rated_torque_nm: float) -> float:
    return pct / 100.0 * rated_torque_nm / drum_radius_m


def force_n_to_torque_pct(force_n: float, drum_radius_m: float, rated_torque_nm: float) -> float:
    return 100.0 * force_n * drum_radius_m / rated_torque_nm if rated_torque_nm > 0 else 0.0


MAX_PLAUSIBLE_MASS_KG = 4.0     # Seil, Griff, Trommel und Motor; mehr deutet auf eine bremsende Hand hin


def fit_mass_friction(points):
    """points: [(Beschleunigung m/s², Motorkraft N)] -> (Masse kg, Reibung N) oder None.
    Gerade F = m·a + F_reib; braucht mindestens zwei verschiedene Kräfte. Unplausibel (None):
    zu grosse Masse, oder Reibung grösser als die kleinste Kraft, bei der das Seil trotzdem hochlief."""
    if len(points) < 3 or len({round(f, 3) for _, f in points}) < 2:
        return None
    a = np.array([p[0] for p in points]); f = np.array([p[1] for p in points])
    m, f0 = np.polyfit(a, f, 1)
    if not (0.05 <= m <= MAX_PLAUSIBLE_MASS_KG) or f0 >= f.min():
        return None
    return float(m), float(max(0.0, f0))


def release_acceleration(samples) -> Optional[float]:
    """Beschleunigung nach oben [m/s²] aus einem Freilauf: Parabel x(t) durch die Positionen
    (x = Seil draussen [m]) von «läuft los» bis kurz vor der Drehzahlgrenze."""
    if len(samples) < 4:
        return None
    t = np.array([s[0] for s in samples]); x = np.array([s[1] for s in samples])
    if t[-1] - t[0] < 0.06:
        return None
    c2, _, _ = np.polyfit(t - t[0], x, 2)
    acc = -2.0 * c2
    return float(acc) if acc > 0 else None


class RopeCalibration:
    def __init__(self, *, rated_torque_nm: float, drum_radius_m: float, dist_per_rev_mm: float,
                 current_pull_pct: float, current_recovery_pct: float, current_speed_rpm: float):
        self.rated_torque_nm = rated_torque_nm
        self.drum_radius_m = drum_radius_m
        self.rpm_to_m_s = dist_per_rev_mm / 1000.0 / 60.0
        self.current = {"pull_pct": float(current_pull_pct), "recovery_pct": float(current_recovery_pct),
                        "speed_rpm": float(current_speed_rpm)}
        # Testwerte, die von den aktuellen Werten abgeleitet sind, ebenfalls innerhalb der Grenzen halten
        self._base = {"pull_pct": min(BASE_MAX_PCT, float(current_pull_pct)),
                      "recovery_pct": min(BASE_MAX_PCT, float(current_recovery_pct)),
                      "speed_rpm": min(SPEED_LIMIT_RPM, float(current_speed_rpm))}
        self.lock = threading.RLock()
        self.steps: List[Step] = []
        self.index = 0
        self.state = "run"          # run | rating | done
        self.message = ""
        self.mass_kg: Optional[float] = None
        self.friction_n: Optional[float] = None
        self.model_measured = False
        self.required_recovery_pct: Optional[float] = None
        self.result: Optional[dict] = None
        self.applied = False
        self.stop_requested = False
        self.live = {"x_m": 0.0, "v_m_s": 0.0, "tension_n": None}
        # Messwert-Puffer
        self._hist = []            # (t, x) der letzten Zyklen für Geschwindigkeit/Beschleunigung
        self._v_hist = []          # (t, v)
        self._phase = "idle"       # idle | pull | recovery
        self._cur = None           # Daten des laufenden Stosses
        self._release = None       # laufender Freilauf
        self._was_out = 0.0
        self._build_initial_plan()

    # ---------------------------------------------------------------- Ablauf
    def _force(self, pct):
        return torque_pct_to_force_n(pct, self.drum_radius_m, self.rated_torque_nm)

    def _pct(self, force_n):
        return force_n_to_torque_pct(force_n, self.drum_radius_m, self.rated_torque_nm)

    def _build_initial_plan(self):
        c = self._base
        for i, lvl in enumerate(FREE_LEVELS_PCT):
            self.steps.append(Step(
                "free", f"Freilauf {i + 1}/{len(FREE_LEVELS_PCT)} – Zug {lvl:.0f} % (≈ {self._force(lvl):.0f} N)",
                "Griff ruhig ca. 60–80 cm herausziehen, kurz still halten, dann GANZ LOSLASSEN. "
                "Das Seil läuft allein hoch – Griff nicht berühren, erst oben auffangen.",
                lvl, lvl, FREE_SPEED_RPM, 0.0, FREE_REPS, level=lvl))
        for lvl in LOAD_LEVELS_PCT:
            name = {40.0: "leicht", 70.0: "mittel", 100.0: "hart"}.get(lvl, f"{lvl:.0f} %")
            self.steps.append(Step(
                "load", f"Stösse {name} (Belastung {lvl:.0f} %)",
                f"{LOAD_STROKES} normale Double-Poling-Stösse in deinem Rhythmus. "
                "Bei «hart» bitte auch kräftig und zügig zurückholen.",
                c["pull_pct"], c["recovery_pct"], c["speed_rpm"], lvl, LOAD_STROKES, level=lvl))
        # Sprint im Flachen: wenig Kraft, aber höchste Frequenz -> schnellste Rückholbewegungen.
        # Bestimmt meist die nötige Rückzugskraft und die Drehzahlgrenze.
        self.steps.append(Step(
            "load", f"Sprint flach (Belastung {SPRINT_LOAD_PCT:.0f} %)",
            f"{SPRINT_STROKES} Stösse wie im Zielsprint auf der Ebene: so hohe Frequenz wie möglich, "
            "Hände blitzschnell wieder nach oben.",
            c["pull_pct"], c["recovery_pct"], c["speed_rpm"], SPRINT_LOAD_PCT, SPRINT_STROKES, level=SPRINT_LOAD_PCT))

    def _add_stage_steps(self):
        """Nach Freilauf und Belastungsstössen: Rückzugsstufen um den berechneten Mindestwert, dann Grundzug."""
        c = self._base
        req = min(RECOVERY_MAX_PCT, self.required_recovery_pct or c["recovery_pct"])
        base = int(math.ceil(req))
        levels = {base - 2, base, base + 2, base + 4, int(round(c["recovery_pct"]))}
        levels = sorted(min(RECOVERY_MAX_PCT, max(RECOVERY_MIN_PCT, v)) for v in levels)
        levels = sorted(set(levels))[:5]
        for i, lvl in enumerate(levels):
            self.steps.append(Step(
                "rec", f"Rückzug {i + 1}/{len(levels)}: {lvl:.0f} % (≈ {self._force(lvl):.0f} N)",
                f"{STAGE_STROKES} Stösse mittel. Achte beim Zurückholen: folgt das Seil sauber? Zieht es zu stark?",
                c["pull_pct"], float(lvl), c["speed_rpm"], STAGE_LOAD_PCT, STAGE_STROKES, rate=True, level=float(lvl)))
        rec = float(self._best_recovery_guess())
        for i, lvl in enumerate(PULL_LEVELS_PCT):
            self.steps.append(Step(
                "pull", f"Grundzug {i + 1}/{len(PULL_LEVELS_PCT)}: {lvl:.0f} % (≈ {self._force(lvl):.0f} N)",
                f"{STAGE_STROKES} Stösse mittel. Achte auf den Zugbeginn oben und das Ende unten.",
                lvl, rec, c["speed_rpm"], STAGE_LOAD_PCT, STAGE_STROKES, rate=True, level=lvl))

    def _add_check_step(self):
        r = self._recommend()
        self.steps.append(Step(
            "check", "Prüfung mit den vorgeschlagenen Werten",
            f"{CHECK_STROKES} kräftige Stösse (Belastung 100 %), dann ein paar Sprint-Stösse – immer schnell zurückholen.",
            r["pull_pct"], r["recovery_pct"], r["speed_rpm"], 100.0, CHECK_STROKES, rate=True))

    @property
    def step(self) -> Optional[Step]:
        return self.steps[self.index] if self.index < len(self.steps) else None

    def command(self, pulling: bool, stroke_share: float):
        """(Drehmoment %, Drehzahlgrenze rpm) für die Regelschleife. Grundzug/Rückzug höchstens BASE_MAX_PCT,
        Drehzahl höchstens SPEED_LIMIT_RPM – unabhängig davon, was der Ablauf vorgibt."""
        with self.lock:
            st = self.step
            if st is None:   # fertig: vorgeschlagene (bzw. aktuelle) Werte wirken lassen
                r = self.result["recommended"] if self.result else self._base
                base, load, speed = (r["pull_pct"] if pulling else r["recovery_pct"]), 0.0, r["speed_rpm"]
            else:
                base = st.pull_pct if pulling else st.recovery_pct
                load, speed = st.load_pct, st.speed_rpm
            share = stroke_share if pulling else 0.0
            return min(base, BASE_MAX_PCT) + load * share, min(speed, SPEED_LIMIT_RPM)

    def _advance(self):
        st = self.step
        if st is not None and st.rate and st.rating is None and self.state != "rating":
            self.state = "rating"
            return
        self.state = "run"
        self.index += 1
        self._reset_motion()
        nxt = self.step
        if nxt is not None and nxt.group == "pull" and self.steps[self.index - 1].group == "rec":
            # Grundzugstufen mit dem besten Rückzug aus den Rückzugsstufen fahren
            rec = float(self._best_recovery_guess())
            for s in self.steps:
                if s.group == "pull":
                    s.recovery_pct = rec
        groups_done = {s.group for s in self.steps[:self.index]}
        if self.index == len(self.steps):
            if "rec" not in groups_done:
                self._evaluate_model()
                self._add_stage_steps()
            elif "check" not in groups_done:
                self._add_check_step()
            else:
                self._finish()

    def _reset_motion(self):
        self._phase, self._cur, self._release = "idle", None, None

    # ---------------------------------------------------------------- Bedienung (Webseite)
    def rate(self, stars: Optional[int]):
        with self.lock:
            if self.state != "rating":
                return
            st = self.step
            st.rating = int(stars) if stars else 0   # 0 = übersprungen
            self._advance()

    def repeat(self):
        with self.lock:
            st = self.step
            if st is not None:
                st.done, st.events, st.rating = 0, [], None
                self.state = "run"
                self._reset_motion()

    def skip(self):
        with self.lock:
            st = self.step
            if st is None:
                return
            if st.rate and st.rating is None:
                st.rating = 0
            self.state = "run"
            self._advance()

    # ---------------------------------------------------------------- Messwerte
    def add(self, t: float, x_out_m: float):
        """Ein Regelzyklus: Zeit [s] und Seil draussen [m] (0 = oben)."""
        with self.lock:
            self._hist.append((t, x_out_m))
            self._hist = self._hist[-6:]
            if len(self._hist) < 3:
                return
            v = _slope(self._hist[-4:])                 # m/s, positiv = Seil wird herausgezogen
            self._v_hist.append((t, v))
            self._v_hist = self._v_hist[-6:]
            acc_up = -_slope(self._v_hist[-4:]) if len(self._v_hist) >= 3 else 0.0
            self.live["x_m"], self.live["v_m_s"] = x_out_m, v
            st = self.step
            if st is None or self.state != "run":
                return
            if st.group == "free":
                self._track_release(st, t, x_out_m, v)
            else:
                self._track_stroke(st, t, x_out_m, v, acc_up)

    def _track_release(self, st: Step, t, x, v):
        if self._release is None:
            # warten, bis das Seil draussen und (fast) still ist, dann auf das Hochlaufen warten
            if x >= FREE_MIN_OUT_M and abs(v) < 0.15:
                self._was_out = x
            if self._was_out and v < -MOVE_M_S and x >= FREE_MIN_OUT_M * 0.7:
                self._release = {"samples": [(t, x)], "peak": -v}
            elif x < 0.1:
                self._was_out = 0.0
            return
        r = self._release
        limit = FREE_SPEED_RPM * self.rpm_to_m_s
        r["peak"] = max(r["peak"], -v)
        ending = (-v >= 0.85 * limit) or x < 0.08 or (-v < r["peak"] - 0.25) or v > 0
        if not ending:
            r["samples"].append((t, x))
            return
        acc = release_acceleration(r["samples"])
        self._release, self._was_out = None, 0.0
        if acc is None:
            self.message = "Freilauf zu kurz gemessen – bitte nochmals weiter herausziehen und loslassen."
            return
        # Hat die Hand gebremst? Dann ist die Beschleunigung viel kleiner – wird über die Streuung sichtbar
        st.events.append({"acc_m_s2": round(acc, 2), "force_n": round(self._force(st.level), 2)})
        st.done += 1
        self.message = f"Freilauf gemessen: {acc:.1f} m/s²"
        if st.done >= st.count:
            self._advance()

    def _tension(self, st: Step, acc_up):
        m = self.mass_kg if self.mass_kg is not None else FALLBACK_MASS_KG
        f0 = self.friction_n if self.friction_n is not None else FALLBACK_FRICTION_N
        return self._force(st.recovery_pct) - f0 - m * acc_up

    def _track_stroke(self, st: Step, t, x, v, acc_up):
        if v > MOVE_M_S:
            if self._phase == "recovery":
                self._close_stroke(st)
            if self._phase != "pull":
                self._cur = {"x0": x, "x_max": x, "pull_peak": 0.0, "ret_peak": 0.0, "acc": [], "tension": [],
                             "limit": False}
                self._phase = "pull"
            c = self._cur
            c["x_max"] = max(c["x_max"], x)
            c["pull_peak"] = max(c["pull_peak"], v)
        elif v < -MOVE_M_S and self._phase in ("pull", "recovery"):
            self._phase = "recovery"
            c = self._cur
            c["ret_peak"] = max(c["ret_peak"], -v)
            c["acc"].append(acc_up)
            tension = self._tension(st, acc_up)
            c["tension"].append(tension)
            self.live["tension_n"] = round(tension, 1)
            if -v >= 0.92 * st.speed_rpm * self.rpm_to_m_s:
                c["limit"] = True
        elif self._phase == "recovery" and x < 0.05:
            self._close_stroke(st)   # oben angekommen und stehen geblieben

    def _close_stroke(self, st: Step):
        c, self._cur, self._phase = self._cur, None, "idle"
        if c is None or c["x_max"] - min(c["x0"], c["x_max"]) < MIN_STROKE_M or not c["acc"]:
            return
        acc95 = float(np.percentile(c["acc"], 95))
        tmin = float(np.percentile(c["tension"], 5)) if c["tension"] else 0.0
        st.events.append(StrokeStats(
            length_m=round(c["x_max"] - c["x0"], 2), pull_peak_m_s=round(c["pull_peak"], 2),
            return_peak_m_s=round(c["ret_peak"], 2), return_acc_m_s2=round(acc95, 1),
            min_tension_n=round(tmin, 1), slack=tmin < SLACK_N, limit_hit=c["limit"]))
        st.done += 1
        if st.done >= st.count:
            self._advance()

    # ---------------------------------------------------------------- Auswertung
    def _strokes(self, *groups) -> List[StrokeStats]:
        return [e for s in self.steps if s.group in groups for e in s.events if isinstance(e, StrokeStats)]

    def _evaluate_model(self):
        points = [(e["acc_m_s2"], e["force_n"]) for s in self.steps if s.group == "free" for e in s.events]
        fit = fit_mass_friction(points)
        if fit:
            self.mass_kg, self.friction_n = fit
            self.model_measured = True
        else:
            self.mass_kg, self.friction_n = FALLBACK_MASS_KG, FALLBACK_FRICTION_N
            self.message = ("Freilauf nicht plausibel (Seil vermutlich gebremst) – Masse/Reibung geschätzt. "
                            "Für eine Messung «Schritt wiederholen» und den Griff ganz loslassen.")
        accs = [e.return_acc_m_s2 for e in self._strokes("load")]
        a95 = float(np.percentile(accs, 95)) if accs else 0.0
        need_n = self.mass_kg * a95 + self.friction_n + TENSION_MARGIN_N
        self.required_recovery_pct = round(min(RECOVERY_MAX_PCT, max(RECOVERY_MIN_PCT, self._pct(need_n))), 1)

    def _best_recovery_guess(self) -> int:
        """Bester Rückzug aus den Rückzugsstufen: kein Durchhängen, beste Bewertung, sonst der kleinste."""
        stages = [s for s in self.steps if s.group == "rec" and s.events]
        ok = [s for s in stages if sum(e.slack for e in s.events) <= 1]
        if not ok:
            return int(min(RECOVERY_MAX_PCT, math.ceil(self.required_recovery_pct or self._base["recovery_pct"])))
        # Stufen ab dem berechneten Mindestwert (mit Spannungsreserve) bevorzugen
        safe = [s for s in ok if s.level >= math.floor(self.required_recovery_pct or 0)]
        ok = safe or ok
        best_rating = max((s.rating or 0) for s in ok)
        if best_rating > 0:
            ok = [s for s in ok if (s.rating or 0) == best_rating]
        return int(min(s.level for s in ok))

    def _best_pull(self) -> float:
        stages = [s for s in self.steps if s.group == "pull" and s.events]
        rated = [s for s in stages if s.rating]
        if not rated:
            return self._base["pull_pct"]
        best = max(s.rating for s in rated)
        cand = [s.level for s in rated if s.rating == best]
        return self._base["pull_pct"] if self._base["pull_pct"] in cand else min(cand)

    def _speed_rpm(self) -> float:
        rets = [e.return_peak_m_s for e in self._strokes("load", "rec", "pull", "check")]
        if not rets:
            return self._base["speed_rpm"]
        v = max(rets) if len(rets) < 10 else float(np.percentile(rets, 99))
        rpm = v * SPEED_MARGIN / self.rpm_to_m_s
        return float(min(SPEED_MAX_RPM, max(SPEED_MIN_RPM, math.ceil(rpm / 100.0) * 100)))

    def _recommend(self) -> dict:
        return {"pull_pct": float(self._best_pull()), "recovery_pct": float(self._best_recovery_guess()),
                "speed_rpm": self._speed_rpm()}

    def _finish(self):
        rec = self._recommend()
        notes = []
        check = [e for e in self._strokes("check")]
        if check:
            # Nachkorrektur, wenn die Prüfung Durchhängen bzw. die Drehzahlgrenze zeigt
            if sum(e.slack for e in check) > 1:
                if rec["recovery_pct"] < RECOVERY_MAX_PCT:
                    rec["recovery_pct"] = min(RECOVERY_MAX_PCT, rec["recovery_pct"] + 2)
                    notes.append("Bei der Prüfung hing das Seil kurz durch – Rückzug erhöht.")
                else:
                    notes.append(f"Bei der Prüfung hing das Seil kurz durch; der Rückzug ist schon an der Grenze "
                                 f"von {RECOVERY_MAX_PCT:.0f} %. Beim sehr schnellen Zurückholen etwas ruhiger werden.")
            if sum(e.limit_hit for e in check) > 1:
                if rec["speed_rpm"] < SPEED_MAX_RPM:
                    rec["speed_rpm"] = min(SPEED_MAX_RPM, rec["speed_rpm"] + 300)
                    notes.append("Bei der Prüfung lief das Seil an der Drehzahlgrenze – Grenze erhöht.")
                else:
                    notes.append(f"Das Seil erreicht beim Zurückholen die Grenze von {SPEED_MAX_RPM:.0f} rpm.")
        self.result = {"recommended": rec, "notes": notes}
        self.state = "done"

    def report(self) -> dict:
        """Alle Messwerte (für die Datei im Log-Ordner)."""
        with self.lock:
            def ev(e):
                return e if isinstance(e, dict) else e.__dict__
            return {"current": self.current, "model": {"mass_kg": self.mass_kg, "friction_n": self.friction_n,
                                                       "measured": self.model_measured,
                                                       "required_recovery_pct": self.required_recovery_pct},
                    "result": self.result, "applied": self.applied,
                    "steps": [{"group": s.group, "title": s.title, "level": s.level, "pull_pct": s.pull_pct,
                               "recovery_pct": s.recovery_pct, "speed_rpm": s.speed_rpm, "load_pct": s.load_pct,
                               "rating": s.rating, "events": [ev(e) for e in s.events]} for s in self.steps]}

    # ---------------------------------------------------------------- Anzeige
    def summary(self) -> dict:
        with self.lock:
            def stage_info(s: Step):
                strokes = [e for e in s.events if isinstance(e, StrokeStats)]
                info = {"group": s.group, "title": s.title, "level": s.level, "done": s.done, "count": s.count,
                        "rating": s.rating}
                if s.group == "free":
                    accs = [e["acc_m_s2"] for e in s.events]
                    info["acc_m_s2"] = round(statistics.median(accs), 2) if accs else None
                elif strokes:
                    info.update(
                        return_peak_m_s=round(max(e.return_peak_m_s for e in strokes), 2),
                        return_acc_m_s2=round(statistics.median(e.return_acc_m_s2 for e in strokes), 1),
                        min_tension_n=round(min(e.min_tension_n for e in strokes), 1),
                        slack=sum(e.slack for e in strokes),
                        limit_hits=sum(e.limit_hit for e in strokes),
                        length_m=round(statistics.median(e.length_m for e in strokes), 2))
                return info
            st = self.step
            return {
                "state": self.state,
                "index": self.index,
                "total": len(self.steps),
                "planned_more": not self.result and not any(s.group == "check" for s in self.steps),
                "step": None if st is None else {
                    "title": st.title, "instruction": st.instruction, "done": st.done, "count": st.count,
                    "rate": st.rate, "group": st.group},
                "message": self.message,
                "live": dict(self.live),
                "model": {"mass_kg": None if self.mass_kg is None else round(self.mass_kg, 2),
                          "friction_n": None if self.friction_n is None else round(self.friction_n, 1),
                          "measured": self.model_measured,
                          "required_recovery_pct": self.required_recovery_pct},
                "stages": [stage_info(s) for s in self.steps],
                "current": dict(self.current),
                "result": self.result,
                "applied": self.applied,
                "n_per_pct": round(self._force(1.0), 2),
            }


def _slope(points) -> float:
    """Steigung einer Ausgleichsgeraden durch (t, y)."""
    t0 = points[0][0]
    ts = [p[0] - t0 for p in points]; ys = [p[1] for p in points]
    n = len(points); mt = sum(ts) / n; my = sum(ys) / n
    den = sum((t - mt) ** 2 for t in ts)
    return sum((t - mt) * (y - my) for t, y in zip(ts, ys)) / den if den > 0 else 0.0
