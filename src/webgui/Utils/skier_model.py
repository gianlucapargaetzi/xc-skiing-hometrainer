# Utils/skier_model.py – virtueller Skifahrer für Tempo, Distanz und (im Skifahrer-Modus) den Widerstand

import math
from dataclasses import dataclass
from typing import Optional

G = 9.81


@dataclass(frozen=True)
class Terrain:
    slope_percent: float = 0.0  # positiv = bergauf
    mu: float = 0.03            # Gleitreibung Ski/Schnee


class VirtualSkier:
    """
    Längsdynamik eines Langläufers:

        m · dv/dt = F_vortrieb − µ·m·g·cos(θ) − m·g·sin(θ) − ½·ρ·CdA·v²

    Der Vortrieb kann als Kraft (Skifahrer-Modus) oder als Leistung (Profil-Modus,
    gemessene Leistung am Seil) vorgegeben werden. Die Leistung wird energetisch
    integriert, damit auch aus dem Stand (v = 0) beschleunigt werden kann.
    Rückwärtsrollen wird nicht modelliert (v >= 0).
    """

    MAX_DT_S = 0.1  # längere Lücken (z.B. Kommunikationsaussetzer) werden begrenzt

    def __init__(self, mass_kg: float, cda_m2: float = 0.45, air_density_kg_m3: float = 1.2):
        if mass_kg <= 0:
            raise ValueError("mass_kg muss > 0 sein")
        self.mass_kg = float(mass_kg)
        self.cda_m2 = float(cda_m2)
        self.air_density = float(air_density_kg_m3)
        self.speed_m_s = 0.0
        self.distance_m = 0.0

    def resistance_force_n(self, speed_m_s: float, terrain: Terrain) -> float:
        theta = math.atan(terrain.slope_percent / 100.0)
        m_g = self.mass_kg * G
        friction = terrain.mu * m_g * math.cos(theta)
        gravity = m_g * math.sin(theta)
        air = 0.5 * self.air_density * self.cda_m2 * speed_m_s * speed_m_s
        return friction + gravity + air

    def step(self, dt_s: float, terrain: Terrain, propulsive_force_n: float = 0.0, propulsive_power_w: float = 0.0) -> float:
        """Integriert einen Zeitschritt und gibt die neue Geschwindigkeit [m/s] zurück."""
        if dt_s <= 0:
            return self.speed_m_s
        dt_s = min(dt_s, self.MAX_DT_S)

        v0 = self.speed_m_s

        # 1) Leistung -> kinetische Energie
        v = v0
        if propulsive_power_w > 0:
            v = math.sqrt(v * v + 2.0 * propulsive_power_w * dt_s / self.mass_kg)

        # 2) Kräfte (Vortrieb, Reibung, Steigung, Luft)
        accel = (max(0.0, propulsive_force_n) - self.resistance_force_n(v, terrain)) / self.mass_kg
        v = max(0.0, v + accel * dt_s)

        self.distance_m += 0.5 * (v0 + v) * dt_s
        self.speed_m_s = v
        return v

    def steady_state_speed(self, power_w: float, terrain: Terrain) -> float:
        """Konstante Geschwindigkeit, bei der die Leistung den Widerstand gerade deckt (zur Kontrolle)."""
        if power_w <= 0:
            return 0.0
        lo, hi = 0.0, 30.0
        for _ in range(60):
            v = 0.5 * (lo + hi)
            if v * self.resistance_force_n(v, terrain) > power_w:
                hi = v
            else:
                lo = v
        return 0.5 * (lo + hi)


def stroke_peak_force_n(resistance_n: float, cycle_s: float, push_s: float, profile_mean: float,
                        force_scale: float = 1.0, max_force_n: float = 150.0) -> float:
    """
    Spitzenkraft am Seil, bei der ein Stoss den Widerstand des virtuellen Skifahrers über den
    ganzen Zyklus gerade ausgleicht (Kraftstoss im Stoss = Widerstand × Zykluszeit):

        F_mittel_im_Stoss = F_widerstand · T_zyklus / T_stoss
        F_spitze          = F_mittel_im_Stoss / Mittelwert der Profilform

    Bergab (Widerstand <= 0) gibt es keinen Stosswiderstand, nur den Grundzug.
    """
    if resistance_n <= 0 or push_s <= 0 or profile_mean <= 0:
        return 0.0
    ratio = min(max(cycle_s / push_s, 1.5), 4.0)
    return min(force_scale * resistance_n * ratio / profile_mean, max_force_n)


