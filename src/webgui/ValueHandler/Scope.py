from ValueHandler.ValueHandlerInterface import ValueHandler
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from BasicWebGUI import BackendNode, Backend
from scipy.interpolate import interp1d
import numpy as np
from typing import List

# Neu: global_config importieren
from Utils.global_config import global_config

HYSTERESIS_CNT = 3
ANALYSIS_AMOUNT = 4
VECTOR_SIZE_MULTIPLIER = 1
MIN_X_VALUE = 0
MAX_X_VALUE = 100
VEC_LENGTH = (MAX_X_VALUE - MIN_X_VALUE) * VECTOR_SIZE_MULTIPLIER + 1


class Scope(ValueHandler, BackendNode):

    def __init__(self):
        ValueHandler.__init__(self, "Scope")
        BackendNode.__init__(self, "IntervalIntensityControllerBackend", update_interval=None)
        self._speed_cache: List[float] = []
        self._cycles: List[np.ndarray] = []
        self._last_cycle_measurements: List[np.ndarray] = []
        self._processed = False
        self._x_vec = np.linspace(MIN_X_VALUE, MAX_X_VALUE, VEC_LENGTH)
        self._data: dict = {}
        self._summary_data: dict = {}
        self._total_distance: float = 0.0
        Backend().registerNode(self)

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

    # ---- Neu: HR-Zonen-/Farb-Berechnung ----
    @staticmethod
    def _hr_zone_and_color(hr: float, max_hr: float):
        """
        Liefert (zone:int, color:str, pct:float) anhand von hr/max_hr.
        Zonen-Definition:
          Z1: <60%, Z2: 60-69%, Z3: 70-79%, Z4: 80-89%, Z5: >=90%
        Farben:
          Z1 #4CAF50, Z2 #8BC34A, Z3 #FFC107, Z4 #FF9800, Z5 #e53935
        """
        if hr is None or max_hr is None or max_hr <= 0:
            return None, "#9E9E9E", None  # Grau bei unbekannt
        pct = float(hr) / float(max_hr)
        if pct < 0.60:
            return 1, "#4CAF50", pct
        elif pct < 0.70:
            return 2, "#8BC34A", pct
        elif pct < 0.80:
            return 3, "#FFC107", pct
        elif pct < 0.90:
            return 4, "#FF9800", pct
        else:
            return 5, "#e53935", pct

    def set_summary_values(self, heart_rate: float, mean_power: float, cadence: float, distance: float, totalDistance: float):
        # Neu: Farbe/Zone/Prozent für Herzfrequenz bestimmen
        zone, color, pct = self._hr_zone_and_color(heart_rate, getattr(global_config, "max_hr", None))

        self._summary_data = {
            'heart_rate': heart_rate,
            'heart_rate_pct': pct,       # z.B. 0.83 für 83% von max_hr
            'heart_rate_zone': zone,     # 1..5 oder None
            'heart_rate_color': color,   # Hex-Farbe
            'mean_power': mean_power,
            'cadence': cadence,
            'distance': distance,
            'totalDistance': totalDistance
        }

        Backend().publish("scope_summary", self._summary_data)

    def evaluateValue(self, measurement_value: np.ndarray):
        self._speed_cache.append(measurement_value[1])
        if len(self._speed_cache) > HYSTERESIS_CNT:
            self._speed_cache = self._speed_cache[-HYSTERESIS_CNT:]

        if measurement_value[1] <= 0:
            self._last_cycle_measurements.append(measurement_value)
            self._processed = False
            return

        if not self._processed and all(v > 0 for v in self._speed_cache):
            if len(self._last_cycle_measurements) > 0:
                vals = np.stack(self._last_cycle_measurements).T
                speed_interpolated = interp1d(vals[0,:], vals[1,:], kind='linear', fill_value="extrapolate")(self._x_vec)
                load_interpolated = interp1d(vals[0,:], vals[2,:], kind='linear', fill_value="extrapolate")(self._x_vec)
                power_interpolated = interp1d(vals[0,:], vals[3,:], kind='linear', fill_value="extrapolate")(self._x_vec)

                self._cycles.append(np.stack([speed_interpolated, load_interpolated, power_interpolated]))
                if len(self._cycles) > ANALYSIS_AMOUNT:
                    self._cycles = self._cycles[-ANALYSIS_AMOUNT:]

                cycles = np.stack(self._cycles)
                mean = np.mean(cycles, axis=0)
                stddev = np.std(cycles, axis=0)

                self._data = {
                    'x': self._x_vec.tolist(),
                    'speed': {'mean': mean[0,:].tolist(), 'stddev': stddev[0,:].tolist()},
                    'load': {'mean': mean[1,:].tolist(), 'stddev': stddev[1,:].tolist()},
                    'power': {'mean': mean[2,:].tolist(), 'stddev': stddev[2,:].tolist()}
                }
                self.publish()
            self._last_cycle_measurements.clear()
            self._processed = True
