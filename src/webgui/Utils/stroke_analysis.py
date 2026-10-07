# Utils/stroke_analysis.py – Auswertung pro Doppelstockschub (ohne Hardware testbar)

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Sequence, Tuple

import numpy as np

from Utils.zones import get_reference_zone_key

# Richtungserkennung mit Deadband (robuster für erste Züge)
SPEED_DEADBAND = 2.0
# Lücken zwischen zwei Messpunkten über diesem Wert werden nicht integriert
MAX_SAMPLE_GAP_S = 0.25
MAX_VALID_SPM = 100


def safe_mean(values) -> float:
    if len(values) == 0:
        return 0.0
    value = float(np.mean(values))
    if np.isnan(value):
        return 0.0
    return value


def time_weighted_mean(values: Sequence[float], timestamps_s: Sequence[float], max_gap_s: float = MAX_SAMPLE_GAP_S) -> float:
    """Trapez-Mittelwert über die Zeit; Lücken > max_gap_s werden ausgelassen.
    Ohne gültiges Zeitintervall wird auf das einfache Mittel zurückgefallen."""
    if len(values) != len(timestamps_s):
        return safe_mean(values)

    integral = 0.0
    total_dt = 0.0
    for i in range(1, len(values)):
        dt = float(timestamps_s[i]) - float(timestamps_s[i - 1])
        if dt <= 0 or dt > max_gap_s:
            continue
        integral += 0.5 * (float(values[i - 1]) + float(values[i])) * dt
        total_dt += dt

    if total_dt <= 0:
        return safe_mean(values)
    return integral / total_dt


def calculate_swing_efficiency_pct(cycle_duration_s, zero_power_duration_s) -> float:
    if cycle_duration_s is None or cycle_duration_s <= 0:
        return 0.0

    zero_power_duration_s = max(0.0, min(float(zero_power_duration_s), float(cycle_duration_s)))
    efficiency_pct = 100.0 * (1.0 - (zero_power_duration_s / float(cycle_duration_s)))
    return max(0.0, min(efficiency_pct, 100.0))


def calculate_torque_power_index(mean_power_w, mean_target_torque_pct) -> float:
    if mean_target_torque_pct is None or mean_target_torque_pct <= 0:
        return 0.0
    return float(mean_power_w) / float(mean_target_torque_pct)


def calculate_push_phase_energy_j(positions_mm, power_values, timestamps_s, swing_start_mm, swing_end_mm) -> float:
    """Arbeit [J] im Schwungbereich; der Drive meldet Bremsleistung negativ."""
    if not positions_mm or not power_values or not timestamps_s:
        return 0.0

    if not (len(positions_mm) == len(power_values) == len(timestamps_s)):
        return 0.0

    energy_j = 0.0

    for i in range(1, len(positions_mm)):
        try:
            x0 = float(positions_mm[i - 1])
            x1 = float(positions_mm[i])
            p0 = float(power_values[i - 1])
            p1 = float(power_values[i])
            t0 = float(timestamps_s[i - 1])
            t1 = float(timestamps_s[i])
        except (TypeError, ValueError):
            continue

        dt = t1 - t0
        if dt <= 0 or dt > MAX_SAMPLE_GAP_S:
            continue

        x_mid = 0.5 * (x0 + x1)
        if not (swing_start_mm <= x_mid <= swing_end_mm):
            continue

        p0_active = abs(p0) if p0 < 0 else 0.0
        p1_active = abs(p1) if p1 < 0 else 0.0
        energy_j += 0.5 * (p0_active + p1_active) * dt

    return max(0.0, energy_j)


def calculate_reference_push_energy_j(reference_zone_key, training_targets) -> Tuple[float, Optional[float], Optional[float]]:
    if not reference_zone_key:
        return 0.0, None, None

    combined = (training_targets or {}).get("combined_zones", {})
    zone = combined.get(reference_zone_key, {})
    if not zone:
        return 0.0, None, None

    spm_cfg = zone.get("spm", {})
    xski_cfg = zone.get("xski_power", {})

    ref_spm = spm_cfg.get("target_spm")
    ref_power_w = xski_cfg.get("high_w")

    if ref_power_w is None:
        ref_power_w = xski_cfg.get("low_w")

    try:
        ref_spm = float(ref_spm)
        ref_power_w = float(ref_power_w)
    except (TypeError, ValueError):
        return 0.0, None, None

    if ref_spm <= 0 or ref_power_w <= 0:
        return 0.0, None, None

    ref_cycle_duration_s = 60.0 / ref_spm
    return float(ref_power_w * ref_cycle_duration_s), ref_spm, ref_power_w


