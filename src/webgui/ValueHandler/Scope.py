from ValueHandler.ValueHandlerInterface import ValueHandler
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from BasicWebGUI import BackendNode, Backend
from scipy.interpolate import interp1d

import numpy as np

HYSTERESIS_CNT = 3 # Amount of continuous negative speed measurements needed for processing to be triggered

ANALYSIS_AMOUNT = 4 # Amount of curves to be used for mean and std dev calculation

# Resolution of vector
VECTOR_SIZE_MULTIPLIER = 1

# Assume that vector values get passed "normalised", so 0 - 100%
MIN_X_VALUE = 0
MAX_X_VALUE = 100

VEC_LENGTH = (MAX_X_VALUE - MIN_X_VALUE) * VECTOR_SIZE_MULTIPLIER + 1

from typing import List
class Scope(ValueHandler, BackendNode):
    def __init__(self):
        ValueHandler.__init__(self, "Scope")
        BackendNode.__init__(self, "IntervalIntensityControllerBackend", update_interval=None) # No publishing via socket IO...
        self._last_cycle_measurements: List[np.ndarray] = []


        self._speed_cache: List[float] = []
        self._cycles: List[np.ndarray] = []
        self._last_cycle_measurements: List[np.ndarray] = []
        self._processed = False
        self._x_vec = np.linspace(MIN_X_VALUE, MAX_X_VALUE, VEC_LENGTH)
        self._data: dict = {}
        Backend().registerNode(self)

    def reset(self):
        self._speed_cache.clear()
        self._cycles.clear()
        self._last_cycle_measurements.clear()
        self._processed = False
        pass

    def publish(self):
        return Backend().publish("scope_values", self._data)
    
    def evaluateValue(self, measurement_value: np.ndarray):
        """Process one new measurement value readout from the Motor controller using the HW interface

        Args:
            measurement_value (np.ndarray): Measurement values of one Readout iteration of the hardware controller with content [Position, Velocity, Torque, Power]
        """
        # print(measurement_value[1])
        self._speed_cache.append(measurement_value[1])
        if len(self._speed_cache) > HYSTERESIS_CNT:
            self._speed_cache = self._speed_cache[-HYSTERESIS_CNT:] 

        if measurement_value[1] <= 0:
            self._last_cycle_measurements.append(measurement_value)
            self._processed = False
            return
    

        if not self._processed:
            if  all([ v > 0 for v in self._speed_cache ]) :
                # print("Processing")
                if len(self._last_cycle_measurements) > 0:
                    vals = np.stack(self._last_cycle_measurements).T
                    interpolator = interp1d(vals[0,:], vals[1,:], kind='linear', fill_value="extrapolate")
                    speed_interpolated = interpolator(self._x_vec)

                    interpolator = interp1d(vals[0,:], vals[2,:], kind='linear', fill_value="extrapolate")
                    load_interpolated = interpolator(self._x_vec)

                    interpolator = interp1d(vals[0,:], vals[3,:], kind='linear', fill_value="extrapolate")
                    power_interpolated = interpolator(self._x_vec)



                    self._cycles.append(np.stack([-1 * speed_interpolated, load_interpolated, -1 *power_interpolated]))
                    if len(self._cycles) > ANALYSIS_AMOUNT:
                        self._cycles = self._cycles[-ANALYSIS_AMOUNT:]

                    cycles =  np.stack(self._cycles)
                    mean = np.mean(cycles, axis=0)
                    stddev = np.std(cycles, axis=0)

                    self._data = {
                        'x': self._x_vec.tolist(), 
                        'speed': {'mean': mean[0,:].tolist(),    'stddev': stddev[0,:].tolist()},
                        'load': {'mean': mean[1,:].tolist(),     'stddev': stddev[1,:].tolist()},
                        'power': {'mean': mean[2,:].tolist(),    'stddev': stddev[2,:].tolist()}
                        }
                    self.publish()
                # pass
                self._last_cycle_measurements.clear()
                self._processed = True



