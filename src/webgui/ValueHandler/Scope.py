from ValueHandler.ValueHandlerInterface import ValueHandler
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from BasicWebGUI import BackendNode, Backend
from scipy.interpolate import interp1d
import numpy as np
from typing import List, Dict, Any, Optional, Tuple

HYSTERESIS_CNT = 3
ANALYSIS_AMOUNT = 4
VECTOR_SIZE_MULTIPLIER = 1

MIN_X_VALUE = 0
MAX_X_VALUE = 2000
VEC_LENGTH = (MAX_X_VALUE - MIN_X_VALUE) * VECTOR_SIZE_MULTIPLIER + 1


class Scope(ValueHandler, BackendNode):
    COLOR_MAP = {
        "z1": "#4CAF50",
        "z2": "#2196F3",
        "z3": "#FFC107",
        "z4": "#FF9800",
        "z5": "#e53935",
    }

    LABEL_MAP = {
        "z1": "Z1 (Easy)",
        "z2": "Z2 (Z2)",
        "z3": "Z3 (Tempo)",
        "z4": "Z4 (Intervall)",
        "z5": "Z5 (High)",
    }

    def __init__(self, max_hr_bpm: float = None, ftp_w: float = None, training_targets: dict = None):
        ValueHandler.__init__(self, "Scope")
        BackendNode.__init__(self, "IntervalIntensityControllerBackend", update_interval=None)

        self._speed_cache: List[float] = []
        self._cycles: List[np.ndarray] = []
        self._last_cycle_measurements: List[np.ndarray] = []
        self._processed = False
        self._x_vec = np.linspace(MIN_X_VALUE, MAX_X_VALUE, VEC_LENGTH)
        self._data: Dict[str, Any] = {}
        self._summary_data: Dict[str, Any] = {}
        self._total_distance: float = 0.0

        self.max_hr_bpm = self._safe_float(max_hr_bpm, 0.0)
        self.ftp_w = self._safe_float(ftp_w, 0.0)

        if not isinstance(training_targets, dict):
            raise ValueError("Scope benötigt training_targets aus ConfigManager.")

        if not training_targets.get("hr_zones"):
            raise ValueError("Scope benötigt hr_zones in training_targets.")

        if not training_targets.get("skierg_spm_zones"):
            raise ValueError("Scope benötigt skierg_spm_zones in training_targets.")

        self.training_targets = training_targets

        Backend().registerNode(self)

    @staticmethod
    def _safe_float(value, default=0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def reset(self):
        self._speed_cache.clear()
        self._cycles.clear()
        self._last_cycle_measurements.clear()
        self._processed = False
        self._total_distance = 0.0

    def publish(self):
        Backend().publish("scope_values", self._data)
        return Backend().publish("scope_summary", self._summary_data)

    def log_message(self, message: str):
        Backend().publish("scope_log", {"message": message})

    def _get_hr_zone_key_and_color(self, hr: float) -> Tuple[Optional[str], str, Optional[float], str]:
        hr_zones = self.training_targets.get("hr_zones", {})
        if hr is None or not hr_zones:
            return None, "#9E9E9E", None, "Unknown"

        try:
            hr = float(hr)
        except (TypeError, ValueError):
            return None, "#9E9E9E", None, "Unknown"

        z1_low = hr_zones.get("z1", {}).get("low_bpm")
        z2_low = hr_zones.get("z2", {}).get("low_bpm")
        z3_low = hr_zones.get("z3", {}).get("low_bpm")
        z4_low = hr_zones.get("z4", {}).get("low_bpm")
        z5_low = hr_zones.get("z5", {}).get("low_bpm")
        z5_high = hr_zones.get("z5", {}).get("high_bpm")

        max_hr_for_pct = self.max_hr_bpm if self.max_hr_bpm > 0 else self._safe_float(z5_high, 0.0)
        pct = round((hr / max_hr_for_pct) * 100, 1) if max_hr_for_pct > 0 else None

        if z5_low is not None and hr >= z5_low:
            zone_key = "z5"
        elif z4_low is not None and hr >= z4_low:
            zone_key = "z4"
        elif z3_low is not None and hr >= z3_low:
            zone_key = "z3"
        elif z2_low is not None and hr >= z2_low:
            zone_key = "z2"
        elif z1_low is not None and hr >= z1_low:
            zone_key = "z1"
        else:
            return None, "#9E9E9E", pct, "Unknown"

        return (
            zone_key,
            self.COLOR_MAP.get(zone_key, "#9E9E9E"),
            pct,
            self.LABEL_MAP.get(zone_key, "Unknown"),
        )

    def _get_spm_zone_key_and_color(self, cadence_spm: float) -> Tuple[Optional[str], str, List[str], str]:
        spm_zones = self.training_targets.get("skierg_spm_zones", {})
        if cadence_spm is None or not spm_zones:
            return None, "#9E9E9E", [], "Unknown"

        try:
            cadence_spm = float(cadence_spm)
        except (TypeError, ValueError):
            return None, "#9E9E9E", [], "Unknown"

        z1_high = spm_zones.get("z1", {}).get("high_spm")
        z2_high = spm_zones.get("z2", {}).get("high_spm")
        z3_high = spm_zones.get("z3", {}).get("high_spm")
        z4_high = spm_zones.get("z4", {}).get("high_spm")

        if z1_high is not None and cadence_spm <= z1_high:
            zone_key = "z1"
        elif z2_high is not None and cadence_spm <= z2_high:
            zone_key = "z2"
        elif z3_high is not None and cadence_spm <= z3_high:
            zone_key = "z3"
        elif z4_high is not None and cadence_spm <= z4_high:
            zone_key = "z4"
        else:
            zone_key = "z5"

        return (
            zone_key,
            self.COLOR_MAP.get(zone_key, "#9E9E9E"),
            [self.LABEL_MAP.get(zone_key, "Unknown")],
            self.LABEL_MAP.get(zone_key, "Unknown"),
        )

    def set_summary_values(
        self,
        heart_rate: float,
        mean_power: float,
        cadence_spm: float,
        distance: float,
        totalDistance: float,
        swing_efficiency_pct: float = None,
        mean_target_torque_pct: float = None,
        torque_power_index: float = None,
        push_phase_energy_j: float = None,
        reference_push_energy_j: float = None,
        push_phase_utilization_pct: float = None,
        reference_zone_key: str = None,
        reference_spm: float = None,
        reference_power_w: float = None
    ):
        hr_zone_key, hr_color, hr_pct, hr_zone_label = self._get_hr_zone_key_and_color(heart_rate)
        spm_zone_key, spm_color, spm_matches, spm_zone_label = self._get_spm_zone_key_and_color(cadence_spm)

        self._summary_data = {
            "heart_rate": heart_rate,
            "heart_rate_pct": hr_pct,
            "heart_rate_zone": hr_zone_key,
            "heart_rate_zone_label": hr_zone_label,
            "heart_rate_color": hr_color,
            "max_hr_bpm": self.max_hr_bpm,

            "mean_power": mean_power,

            "cadence_spm": cadence_spm,
            "cadence": cadence_spm,  # abwärtskompatibel

            "spm_zone": spm_zone_key,
            "spm_zone_label": spm_zone_label,
            "spm_zone_color": spm_color,
            "spm_zone_matches": spm_matches,

            "ftp_w": self.ftp_w,
            "training_targets": self.training_targets,

            "distance": distance,
            "totalDistance": totalDistance,

            "swing_efficiency_pct": swing_efficiency_pct,
            "mean_target_torque_pct": mean_target_torque_pct,
            "torque_power_index": torque_power_index,

            "push_phase_energy_j": push_phase_energy_j,
            "reference_push_energy_j": reference_push_energy_j,
            "push_phase_utilization_pct": push_phase_utilization_pct,
            "reference_zone_key": reference_zone_key,
            "reference_spm": reference_spm,
            "reference_power_w": reference_power_w
        }

        Backend().publish("scope_summary", self._summary_data)

    def evaluateValue(self, measurement_value: np.ndarray):
        measurement_value = measurement_value.copy()

        x_mm = float(measurement_value[0])

        if x_mm < MIN_X_VALUE:
            measurement_value[0] = MIN_X_VALUE
        elif x_mm > MAX_X_VALUE:
            measurement_value[0] = MAX_X_VALUE

        self._speed_cache.append(measurement_value[1])
        if len(self._speed_cache) > HYSTERESIS_CNT:
            self._speed_cache = self._speed_cache[-HYSTERESIS_CNT:]

        if measurement_value[1] <= 0:
            self._last_cycle_measurements.append(measurement_value)
            self._processed = False
            return

        if not self._processed and all(v > 0 for v in self._speed_cache):
            if len(self._last_cycle_measurements) > 1:
                vals = np.stack(self._last_cycle_measurements).T

                sort_idx = np.argsort(vals[0, :])
                x_vals = vals[0, sort_idx]
                speed_vals = vals[1, sort_idx]
                load_vals = vals[2, sort_idx]
                power_vals = vals[3, sort_idx]

                unique_x, unique_indices = np.unique(x_vals, return_index=True)
                speed_vals = speed_vals[unique_indices]
                load_vals = load_vals[unique_indices]
                power_vals = power_vals[unique_indices]

                if len(unique_x) > 1:
                    speed_interpolated = interp1d(
                        unique_x, speed_vals, kind="linear", fill_value="extrapolate"
                    )(self._x_vec)

                    load_interpolated = interp1d(
                        unique_x, load_vals, kind="linear", fill_value="extrapolate"
                    )(self._x_vec)

                    power_interpolated = interp1d(
                        unique_x, power_vals, kind="linear", fill_value="extrapolate"
                    )(self._x_vec)

                    self._cycles.append(
                        np.stack([speed_interpolated, load_interpolated, power_interpolated])
                    )
                    if len(self._cycles) > ANALYSIS_AMOUNT:
                        self._cycles = self._cycles[-ANALYSIS_AMOUNT:]

                    cycles = np.stack(self._cycles)
                    mean = np.mean(cycles, axis=0)
                    stddev = np.std(cycles, axis=0)

                    self._data = {
                        "x": self._x_vec.tolist(),
                        "speed": {
                            "mean": mean[0, :].tolist(),
                            "stddev": stddev[0, :].tolist()
                        },
                        "load": {
                            "mean": mean[1, :].tolist(),
                            "stddev": stddev[1, :].tolist()
                        },
                        "power": {
                            "mean": mean[2, :].tolist(),
                            "stddev": stddev[2, :].tolist()
                        }
                    }
                    self.publish()

            self._last_cycle_measurements.clear()
            self._processed = True