def calculate_push_phase_utilization_pct(actual_energy_j, reference_energy_j) -> float:
    try:
        actual_energy_j = float(actual_energy_j)
        reference_energy_j = float(reference_energy_j)
    except (TypeError, ValueError):
        return 0.0

    if reference_energy_j <= 0:
        return 0.0

    return 100.0 * (actual_energy_j / reference_energy_j)


@dataclass
class StrokeResult:
    timestamp: datetime  # UTC
    duration_s: float
    push_duration_s: float  # Zeit mit Zugleistung im Zyklus
    cadence_spm: int
    heart_rate: float
    mean_power_w: float
    mean_target_torque_pct: float
    mean_controller_torque_pct: float
    applied_torque_pct: float
    swing_efficiency_pct: float
    torque_power_index: float
    push_phase_energy_j: float
    reference_push_energy_j: float
    push_phase_utilization_pct: float
    reference_zone_key: Optional[str]
    reference_spm: Optional[float]
    reference_power_w: Optional[float]
    distance_m: float
    total_distance_m: float
    pace_s500: int

    def to_record(self) -> dict:
        """Datensatz für den TCX-Export."""
        return {
            "timestamp": self.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "sequence_freq": round(self.cadence_spm / 2),
            "cadence_spm": self.cadence_spm,
            "power": self.mean_power_w,
            "heart_rate": self.heart_rate,
            # TCX ext:Torque soll die Intervall-/Controller-Vorgabe enthalten
            # (z.B. 60, 70, ..., 180 % max_torque_pct), nicht den positionsabhängigen
            # aktuell geschriebenen Drive-Torque am Zyklusende. Letzterer liegt am
            # Zugende oft wieder nahe min_torque_pct und führte im Export zu konstanten
            # Werten wie 20.0.
            "torque": round(self.mean_controller_torque_pct, 1),
            "controller_torque_pct": round(self.mean_controller_torque_pct, 1),
            "applied_torque_pct": round(self.applied_torque_pct, 1),
            "distance": self.total_distance_m,
            "swing_efficiency_pct": round(self.swing_efficiency_pct, 1),
            "mean_target_torque_pct": round(self.mean_target_torque_pct, 1),
            "torque_power_index": round(self.torque_power_index, 3),
            "push_phase_energy_j": round(self.push_phase_energy_j, 2),
            "reference_push_energy_j": round(self.reference_push_energy_j, 2) if self.reference_push_energy_j else 0.0,
            "push_phase_utilization_pct": round(self.push_phase_utilization_pct, 1),
            "reference_zone_key": self.reference_zone_key,
            "reference_spm": round(self.reference_spm, 1) if self.reference_spm else None,
            "reference_power_w": round(self.reference_power_w, 1) if self.reference_power_w else None,
        }


