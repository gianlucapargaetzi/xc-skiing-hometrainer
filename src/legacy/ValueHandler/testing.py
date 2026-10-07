    def evaluateValue(self, measurement_value: np.ndarray):
        if len(self._last_value_cache) >= HYSTERESIS_CNT:
            self._last_value_cache.pop(0)

        self._last_value_cache.append(measurement_value)


        upwards_motion = all(value.speed > 0 for value in self._last_value_cache)
        if upwards_motion:
            if self._processed:
                return
            
            self._last_cycle_measurements.clear()
            # Consider push motion finished when 5 continuous upwards spead are readout. At this point to the processing.
            self._processed = True
            return
        
        downwards_motion = all(value.speed < 0 for value in self._last_value_cache)

        if downwards_motion:
            if self._processed:
                self._last_cycle_measurements.append(item for item in self._last_value_cache)
                self._processed = False
            else:
                self._last_cycle_measurements.append(measurement_value)