class StrokeForcePlanner:
    """
    Legt die Spitzenkraft des Kraftprofils im Skifahrer-Modus fest – nur einmal pro Stoss
    (an der Zyklusgrenze), nicht innerhalb des Stosses. Dadurch gibt es keine schnelle
    Rückkopplung Seilgeschwindigkeit -> Kraft (die bei 20–40 ms Latenz zum Ruckeln führte).

    Änderungen werden pro Stoss auf max_step_n begrenzt; gestartet wird bei 0 N, die Kraft
    baut sich also über die ersten Stösse sanft auf.
    """

    EMA_ALPHA = 0.3

    def __init__(self, profile_mean: float, force_scale: float = 1.0, max_force_n: float = 150.0,
                 max_step_n: float = 20.0, cycle_s: float = 1.2, push_s: float = 0.45):
        self.profile_mean = float(profile_mean)
        self.force_scale = float(force_scale)
        self.max_force_n = float(max_force_n)
        self.max_step_n = float(max_step_n)
        self.cycle_s = float(cycle_s)
        self.push_s = float(push_s)
        self.peak_force_n = 0.0
        self.target_force_n = 0.0

    def update(self, resistance_n: float, cycle_s: Optional[float] = None, push_s: Optional[float] = None) -> float:
        """An jeder Zyklusgrenze aufrufen. Gibt die Spitzenkraft für den nächsten Stoss zurück."""
        if cycle_s and 0.3 <= cycle_s <= 5.0:
            self.cycle_s += self.EMA_ALPHA * (cycle_s - self.cycle_s)
        if push_s and 0.1 <= push_s <= 2.0:
            self.push_s += self.EMA_ALPHA * (push_s - self.push_s)

        self.target_force_n = stroke_peak_force_n(
            resistance_n, self.cycle_s, self.push_s, self.profile_mean, self.force_scale, self.max_force_n
        )
        step = max(-self.max_step_n, min(self.target_force_n - self.peak_force_n, self.max_step_n))
        self.peak_force_n = max(0.0, min(self.peak_force_n + step, self.max_force_n))
        return self.peak_force_n


def force_to_torque_pct(force_n: float, drum_radius_m: float, rated_torque_nm: float) -> float:
    """Seilkraft [N] -> Drehmoment in % des Motor-Nenndrehmoments."""
    if rated_torque_nm <= 0:
        return 0.0
    return 100.0 * force_n * drum_radius_m / rated_torque_nm


def intensity_to_slope_percent(intensity_pct: float, base_slope_percent: float, slope_per_intensity_pct: float) -> float:
    """Skifahrer-Modus: Intensität 100 % = Grundsteigung, jedes % mehr/weniger = slope_per_intensity_pct.
    Intensität <= 0 (Controller inaktiv) -> Grundsteigung."""
    if intensity_pct is None or intensity_pct <= 0:
        return base_slope_percent
    return base_slope_percent + (float(intensity_pct) - 100.0) * slope_per_intensity_pct


class RopeSpeedEstimator:
    """Seilgeschwindigkeit [m/s] aus der Encoderposition (Zug = positiv), mit Ausreisserbegrenzung
    und exponentieller Glättung. Unabhängig von Einheiten des Drehzahlregisters."""

    MAX_PLAUSIBLE_M_S = 10.0

    def __init__(self, dist_per_rev_mm: float, alpha: float = 0.5, counts_per_rev: int = 65536):
        """alpha = Gewicht des neuen Messwerts (1 = ungeglättet, kleiner = stärker geglättet)."""
        self._m_per_count = dist_per_rev_mm / 1000.0 / counts_per_rev
        self._alpha = min(1.0, max(0.01, alpha))
        self._last_counts: Optional[int] = None
        self._last_t: Optional[float] = None
        self.speed_m_s = 0.0

    def update(self, t: float, position_counts: Optional[int]) -> float:
        if position_counts is None:
            return self.speed_m_s
        if self._last_counts is not None and self._last_t is not None:
            dt = t - self._last_t
            if 0 < dt <= VirtualSkier.MAX_DT_S:
                # Beim Zug nimmt die Encoderposition ab
                raw = -(position_counts - self._last_counts) * self._m_per_count / dt
                raw = max(-self.MAX_PLAUSIBLE_M_S, min(raw, self.MAX_PLAUSIBLE_M_S))
                self.speed_m_s = self._alpha * raw + (1.0 - self._alpha) * self.speed_m_s
        self._last_counts = position_counts
        self._last_t = t
        return self.speed_m_s


def estimate_rated_torque_nm(power_w: float, torque_pct: float, rope_speed_m_s: float, drum_radius_m: float) -> Optional[float]:
    """Schätzt das Motor-Nenndrehmoment aus P = T·ω mit T = torque_pct/100 · T_nenn.
    Nur aussagekräftig während eines kräftigen Zugs; enthält die Verluste des Antriebs."""
    if power_w <= 0 or torque_pct <= 0 or rope_speed_m_s <= 0 or drum_radius_m <= 0:
        return None
    omega = rope_speed_m_s / drum_radius_m
    return power_w / (torque_pct / 100.0 * omega)