class StrokeAnalyzer:
    """
    Sammelt die Messpunkte eines Zyklus und wertet ihn aus, sobald die Bewegungsrichtung
    von "Seil wird eingezogen" (speed > 0) auf "Zug" (speed < 0) wechselt.

    Der erste Richtungswechsel startet nur die Zeitmessung (der Teilzug davor wird verworfen).
    """

    def __init__(self, swing_start_mm: float, swing_end_mm: float):
        self.swing_start_mm = swing_start_mm
        self.swing_end_mm = swing_end_mm

        self._old_dir = False
        self._cycle_start_t: Optional[float] = None
        self._cycle_start_distance_m = 0.0
        self._zero_power_start_t: Optional[float] = None
        self._zero_power_duration_s = 0.0
        self._reset_buffers()

        # Sitzungswerte
        self.stroke_count = 0
        self.total_distance_m = 0.0
        self.avg_power_w = 0.0
        self.avg_pace_s500 = 0.0
        self.last_cadence_spm = 0.0
        self.last_pace_s500 = 0
        self.last_power_w = 0.0

    def _reset_buffers(self):
        self._active_power: List[float] = []
        self._applied_torque: List[float] = []
        self._controller_torque: List[float] = []
        self._pos_mm: List[float] = []
        self._raw_power: List[float] = []
        self._time_s: List[float] = []

    def add_sample(self, t: float, pos_mm: float, speed: float, raw_power: float,
                   applied_torque_pct: float, controller_torque_pct: float) -> bool:
        """Messpunkt hinzufügen. Gibt True zurück, wenn damit ein Zyklus abgeschlossen ist
        (dann close_cycle() aufrufen)."""
        if raw_power < 0:
            active_power = abs(raw_power)
            if self._zero_power_start_t is not None:
                self._zero_power_duration_s += t - self._zero_power_start_t
                self._zero_power_start_t = None
        else:
            active_power = 0.0
            if self._zero_power_start_t is None:
                self._zero_power_start_t = t

        self._active_power.append(active_power)
        self._applied_torque.append(applied_torque_pct)
        self._controller_torque.append(controller_torque_pct)
        self._pos_mm.append(pos_mm)
        self._raw_power.append(raw_power)
        self._time_s.append(t)

        if speed > SPEED_DEADBAND:
            actual_dir = True
        elif speed < -SPEED_DEADBAND:
            actual_dir = False
        else:
            actual_dir = self._old_dir

        cycle_complete = self._old_dir and not actual_dir
        self._old_dir = actual_dir
        return cycle_complete

    @property
    def last_active_power_w(self) -> float:
        return self._active_power[-1] if self._active_power else 0.0

    def close_cycle(self, t: float, heart_rate, training_targets, total_distance_m: float) -> Optional[StrokeResult]:
        """Zyklus abschliessen. Liefert None für den ersten bzw. einen ungültigen Zyklus.
        total_distance_m = Gesamtdistanz des virtuellen Skifahrers zum Zeitpunkt t."""
        # Eine laufende Nullleistungsphase gehört nur bis zur Zyklusgrenze zu diesem Zug
        if self._zero_power_start_t is not None:
            self._zero_power_duration_s += t - self._zero_power_start_t
            self._zero_power_start_t = t

        try:
            if self._cycle_start_t is None:
                return None
            return self._evaluate(t, heart_rate, training_targets, total_distance_m)
        finally:
            self._cycle_start_t = t
            self._cycle_start_distance_m = total_distance_m
            self._zero_power_duration_s = 0.0
            self._reset_buffers()

    def _evaluate(self, t, heart_rate, training_targets, total_distance_m) -> Optional[StrokeResult]:
        duration_s = t - self._cycle_start_t
        cadence_spm = round(60.0 / duration_s) if duration_s > 0 else 0
        if cadence_spm > MAX_VALID_SPM or cadence_spm <= 0:
            return None

        mean_power = time_weighted_mean(self._active_power, self._time_s)
        push_duration_s = sum(
            min(self._time_s[i] - self._time_s[i - 1], MAX_SAMPLE_GAP_S)
            for i in range(1, len(self._time_s))
            if self._active_power[i] > 0 and self._time_s[i] > self._time_s[i - 1]
        )
        mean_target_torque_pct = safe_mean(self._applied_torque)
        mean_controller_torque_pct = safe_mean(self._controller_torque)
        swing_efficiency_pct = calculate_swing_efficiency_pct(duration_s, self._zero_power_duration_s)
        torque_power_index = calculate_torque_power_index(mean_power, mean_target_torque_pct)

        reference_zone_key = get_reference_zone_key(heart_rate, cadence_spm, training_targets)
        push_energy_j = calculate_push_phase_energy_j(
            self._pos_mm, self._raw_power, self._time_s, self.swing_start_mm, self.swing_end_mm
        )
        reference_energy_j, reference_spm, reference_power_w = calculate_reference_push_energy_j(
            reference_zone_key, training_targets
        )
        utilization_pct = calculate_push_phase_utilization_pct(push_energy_j, reference_energy_j)

        distance_m = max(0.0, total_distance_m - self._cycle_start_distance_m)
        self.total_distance_m = total_distance_m

        speed_m_s = distance_m / max(duration_s, 1e-3) if distance_m > 0 else 0.0
        pace_s500 = int(round(500.0 / speed_m_s)) if speed_m_s > 0 else 0

        self.stroke_count += 1
        n = float(self.stroke_count)
        self.avg_power_w = ((n - 1.0) * self.avg_power_w + mean_power) / n
        self.avg_pace_s500 = ((n - 1.0) * self.avg_pace_s500 + pace_s500) / n
        self.last_cadence_spm = float(cadence_spm)
        self.last_pace_s500 = pace_s500
        self.last_power_w = float(mean_power)

        return StrokeResult(
            timestamp=datetime.fromtimestamp(t, timezone.utc),
            duration_s=duration_s,
            push_duration_s=push_duration_s,
            cadence_spm=cadence_spm,
            heart_rate=heart_rate,
            mean_power_w=mean_power,
            mean_target_torque_pct=mean_target_torque_pct,
            mean_controller_torque_pct=mean_controller_torque_pct,
            applied_torque_pct=self._applied_torque[-1] if self._applied_torque else 0.0,
            swing_efficiency_pct=swing_efficiency_pct,
            torque_power_index=torque_power_index,
            push_phase_energy_j=push_energy_j,
            reference_push_energy_j=reference_energy_j,
            push_phase_utilization_pct=utilization_pct,
            reference_zone_key=reference_zone_key,
            reference_spm=reference_spm,
            reference_power_w=reference_power_w,
            distance_m=distance_m,
            total_distance_m=self.total_distance_m,
            pace_s500=pace_s500,
        )
