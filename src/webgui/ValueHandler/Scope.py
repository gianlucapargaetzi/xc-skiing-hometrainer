from ValueHandler.ValueHandlerInterface import ValueHandler
from HardwareController.HardwareController import MeasurementValues


import numpy as np

HYSTERESIS_CNT = 5

NUM_POINTS_PER_CURVE = 1000
MUTLIPLIER = NUM_POINTS_PER_CURVE/100



from typing import List
class Scope(ValueHandler):
    def __init__(self):
        ValueHandler.__init__(self, "Scope")
        self._last_cycle_measurements: List[np.ndarray] = []


        self._last_measurements: List[np.ndarray] = []

        self._last_value_cache: List[np.ndarray] = []
        self._processed = False


    def evaluateValue(self, measurement_value: np.ndarray):
        if len(self._last_value_cache) >= HYSTERESIS_CNT:
            self._last_value_cache.pop(0)

        self._last_value_cache.append(measurement_value)


        upwards_motion = all(value[1] > 0 for value in self._last_value_cache)
        if upwards_motion:
            if self._processed:
                return
            

            # Consider push motion finished when 5 continuous upwards spead are readout. At this point to the processing.
            meas = np.stack(self._last_cycle_measurements)
            print(meas.shape)


            self._last_cycle_measurements.clear()
            self._processed = True
            return
        
        downwards_motion = all(value[1] < 0 for value in self._last_value_cache)

        if downwards_motion:
            if self._processed:
                self._last_cycle_measurements.append(item for item in self._last_value_cache)
                self._processed = False
            else:
                self._last_cycle_measurements.append(measurement_value)
            
        

    

    